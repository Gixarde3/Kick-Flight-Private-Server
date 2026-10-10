using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KickFlight.BootstrapApi;

/// <summary>
/// Server-side store for uploaded battle replays (Colorful /battle/upload) plus the two data-driven tabs the
/// unmodified client renders: one BattleReplayChannel type-2 row per kicker, and one type-3 "Featured" row whose
/// content is the rotation's matches with the most human players.
///
/// Storage layout (directory from <c>Replays:Directory</c>, default <c>.local/replays</c>):
/// <code>
///   blobs/&lt;replayId&gt;.bin    the uploaded gzip archive, byte-for-byte (this is the plaintext D2CCodec.Encode
///                            wraps for /battleReplay/play)
///   meta/&lt;replayId&gt;.json    the index row, one per replay; every file here rebuilds the in-memory index
///   featured.json            the frozen Featured rotation (survives restarts)
/// </code>
///
/// The archive the client uploads is NOT a zip: it is <c>gzip( [TYPE_UINT][uint32-le length][TYPE_STRING]
/// [int32-le nameLen][utf8 name][raw bytes] ... )</c>. See docs/REPLAYS.md for the RVAs that pin the encoding.
/// </summary>
public sealed class BattleReplayService
{
    public const string DirectoryKey = "Replays:Directory";
    public const string MaxUploadBytesKey = "Replays:MaxUploadBytes";
    public const string MaxDecompressedBytesKey = "Replays:MaxDecompressedBytes";
    public const string KickerChannelSizeKey = "Replays:KickerChannelSize";
    public const string FeaturedCountKey = "Replays:FeaturedCount";
    public const string RotationHoursKey = "Replays:RotationHours";
    public const string FeaturedWindowHoursKey = "Replays:FeaturedWindowHours";
    public const string RetentionDaysKey = "Replays:RetentionDays";
    public const string MaxTotalBytesKey = "Replays:MaxTotalBytes";
    public const string KeyLifetimeMinutesKey = "Replays:KeyLifetimeMinutes";

    public const string DefaultRelativeDirectory = ".local/replays";
    public const long DefaultMaxUploadBytes = 64L * 1024 * 1024;          // client frames cap is 50 MiB before gzip
    public const long DefaultMaxDecompressedBytes = 256L * 1024 * 1024;
    public const int DefaultKickerChannelSize = 20;
    public const int DefaultFeaturedCount = 20;
    public const double DefaultRotationHours = 3;
    public const double DefaultRetentionDays = 30;
    public const long DefaultMaxTotalBytes = 5L * 1024 * 1024 * 1024;

    // ReplayValue value-type tags (Colorful.ReplayValue, dump.cs:531629-531646). Only the two the archive uses.
    private const byte TypeUInt = 2;
    private const byte TypeString = 6;

    // 2030 is the sentinel most other served windows use; the Featured/Kicker windows never expire.
    private const string FarFutureDatetime = "2099-12-31 23:59:59";

    private readonly string _directory;
    private readonly string _blobDirectory;
    private readonly string _metaDirectory;
    private readonly string _featuredPath;
    private readonly long _maxUploadBytes;
    private readonly long _maxDecompressedBytes;
    private readonly int _kickerChannelSize;
    private readonly int _featuredCount;
    private readonly TimeSpan _rotation;
    private readonly TimeSpan _featuredWindow;
    private readonly TimeSpan _retention;
    private readonly long _maxTotalBytes;
    private readonly TimeSpan _keyLifetime;
    private readonly TimeProvider _timeProvider;
    private readonly ILogger<BattleReplayService> _logger;

    private readonly ConcurrentDictionary<string, ReplayRecord> _records = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, PendingMatch> _pending = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, PlayKey> _playKeys = new(StringComparer.Ordinal);
    private readonly object _writeLock = new();
    private readonly object _rotationLock = new();
    private FeaturedSnapshot? _featured;

