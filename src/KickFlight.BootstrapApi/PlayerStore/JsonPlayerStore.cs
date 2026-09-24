using System.Collections.Concurrent;
using System.Text.Json;

namespace KickFlight.BootstrapApi.PlayerStore;

// The original on-disk store: one <player id>.json per player under <content root>/data/users, plus an
// identity index so a device uuid keeps its player id across restarts.
//
// This is the fallback, selected when no connection string is configured, so that local runs and the test
// suite work with no database. The deployment uses PostgresPlayerStore.
//
// Sessions are held in memory here, and deliberately: what has to survive a restart is the *identity* (so a
// returning device is not handed a different player), and that is on disk. A client whose token is lost
// re-authenticates on next launch and, because the uuid -> id mapping is durable, gets its own player back.
public sealed class JsonPlayerStore : IPlayerStore
{
    // The index file names are prefixed so they cannot collide with a save file, whose name is always a
    // bare player id. They are also excluded from the glob the deploy script uses to report user counts.
    private const string IdentityIndexFile = "_identities.json";
    private const string FirstPlayerId = "1000001";

    // The highest id this directory has ever been seen to contain, process-wide. Two stores over one directory -
    // which is what IClassFixture hands the test suite, one server per test class - would otherwise each read the
    // directory before either writes and issue the same id to two different devices, leaving two sessions to
    // overwrite each other's save file. One server in production never needs this, but it costs nothing there.
    private static readonly object IdLock = new();
    private static readonly ConcurrentDictionary<string, object> IdentityLocksByDirectory = new(StringComparer.Ordinal);
    private static long _idHighWaterMark;

    private readonly string _usersDirectory;
    private readonly ILogger<JsonPlayerStore> _logger;
    private readonly object _identityLock;
    private readonly Dictionary<string, long> _playerIdByUuid = new(StringComparer.Ordinal);
    private readonly Dictionary<string, byte[]> _keysByAccessToken = new(StringComparer.Ordinal);
    private readonly Dictionary<string, long> _playerIdByToken = new(StringComparer.Ordinal);

    public JsonPlayerStore(ILogger<JsonPlayerStore> logger, IWebHostEnvironment environment)
    {
        _logger = logger;
        _usersDirectory = Path.Combine(environment.ContentRootPath, "data", "users");
        _identityLock = IdentityLocksByDirectory.GetOrAdd(Path.GetFullPath(_usersDirectory), _ => new object());
        Directory.CreateDirectory(_usersDirectory);
        lock (_identityLock) LoadIdentityIndex();
    }

    private void LoadIdentityIndex()
    {
        var path = Path.Combine(_usersDirectory, IdentityIndexFile);
        if (!File.Exists(path)) return;
        try
        {
            var index = JsonSerializer.Deserialize<Dictionary<string, long>>(File.ReadAllText(path));
            if (index is null) return;
            foreach (var (uuid, playerId) in index) _playerIdByUuid[uuid] = playerId;
            _logger.LogInformation("Loaded {Count} device identities from {Path}", _playerIdByUuid.Count, path);
        }
        catch (Exception ex)
        {
            // Losing the index is recoverable (a returning device gets a new id) but never silent: the whole
            // point of the store is to not do that.
            _logger.LogError(ex, "Could not read the identity index at {Path}; returning devices will be re-created", path);
        }
    }

    private void PersistIdentityIndex()
    {
        try
        {
            var path = Path.Combine(_usersDirectory, IdentityIndexFile);
            var json = JsonSerializer.Serialize(_playerIdByUuid, new JsonSerializerOptions { WriteIndented = true });
            // Write-then-rename: a crash mid-write must not leave a truncated index, which would silently
            // re-issue identities to every device that then connects.
            // Stores over this directory share the identity lock, while the unique suffix also avoids
            // collisions with another process writing the same index.
            var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            File.WriteAllText(temporary, json);
            File.Move(temporary, path, overwrite: true);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Could not write the identity index; this mapping will be lost on restart");
        }
    }

    public long ResolvePlayerId(string uuid)
    {
        lock (_identityLock)
        {
            // Each instance has its own dictionary. Refresh under the directory-wide lock so a second
            // store cannot persist an older snapshot and erase identities just added by the first.
            LoadIdentityIndex();
            if (_playerIdByUuid.TryGetValue(uuid, out var existing)) return existing;

            var playerId = NextPlayerId();
            _playerIdByUuid[uuid] = playerId;
            PersistIdentityIndex();
            _logger.LogInformation("New device {Uuid} assigned player {PlayerId}", uuid, playerId);
            return playerId;
        }
    }

    // One past the highest id in use, so deleting a save file cannot make the next device inherit its id.
    private long NextPlayerId()
    {
        lock (IdLock)
        {
            long highest = Math.Max(_idHighWaterMark, long.Parse(FirstPlayerId));
            foreach (var candidate in _playerIdByUuid.Values)
            {
                if (candidate > highest) highest = candidate;
            }
            foreach (var file in Directory.EnumerateFiles(_usersDirectory, "*.json"))
            {
                var name = Path.GetFileNameWithoutExtension(file);
                if (long.TryParse(name, out var id) && id > highest) highest = id;
            }
            _idHighWaterMark = highest + 1;
            return _idHighWaterMark;
        }
    }

    public SessionState? TryLoad(long playerId)
    {
        var file = Path.Combine(_usersDirectory, $"{playerId}.json");
        if (!File.Exists(file)) return null;
        try
        {
            var loaded = JsonSerializer.Deserialize<SessionState>(File.ReadAllText(file));
            if (loaded is null) return null;
            loaded.UserId = playerId.ToString();
            // Save files written before gear support (or hand-edited with an explicit null) must load as
            // "no gear", never as a null dictionary the gear handlers would then dereference.
            loaded.CostumeGears ??= new Dictionary<int, int[]>();
            loaded.PendingGear ??= new PendingGearState();
            loaded.ItemAmounts ??= new Dictionary<int, int>();
            loaded.Discs ??= new Dictionary<int, UserDiscState>();
            loaded.Decks ??= new Dictionary<int, List<int>>();
            return loaded;
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error loading user state for {PlayerId}: {Error}", playerId, ex.Message);
            return null;
        }
    }

    public void Save(SessionState state, string? uuid = null)
    {
        if (state.PlayerId == 0)
        {
            _logger.LogWarning("Refusing to save a state whose UserId {UserId} is not a player id", state.UserId);
            return;
        }
        try
        {
            if (uuid is not null)
            {
                lock (_identityLock)
                {
                    LoadIdentityIndex();
                    if (_playerIdByUuid.TryGetValue(uuid, out var known) && known != state.PlayerId)
                    {
                        _logger.LogWarning("Device {Uuid} maps to {Known} but is saving {Actual}; keeping the mapping",
                            uuid, known, state.PlayerId);
                    }
                    else if (!_playerIdByUuid.ContainsKey(uuid))
                    {
                        _playerIdByUuid[uuid] = state.PlayerId;
                        PersistIdentityIndex();
                    }
                }
            }

            var file = Path.Combine(_usersDirectory, $"{state.PlayerId}.json");
            var json = JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(file, json);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error saving user state for {PlayerId}: {Error}", state.PlayerId, ex.Message);
        }
    }

    public void SaveSession(string accessToken, long playerId, byte[] key)
    {
        _keysByAccessToken[accessToken] = key;
        _playerIdByToken[accessToken] = playerId;
    }

    public SessionRecord? FindSession(string accessToken) =>
        _keysByAccessToken.TryGetValue(accessToken, out var key) && _playerIdByToken.TryGetValue(accessToken, out var playerId)
            ? new SessionRecord(playerId, key)
            : null;

    // Rank is not persisted in this store: it belongs to the deployment, and the fallback keeps it in memory
    // so local runs and tests see a stable value instead of the starting rank on every read.
    private readonly Dictionary<(long PlayerId, int BattleRuleType), RankState> _ranks = new();

    public RankState LoadRank(long playerId, int battleRuleType) =>
        _ranks.TryGetValue((playerId, battleRuleType), out var rank) ? rank : RankProgression.Starting;

    public void SaveRank(long playerId, int battleRuleType, RankState rank) =>
        _ranks[(playerId, battleRuleType)] = rank;

    // A directory scan, which is the honest way to answer this against files: the deployment, where the answer
    // has to be fast and exact, uses the unique index the Postgres store queries instead.
    public bool IsNameTaken(string name, long exceptPlayerId)
    {
        foreach (var file in Directory.EnumerateFiles(_usersDirectory, "*.json"))
        {
            if (!long.TryParse(Path.GetFileNameWithoutExtension(file), out var playerId)) continue; // skips the identity index
            if (playerId == exceptPlayerId) continue;
            try
            {
                using var document = JsonDocument.Parse(File.ReadAllText(file));
                if (document.RootElement.TryGetProperty(nameof(SessionState.UserName), out var prop)
                    && prop.ValueKind == JsonValueKind.String
                    && string.Equals(prop.GetString(), name, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
            catch (JsonException ex)
            {
                // An unreadable save must not block someone else's onboarding.
                _logger.LogWarning("Skipping unreadable save {File} while checking names: {Error}", file, ex.Message);
            }
        }
        return false;
    }
}