    public BattleReplayService(IConfiguration configuration, IWebHostEnvironment environment,
        TimeProvider timeProvider, ILogger<BattleReplayService> logger)
    {
        _timeProvider = timeProvider;
        _logger = logger;
        _directory = RepositoryPaths.Resolve(
            configuration[DirectoryKey] is { Length: > 0 } configured ? configured : DefaultRelativeDirectory,
            environment.ContentRootPath);
        _blobDirectory = Path.Combine(_directory, "blobs");
        _metaDirectory = Path.Combine(_directory, "meta");
        _featuredPath = Path.Combine(_directory, "featured.json");
        _maxUploadBytes = GetLong(configuration, MaxUploadBytesKey, DefaultMaxUploadBytes);
        _maxDecompressedBytes = GetLong(configuration, MaxDecompressedBytesKey, DefaultMaxDecompressedBytes);
        _kickerChannelSize = (int)GetLong(configuration, KickerChannelSizeKey, DefaultKickerChannelSize);
        _featuredCount = (int)GetLong(configuration, FeaturedCountKey, DefaultFeaturedCount);
        _rotation = TimeSpan.FromHours(GetDouble(configuration, RotationHoursKey, DefaultRotationHours));
        _featuredWindow = TimeSpan.FromHours(GetDouble(configuration, FeaturedWindowHoursKey, DefaultRotationHours * 2));
        _retention = TimeSpan.FromDays(GetDouble(configuration, RetentionDaysKey, DefaultRetentionDays));
        _maxTotalBytes = GetLong(configuration, MaxTotalBytesKey, DefaultMaxTotalBytes);
        _keyLifetime = TimeSpan.FromMinutes(GetDouble(configuration, KeyLifetimeMinutesKey, 10));

        Directory.CreateDirectory(_blobDirectory);
        Directory.CreateDirectory(_metaDirectory);
        LoadIndex();
        _logger.LogInformation(
            "Battle replays: {Count} record(s) in {Directory} (kickerChannelSize={KickerSize}, featuredCount={FeaturedCount}, rotation={Rotation}h)",
            _records.Count, _directory, _kickerChannelSize, _featuredCount, _rotation.TotalHours);
    }

    public long MaxUploadBytes => _maxUploadBytes;

    private static long GetLong(IConfiguration configuration, string key, long fallback) =>
        long.TryParse(configuration[key], out var parsed) && parsed > 0 ? parsed : fallback;

    private static double GetDouble(IConfiguration configuration, string key, double fallback) =>
        double.TryParse(configuration[key], System.Globalization.CultureInfo.InvariantCulture, out var parsed) && parsed > 0
            ? parsed : fallback;

    // ------------------------------------------------------------------ pending matches (/battle/end, custom)

    public sealed class PendingPlayer
    {
        public string UserId { get; set; } = "";
        public string Name { get; set; } = "";
        public int Rank { get; set; }
        public int KickerId { get; set; }
        public int KickerCostumeId { get; set; }
        public int FrameId { get; set; }
        public string LanguageCode { get; set; } = "";
        public int TeamType { get; set; }
        public bool Ai { get; set; }
        public bool Mvp { get; set; }
    }

    public sealed class PendingTeam
    {
        public int TeamType { get; set; }
        public int Score { get; set; }
        public int RemainingDistance { get; set; }
        public int LastRemainingDistance { get; set; }
    }

    /// <summary>The match facts /battle/end carries before (and independently of) the upload.</summary>
    public sealed class PendingMatch
    {
        public string BattleId { get; set; } = "";
        public bool Custom { get; set; }
        public int BattleRuleId { get; set; }
        public int FieldId { get; set; }
        public int HumanCount { get; set; }
        public List<PendingTeam> Teams { get; set; } = [];
        public List<PendingPlayer> Players { get; set; } = [];
        public DateTime EndUtc { get; set; }
    }

    /// <summary>Remembers the battle-end facts until the master client's /battle/upload arrives for the same id.</summary>
    public void RecordBattleEnd(PendingMatch match, DateTime nowUtc)
    {
        if (string.IsNullOrWhiteSpace(match.BattleId)) return;
        match.EndUtc = nowUtc;
        _pending[SafeId(match.BattleId)] = match;
        // The upload for a normal match usually follows within seconds; keep the map from growing without bound.
        if (_pending.Count > 2048)
        {
            foreach (var stale in _pending.Where(kv => nowUtc - kv.Value.EndUtc > TimeSpan.FromHours(6)).Select(kv => kv.Key).ToList())
                _pending.TryRemove(stale, out _);
        }
        _logger.LogInformation(
            "Recorded battle-end {BattleId} (custom={Custom}, rule={RuleId}, field={FieldId}, humans={Humans})",
            match.BattleId, match.Custom, match.BattleRuleId, match.FieldId, match.HumanCount);
    }

    // ------------------------------------------------------------------ storage records

    public sealed class ReplayPlayerRecord
    {
        public string UserId { get; set; } = "";
        public string Name { get; set; } = "";
        public int FrameId { get; set; }
        public string LanguageCode { get; set; } = "";
        public int Rank { get; set; }
        public int KickerId { get; set; }
        public int KickerCostumeId { get; set; }
        public bool MvpFlag { get; set; }
    }

    public sealed class ReplayTeamRecord
    {
        public int TeamType { get; set; }
        public int Score { get; set; }
        public int RemainingDistance { get; set; }
        public int LastRemainingDistance { get; set; }
        public List<ReplayPlayerRecord> Players { get; set; } = [];
    }

    public sealed class ReplayRecord
    {
        public string ReplayId { get; set; } = "";
        public string BattleId { get; set; } = "";
        public string ApplicationVersion { get; set; } = "";
        public string EndDatetime { get; set; } = "";
        public int BattleRuleId { get; set; }
        public int FieldId { get; set; }
        public int HumanCount { get; set; }
        public int[] KickerIds { get; set; } = [];
        public List<ReplayTeamRecord> Teams { get; set; } = [];
        public long SizeBytes { get; set; }
        public string Sha256 { get; set; } = "";
        public DateTime EndUtc { get; set; }
        public DateTime CreatedUtc { get; set; }
    }

    public sealed class FeaturedSnapshot
    {
        public DateTime RotationStartUtc { get; set; }
        public List<string> ReplayIds { get; set; } = [];
        public DateTime ComputedUtc { get; set; }
    }

    private sealed class PlayKey
    {
        public string ReplayId { get; set; } = "";
        public byte[] Key { get; set; } = [];
        public DateTime ExpiresUtc { get; set; }
    }

    private void LoadIndex()
    {
        foreach (var metaFile in Directory.EnumerateFiles(_metaDirectory, "*.json"))
        {
            try
            {
                var record = JsonSerializer.Deserialize<ReplayRecord>(File.ReadAllText(metaFile));
                if (record is null || string.IsNullOrEmpty(record.ReplayId)) continue;
                if (!File.Exists(BlobPath(record.ReplayId))) continue;
                if (string.IsNullOrEmpty(record.ApplicationVersion)) BackfillVersion(record, metaFile);
                _records[record.ReplayId] = record;
            }
            catch (Exception ex)
            {
                _logger.LogWarning("Ignoring unreadable replay metadata {File}: {Error}", metaFile, ex.Message);
            }
        }
    }

    // Replays stored before the archive parser handled path-qualified member names have no application version, and
    // the client marks such cells as an invalid version. Re-read it from the blob once and rewrite the metadata.
    private void BackfillVersion(ReplayRecord record, string metaFile)
    {
        try
        {
            var version = ParseGzip(File.ReadAllBytes(BlobPath(record.ReplayId))).AppVersion;
            if (string.IsNullOrEmpty(version)) return;
            record.ApplicationVersion = version;
            File.WriteAllText(metaFile, JsonSerializer.Serialize(record));
        }
        catch (Exception ex) when (ex is IOException or InvalidDataException or JsonException)
        {
            _logger.LogWarning("Could not backfill the version of replay {ReplayId}: {Error}", record.ReplayId, ex.Message);
        }
    }

    public string StorageDirectory => _directory;

    public IReadOnlyCollection<ReplayRecord> Records => _records.Values.ToArray();

    // ------------------------------------------------------------------ upload

    /// <summary>
    /// Stores one uploaded replay. Returns false for a duplicate battle (the master client is the only uploader, so
    /// the first upload wins), an oversized body, or an archive that does not parse.
    /// </summary>
    public bool StoreUpload(string requestedBattleId, byte[] gzip, DateTime nowUtc)
    {
        if (gzip.Length == 0 || gzip.Length > _maxUploadBytes)
        {
            _logger.LogWarning("Rejected replay upload for {BattleId}: {Bytes} bytes (cap {Cap})",
                requestedBattleId, gzip.Length, _maxUploadBytes);
            return false;
        }

        ParsedReplay parsed;
        try
        {
            parsed = ParseGzip(gzip);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Rejected replay upload for {BattleId}: archive did not parse: {Error}",
                requestedBattleId, ex.Message);
            return false;
        }

        var battleId = string.IsNullOrWhiteSpace(parsed.BattleId) ? requestedBattleId : parsed.BattleId!;
        if (string.IsNullOrWhiteSpace(battleId)) return false;
        var replayId = SafeId(battleId);

        lock (_writeLock)
        {
            if (_records.ContainsKey(replayId))
            {
                _logger.LogInformation("Ignoring duplicate replay upload for {BattleId} (first one is kept)", battleId);
                return false;
            }

            _pending.TryGetValue(SafeId(battleId), out var pending);
            pending ??= _pending.Values.FirstOrDefault(p => p.Custom && p.BattleId == requestedBattleId);

            var record = BuildRecord(replayId, battleId, parsed, pending, gzip, nowUtc);
            WriteBlob(replayId, gzip);
            WriteMeta(record);
            _records[replayId] = record;
            if (pending is not null) _pending.TryRemove(SafeId(pending.BattleId), out _);
            PruneLocked(nowUtc);
        }

        _logger.LogInformation(
            "Stored replay {ReplayId} for {BattleId}: version={AppVersion} rule={RuleId} field={FieldId} humans={Humans} size={Bytes}",
            replayId, battleId, parsed.AppVersion, parsed.BattleRuleId, parsed.FieldId,
            _records[replayId].HumanCount, gzip.Length);
        return true;
    }

    private ReplayRecord BuildRecord(string replayId, string battleId, ParsedReplay parsed, PendingMatch? pending,
        byte[] gzip, DateTime nowUtc)
    {
        // Pending roster supplies the kicker row costume ids: PlayerBattleInfo in the archive has no costume field.
        var costumeByUser = new Dictionary<string, int>(StringComparer.Ordinal);
        if (pending is not null)
        {
            foreach (var p in pending.Players)
                if (!string.IsNullOrEmpty(p.UserId) && p.KickerCostumeId > 0) costumeByUser[p.UserId] = p.KickerCostumeId;
        }

        var teams = new Dictionary<int, ReplayTeamRecord>();
        foreach (var player in parsed.Players)
        {
            if (!teams.TryGetValue(player.TeamType, out var team))
            {
                team = new ReplayTeamRecord { TeamType = player.TeamType };
                teams[player.TeamType] = team;
            }
            team.Players.Add(new ReplayPlayerRecord
            {
                UserId = player.UserId,
                Name = player.Name,
                FrameId = player.FrameId,
                LanguageCode = player.LanguageCode,
                Rank = player.Rank,
                KickerId = player.KickerId,
                KickerCostumeId = costumeByUser.GetValueOrDefault(player.UserId, 0),
                MvpFlag = !string.IsNullOrEmpty(parsed.MvpUserId) && player.UserId == parsed.MvpUserId
            });
        }

        int ScoreAt(int teamType) => teamType >= 0 && teamType < parsed.Scores.Length ? parsed.Scores[teamType] : 0;
        int MinDistanceAt(int teamType) => teamType >= 0 && teamType < parsed.MinRemaining.Length ? parsed.MinRemaining[teamType] : 0;
        int LastFlagAt(int teamType) => teamType >= 0 && teamType < parsed.LastFlag.Length ? parsed.LastFlag[teamType] : 0;

        if (teams.Count > 0)
        {
            foreach (var team in teams.Values)
            {
                team.Score = ScoreAt(team.TeamType);
                team.RemainingDistance = MinDistanceAt(team.TeamType);
                team.LastRemainingDistance = LastFlagAt(team.TeamType);
            }
        }
        else if (pending is not null)
        {
            // Nothing parsed from the archive roster: fall back to the battle-end snapshot, costumes included.
            foreach (var pendingTeam in pending.Teams)
            {
                var team = new ReplayTeamRecord
                {
                    TeamType = pendingTeam.TeamType,
                    Score = pendingTeam.Score,
                    RemainingDistance = pendingTeam.RemainingDistance,
                    LastRemainingDistance = pendingTeam.LastRemainingDistance
                };
                foreach (var p in pending.Players.Where(p => p.TeamType == pendingTeam.TeamType))
                {
                    team.Players.Add(new ReplayPlayerRecord
                    {
                        UserId = p.UserId,
                        Name = p.Name,
                        FrameId = p.FrameId,
                        LanguageCode = p.LanguageCode,
                        Rank = p.Rank,
                        KickerId = p.KickerId,
                        KickerCostumeId = p.KickerCostumeId,
                        MvpFlag = p.Mvp
                    });
                }
                teams[team.TeamType] = team;
            }
        }

        var parsedHumans = parsed.HasAiFlag
            ? parsed.Players.Count(p => !p.IsAi && !p.UserId.StartsWith("bot-", StringComparison.OrdinalIgnoreCase))
            : 0;
        var humanCount = Math.Max(parsedHumans, pending?.HumanCount ?? 0);

        var kickerIds = parsed.Players.Select(p => p.KickerId).Where(id => id > 0).Distinct().OrderBy(id => id).ToArray();
        if (kickerIds.Length == 0 && pending is not null)
            kickerIds = pending.Players.Select(p => p.KickerId).Where(id => id > 0).Distinct().OrderBy(id => id).ToArray();

        // The header's _dateTimeTicks is device wall-clock. It is only trusted when it is near the receipt time:
        // a wrong sign, a different ticks epoch or a clock-skewed phone must not put a 1970 date on the index row
        // (retention and the Featured tie-break both read this value).
        var endUtc = parsed.EndUtc is { } parsedEnd && Math.Abs((parsedEnd - nowUtc).TotalDays) <= 1 ? parsedEnd : nowUtc;
        return new ReplayRecord
        {
            ReplayId = replayId,
            BattleId = battleId,
            ApplicationVersion = parsed.AppVersion,
            EndDatetime = endUtc.ToString("yyyy-MM-dd HH:mm:ss"),
            BattleRuleId = parsed.BattleRuleId > 0 ? parsed.BattleRuleId : pending?.BattleRuleId ?? 1,
            FieldId = parsed.FieldId > 0 ? parsed.FieldId : pending?.FieldId ?? 0,
            HumanCount = humanCount,
            KickerIds = kickerIds,
            Teams = teams.Values.OrderBy(t => t.TeamType).ToList(),
            SizeBytes = gzip.Length,
            Sha256 = Convert.ToHexString(SHA256.HashData(gzip)).ToLowerInvariant(),
            EndUtc = endUtc,
            CreatedUtc = nowUtc
        };
    }

    private void WriteBlob(string replayId, byte[] gzip)
    {
        var target = BlobPath(replayId);
        var temp = target + ".tmp";
        File.WriteAllBytes(temp, gzip);
        File.Move(temp, target, overwrite: true);
    }

    private void WriteMeta(ReplayRecord record)
    {
        var target = MetaPath(record.ReplayId);
        var temp = target + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(record));
        File.Move(temp, target, overwrite: true);
    }

    private string BlobPath(string replayId) => Path.Combine(_blobDirectory, replayId + ".bin");
    private string MetaPath(string replayId) => Path.Combine(_metaDirectory, replayId + ".json");

    // ------------------------------------------------------------------ index queries

    /// <summary>The frozen Featured set for the current rotation. Recomputed when the rotation rolls; until it is full
    /// (fewer than FeaturedCount replays existed when it was computed) new replays are appended, never swapped in.</summary>
    public IReadOnlyList<ReplayRecord> GetFeatured(DateTime nowUtc)
    {
        lock (_rotationLock)
        {
            var rotationStart = RotationStart(nowUtc);
            _featured ??= LoadFeatured();
            if (_featured is null || _featured.RotationStartUtc != rotationStart)
            {
                _featured = ComputeFeatured(rotationStart, nowUtc);
                PersistFeatured(_featured);
                _logger.LogInformation("Featured rotation {Start:o}: {Count} replay(s)",
                    rotationStart, _featured.ReplayIds.Count);
            }
            else if (_featured.ReplayIds.Count < _featuredCount)
            {
                var fill = RankFeatured(nowUtc).Where(id => !_featured.ReplayIds.Contains(id))
                    .Take(_featuredCount - _featured.ReplayIds.Count).ToList();
                if (fill.Count > 0)
                {
                    _featured.ReplayIds.AddRange(fill);
                    PersistFeatured(_featured);
                }
            }

            return _featured.ReplayIds
                .Select(id => _records.GetValueOrDefault(id))
                .Where(record => record is not null)
                .Cast<ReplayRecord>()
                .ToArray();
        }
    }

    public FeaturedSnapshot? FeaturedSnapshotForTests
    {
        get { lock (_rotationLock) return _featured; }
    }

    private FeaturedSnapshot ComputeFeatured(DateTime rotationStart, DateTime nowUtc) =>
        new() { RotationStartUtc = rotationStart, ReplayIds = RankFeatured(nowUtc).Take(_featuredCount).ToList(), ComputedUtc = nowUtc };

    // Most humans first among the replays of the last window; older replays only fill what the window cannot, so a quiet
    // server still shows something.
    private IEnumerable<string> RankFeatured(DateTime nowUtc)
    {
        var windowStart = nowUtc - _featuredWindow;
        return _records.Values
            .OrderByDescending(r => r.CreatedUtc >= windowStart)
            .ThenByDescending(r => r.HumanCount)
            .ThenByDescending(r => r.EndUtc)
            .ThenByDescending(r => r.ReplayId, StringComparer.Ordinal)
            .Select(r => r.ReplayId);
    }

    public IReadOnlyList<ReplayRecord> GetLatestForKicker(int kickerId, DateTime nowUtc) =>
        _records.Values
            .Where(r => r.KickerIds.Contains(kickerId))
            .OrderByDescending(r => r.EndUtc)
            .ThenByDescending(r => r.ReplayId, StringComparer.Ordinal)
            .Take(_kickerChannelSize)
            .ToArray();

    /// <summary>Builds the /battleReplay/index body: Featured (type 3, id 1) plus one type-2 channel per kicker.</summary>
    public string BuildIndexJson(IReadOnlyList<int> kickerIds, Func<int, int> defaultCostumeId, DateTime nowUtc)
    {
        var displayStart = nowUtc.AddDays(-1).ToString("yyyy-MM-dd HH:mm:ss");
        var channels = new List<object>
        {
            new
            {
                battleReplayChannelId = 1,
                battleReplayList = BuildReplayJson(GetFeatured(nowUtc), defaultCostumeId, displayStart)
            }
        };
        foreach (var kickerId in kickerIds)
        {
            channels.Add(new
            {
                battleReplayChannelId = 1000 + kickerId,
                battleReplayList = BuildReplayJson(GetLatestForKicker(kickerId, nowUtc), defaultCostumeId, displayStart)
            });
        }

        return JsonSerializer.Serialize(new
        {
            battleReplayChannelList = channels.ToArray(),
            appMovieList = Array.Empty<object>()
        });
    }

    private static object[] BuildReplayJson(IReadOnlyList<ReplayRecord> records, Func<int, int> defaultCostumeId,
        string displayStart)
    {
        return records.Select(record => (object)new
        {
            battleReplayId = record.ReplayId,
            battleRuleId = record.BattleRuleId,
            fieldId = record.FieldId,
            endDatetime = record.EndDatetime,
            displayStartDatetime = displayStart,
            displayEndDatetime = FarFutureDatetime,
            applicationVersion = record.ApplicationVersion,
            battleReplayTeamList = record.Teams.Select(team => new
            {
                teamType = team.TeamType,
                score = team.Score,
                remainingDistance = team.RemainingDistance,
                lastRemainingDistance = team.LastRemainingDistance,
                battleReplayPlayerList = team.Players.Select(player => new
                {
                    userId = player.UserId,
                    name = player.Name,
                    frameId = player.FrameId,
                    languageCode = player.LanguageCode,
                    rank = player.Rank,
                    kickerCostumeId = player.KickerCostumeId > 0 ? player.KickerCostumeId : defaultCostumeId(player.KickerId),
                    mvpFlag = player.MvpFlag
                }).ToArray()
            }).ToArray()
        }).ToArray();
    }

    // ------------------------------------------------------------------ playback keys / blob

    /// <summary>Creates a one-shot download key and the key id the URL must carry, or ("","") for an unknown replay.</summary>
    public (string KeyId, string EncryptionKey) CreatePlayKey(string replayId, DateTime nowUtc)
    {
        if (string.IsNullOrWhiteSpace(replayId) || !_records.ContainsKey(replayId)) return ("", "");
        var key = Convert.ToHexString(RandomNumberGenerator.GetBytes(16)); // 32 ASCII chars = AES-256 key material
        var keyId = Guid.NewGuid().ToString("N");
        _playKeys[keyId] = new PlayKey { ReplayId = replayId, Key = Encoding.UTF8.GetBytes(key), ExpiresUtc = nowUtc + _keyLifetime };

        // Drop expired keys opportunistically; the map is tiny (one entry per download started in the last 10 min).
        foreach (var expired in _playKeys.Where(kv => kv.Value.ExpiresUtc < nowUtc).Select(kv => kv.Key).ToList())
            _playKeys.TryRemove(expired, out _);

        return (keyId, key);
    }

    /// <summary>Encrypts the stored blob exactly as the client expects (D2CCodec = IV || AES-256-CBC/PKCS7).</summary>
    public bool TryEncodeBlob(string keyId, DateTime nowUtc, out byte[] encoded)
    {
        encoded = [];
        if (string.IsNullOrWhiteSpace(keyId) || !_playKeys.TryGetValue(keyId, out var playKey)) return false;
        if (playKey.ExpiresUtc < nowUtc)
        {
            _playKeys.TryRemove(keyId, out _);
            return false;
        }
        var blobPath = BlobPath(playKey.ReplayId);
        if (!File.Exists(blobPath)) return false;
        var blob = File.ReadAllBytes(blobPath);
        encoded = D2CCodec.Encode(blob, playKey.Key, RandomNumberGenerator.GetBytes(D2CCodec.VectorSizeBytes));
        return true;
    }

    // ------------------------------------------------------------------ retention

    private void PruneLocked(DateTime nowUtc)
    {
        var cutoff = nowUtc - _retention;
        var pinned = new HashSet<string>(
            (_featured ?? LoadFeatured())?.ReplayIds ?? [], StringComparer.Ordinal);

        var removed = 0;
        foreach (var record in _records.Values.OrderBy(r => r.EndUtc).ToList())
        {
            if (pinned.Contains(record.ReplayId)) continue;
            // Age is measured by server receipt, not the (untrusted) header timestamp.
            var tooOld = record.CreatedUtc < cutoff;
            var totalBytes = _records.Values.Sum(r => r.SizeBytes);
            var overBudget = totalBytes > _maxTotalBytes;
            if (!tooOld && !overBudget) continue;
            _records.TryRemove(record.ReplayId, out _);
            TryDelete(BlobPath(record.ReplayId));
            TryDelete(MetaPath(record.ReplayId));
            removed++;
        }

        if (removed > 0) _logger.LogInformation("Replay retention pruned {Count} record(s)", removed);
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch (IOException) { /* best effort */ }
    }

    // ------------------------------------------------------------------ featured persistence

    private DateTime RotationStart(DateTime nowUtc)
    {
        var ticks = _rotation.Ticks;
        return ticks <= 0 ? nowUtc : new DateTime(nowUtc.Ticks - (nowUtc.Ticks % ticks), DateTimeKind.Utc);
    }

    private FeaturedSnapshot? LoadFeatured()
    {
        try
        {
            if (!File.Exists(_featuredPath)) return null;
            return JsonSerializer.Deserialize<FeaturedSnapshot>(File.ReadAllText(_featuredPath));
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Ignoring unreadable featured rotation {File}: {Error}", _featuredPath, ex.Message);
            return null;
        }
    }

    private void PersistFeatured(FeaturedSnapshot snapshot)
    {
        try
        {
            var temp = _featuredPath + ".tmp";
            File.WriteAllText(temp, JsonSerializer.Serialize(snapshot));
            File.Move(temp, _featuredPath, overwrite: true);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not persist featured rotation: {Error}", ex.Message);
        }
    }

    // ------------------------------------------------------------------ archive parsing

    private sealed class ParsedPlayer
    {
        public string UserId { get; set; } = "";
        public string Name { get; set; } = "";
        public int Rank { get; set; }
        public int KickerId { get; set; }
        public int TeamType { get; set; }
        public int FrameId { get; set; }
        public string LanguageCode { get; set; } = "";
        public bool IsAi { get; set; }
    }

    private sealed class ParsedReplay
    {
        public string? BattleId { get; set; }
        public string AppVersion { get; set; } = "";
        public int BattleRuleId { get; set; }
        public int FieldId { get; set; }
        public DateTime? EndUtc { get; set; }
        public bool HasAiFlag { get; set; }
        public string MvpUserId { get; set; } = "";
        public int[] Scores { get; set; } = [];
        public int[] MinRemaining { get; set; } = [];
        public int[] LastFlag { get; set; } = [];
        public List<ParsedPlayer> Players { get; } = [];
    }

    private ParsedReplay ParseGzip(byte[] gzip)
    {
        using var input = new MemoryStream(gzip);
        using var gunzip = new GZipStream(input, CompressionMode.Decompress);
        using var output = new MemoryStream();
        var buffer = new byte[81920];
        int read;
        while ((read = gunzip.Read(buffer, 0, buffer.Length)) > 0)
        {
            if (output.Length + read > _maxDecompressedBytes)
                throw new InvalidDataException($"decompressed archive exceeds {_maxDecompressedBytes} bytes");
            output.Write(buffer, 0, read);
        }

        var archive = ParseArchive(output.GetBuffer().AsSpan(0, (int)output.Length));
        var parsed = new ParsedReplay();
        if (archive.Header is not null)
        {
            using var header = JsonDocument.Parse(archive.Header);
            parsed.AppVersion = GetString(header.RootElement, "appVersion");
            var ticks = GetLong(header.RootElement, "dateTimeTicks");
            if (ticks > DateTime.UnixEpoch.Ticks && ticks < DateTime.MaxValue.Ticks)
            {
                try { parsed.EndUtc = new DateTime(ticks, DateTimeKind.Utc); }
                catch (ArgumentOutOfRangeException) { /* leave null */ }
            }
        }
        if (archive.Battle is not null)
        {
            using var battle = JsonDocument.Parse(archive.Battle);
            var root = battle.RootElement;
            if (TryGetProperty(root, "battleRuleInfo", out var rule))
            {
                parsed.BattleRuleId = GetInt(rule, "battleRuleId");
                parsed.FieldId = GetInt(rule, "fieldId");
            }
            if (TryGetProperty(root, "battleInfo", out var battleInfo))
            {
                parsed.BattleId = GetString(battleInfo, "battleId");
                ReadRoster(battleInfo, parsed);
            }
        }
        if (archive.Result is not null)
        {
            using var result = JsonDocument.Parse(archive.Result);
            var root = result.RootElement;
            parsed.Scores = ReadIntArray(root, "score");
            parsed.MinRemaining = ReadIntArray(root, "minRemainingDistance");
            parsed.LastFlag = ReadIntArray(root, "lastFlagProgressRate");
            parsed.MvpUserId = GetString(root, "mvpUserId");
            if (parsed.Players.Count == 0 && TryGetProperty(root, "battleInfo", out var resultRoster))
                ReadRoster(resultRoster, parsed);
            if (parsed.BattleId is null && TryGetProperty(root, "battleInfo", out _))
            {
                // The result member does not carry the battle id; nothing else to do here.
            }
        }
        return parsed;
    }

    private static void ReadRoster(JsonElement rosterElement, ParsedReplay parsed)
    {
        if (!TryGetProperty(rosterElement, "playerBattleInfos", out var players) || players.ValueKind != JsonValueKind.Array)
            return;
        var hasAiFlag = false;
        foreach (var player in players.EnumerateArray())
        {
            if (TryGetProperty(player, "isAi", out var aiProp) && aiProp.ValueKind is JsonValueKind.True or JsonValueKind.False)
                hasAiFlag = true;
            var aiId = GetInt(player, "kickerAiParameterId");
            var userId = GetString(player, "userId");
            parsed.Players.Add(new ParsedPlayer
            {
                UserId = userId,
                Name = GetString(player, "name"),
                Rank = GetInt(player, "rank"),
                KickerId = GetInt(player, "kickerId"),
                TeamType = GetInt(player, "teamType"),
                FrameId = GetInt(player, "frameId"),
                LanguageCode = GetString(player, "languageCode"),
                IsAi = (aiProp.ValueKind == JsonValueKind.True) || aiId > 0 ||
                       userId.StartsWith("bot-", StringComparison.OrdinalIgnoreCase)
            });
        }
        if (hasAiFlag) parsed.HasAiFlag = true;
    }

    public sealed class ReplayArchive
    {
        public byte[]? Header { get; set; }
        public byte[]? Battle { get; set; }
        public byte[]? Result { get; set; }
    }

    /// <summary>
    /// Reads the [TYPE_UINT][uint32-le length][TYPE_STRING][int32-le nameLen][utf8 name][raw bytes] archive.
    /// Unknown members (frames, future files) are skipped but still validated so a corrupt stream fails.
    /// </summary>
    public static ReplayArchive ParseArchive(ReadOnlySpan<byte> archive)
    {
        var result = new ReplayArchive();
        var position = 0;
        while (position < archive.Length)
        {
            if (position + 1 > archive.Length || archive[position++] != TypeUInt)
                throw new InvalidDataException("archive member length tag is not TYPE_UINT");
            if (position + 4 > archive.Length)
                throw new InvalidDataException("archive member length is truncated");
            var length = BinaryPrimitives.ReadUInt32LittleEndian(archive[position..]);
            position += 4;
            if (length > int.MaxValue)
                throw new InvalidDataException("archive member length is too large");

            if (position + 1 > archive.Length || archive[position++] != TypeString)
                throw new InvalidDataException("archive member name tag is not TYPE_STRING");
            if (position + 4 > archive.Length)
                throw new InvalidDataException("archive member name length is truncated");
            var nameLength = BinaryPrimitives.ReadInt32LittleEndian(archive[position..]);
            position += 4;
            if (nameLength < 0 || position + nameLength > archive.Length)
                throw new InvalidDataException("archive member name is truncated");
            var name = Encoding.UTF8.GetString(archive.Slice(position, nameLength));
            position += nameLength;

            if (position + (int)length > archive.Length)
                throw new InvalidDataException("archive member body is truncated");
            var body = archive.Slice(position, (int)length).ToArray();
            position += (int)length;

            // The client writes each member under its full device path (".../Replay/Work/header") and the JSON
            // members start with a UTF-8 BOM, which JsonDocument.Parse(byte[]) rejects.
            name = name[(name.LastIndexOfAny(['/', '\\']) + 1)..];
            if (body.Length >= 3 && body[0] == 0xEF && body[1] == 0xBB && body[2] == 0xBF) body = body[3..];

            switch (name)
            {
                case "header": result.Header = body; break;
                case "battle": result.Battle = body; break;
                case "result": result.Result = body; break;
            }
        }
        return result;
    }

    // ------------------------------------------------------------------ JSON helpers (client field names keep the leading underscore)

    private static bool TryGetProperty(JsonElement element, string name, out JsonElement value)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            value = default;
            return false;
        }
        if (element.TryGetProperty("_" + name, out value)) return true;
        return element.TryGetProperty(name, out value);
    }

    private static string GetString(JsonElement element, string name) =>
        TryGetProperty(element, name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString() ?? ""
            : "";

    private static int GetInt(JsonElement element, string name) =>
        TryGetProperty(element, name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var parsed)
            ? parsed
            : 0;

    private static long GetLong(JsonElement element, string name) =>
        TryGetProperty(element, name, out var value) && value.ValueKind == JsonValueKind.Number && value.TryGetInt64(out var parsed)
            ? parsed
            : 0;

    private static int[] ReadIntArray(JsonElement element, string name)
    {
        if (!TryGetProperty(element, name, out var value) || value.ValueKind != JsonValueKind.Array) return [];
        var list = new List<int>();
        foreach (var item in value.EnumerateArray())
            list.Add(item.ValueKind == JsonValueKind.Number && item.TryGetInt32(out var parsed) ? parsed : 0);
        return list.ToArray();
    }

    /// <summary>A file- and URL-safe id. battle-N / custom-... survive verbatim; anything else is hashed.</summary>
    internal static string SafeId(string battleId)
    {
        if (battleId.Length is > 0 and <= 64 && battleId.All(c =>
                char.IsAsciiLetterOrDigit(c) || c is '-' or '_'))
        {
            return battleId;
        }
        return "r-" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(battleId)))[..24].ToLowerInvariant();
    }
}
