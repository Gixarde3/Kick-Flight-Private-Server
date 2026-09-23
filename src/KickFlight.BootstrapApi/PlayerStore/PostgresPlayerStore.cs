using System.Text.Json;
using Npgsql;

namespace KickFlight.BootstrapApi.PlayerStore;

// Player state in PostgreSQL, which is what the deployment uses.
//
// Shape, and why it is not fully normalised: the four things a service actually queries - identity, the
// display name, the currencies and the battle rank - are real columns, and the rest of the state is one
// `state jsonb` document. Decks, owned discs, costume gears and the pending gear roll are only ever read and
// written as a whole (the API loads a player, mutates, saves), so normalising them would buy nothing and cost
// a mapping layer plus the chance of a half-applied save. See deploy/README.md.
//
// Migrations are embedded rather than run by hand so a fresh database reaches the current schema by starting
// the API once. `schema_meta` records which have been applied, so applying is idempotent and additive.
public sealed class PostgresPlayerStore : IPlayerStore
{
    private const int SchemaVersion = 1;

    private static readonly (int Version, string Sql)[] Migrations =
    [
        (1, """
            create table players (
                id                  bigint primary key,
                uuid                text not null unique,
                display_name        text,
                kicker_id           integer not null,
                kicker_costume_id   integer not null,
                active_deck_number  integer not null,
                item_jet_coins      integer not null,
                item_paid_jet_coins integer not null,
                item_disc_force     integer not null,
                item_kick_points    integer not null,
                state               jsonb   not null,
                created_at          timestamptz not null default now(),
                updated_at          timestamptz not null default now()
            );

            -- Player ids stay numeric and dense from 1000001: the client parses the id with long.TryParse and
            -- renders "Player NNNN" from the low digits, and the previous in-memory allocator started at
            -- 1000002 for the second device on the strength of that.
            create sequence player_id_seq as bigint start with 1000001;

            create table sessions (
                access_token text primary key,
                player_id    bigint not null references players(id) on delete cascade,
                session_key  bytea  not null,
                created_at   timestamptz not null default now()
            );

            create index sessions_player_id_idx on sessions (player_id);

            create table player_ranks (
                player_id       bigint  not null references players(id) on delete cascade,
                battle_rule_type integer not null,
                battle_point    integer not null,
                rank            integer not null,
                updated_at      timestamptz not null default now(),
                primary key (player_id, battle_rule_type)
            );
            """)
    ];

    private readonly NpgsqlDataSource _dataSource;
    private readonly ILogger<PostgresPlayerStore> _logger;

    public PostgresPlayerStore(ILogger<PostgresPlayerStore> logger, string connectionString)
    {
        _logger = logger;
        _dataSource = NpgsqlDataSource.Create(connectionString);
        Migrate();
    }

    // Serialised across instances because two API containers starting at once would race here; the advisory
    // lock is held for the length of the migration and released with the connection.
    private void Migrate()
    {
        using var connection = _dataSource.OpenConnection();
        using (var createMeta = connection.CreateCommand())
        {
            createMeta.CommandText = """
                create table if not exists schema_meta (
                    version    integer primary key,
                    applied_at timestamptz not null default now()
                )
                """;
            createMeta.ExecuteNonQuery();
        }

        using var advisory = connection.CreateCommand();
        advisory.CommandText = "select pg_advisory_lock(48095837)";
        advisory.ExecuteNonQuery();
        try
        {
            foreach (var (version, sql) in Migrations)
            {
                using var check = connection.CreateCommand();
                check.CommandText = "select 1 from schema_meta where version = $1";
                check.Parameters.AddWithValue(version);
                if (check.ExecuteScalar() is not null) continue;

                _logger.LogInformation("Applying player store migration {Version}", version);
                // DDL and the version row in one transaction: a crash cannot leave the schema half-applied
                // with the version recorded, which would skip the rest forever.
                using var transaction = connection.BeginTransaction();
                using (var apply = connection.CreateCommand())
                {
                    apply.Transaction = transaction;
                    apply.CommandText = sql;
                    apply.ExecuteNonQuery();
                }
                using (var record = connection.CreateCommand())
                {
                    record.Transaction = transaction;
                    record.CommandText = "insert into schema_meta (version) values ($1)";
                    record.Parameters.AddWithValue(version);
                    record.ExecuteNonQuery();
                }
                transaction.Commit();
            }
        }
        finally
        {
            using var unlock = connection.CreateCommand();
            unlock.CommandText = "select pg_advisory_unlock(48095837)";
            unlock.ExecuteNonQuery();
        }

        // Fail fast and loudly if the database is ahead of the code: a missing column would otherwise surface
        // as an unrelated exception on the first request.
        using var verify = connection.CreateCommand();
        verify.CommandText = "select coalesce(max(version), 0) from schema_meta";
        var applied = Convert.ToInt32(verify.ExecuteScalar());
        if (applied < SchemaVersion)
        {
            throw new InvalidOperationException(
                $"Player store migrations did not reach version {SchemaVersion} (at {applied}).");
        }
    }

    public long ResolvePlayerId(string uuid)
    {
        using var connection = _dataSource.OpenConnection();

        // The whole identity guarantee, in one statement: insert-if-absent then read back, so a uuid that is
        // already known keeps its player id no matter how many devices race here or how often the API
        // restarts. nextval is evaluated before the conflict is detected, so a lost race burns an id - that is
        // the intended trade, since ids need only be unique, not contiguous.
        using var command = connection.CreateCommand();
        command.CommandText = """
            insert into players (
                id, uuid, kicker_id, kicker_costume_id, active_deck_number,
                item_jet_coins, item_paid_jet_coins, item_disc_force, item_kick_points, state)
            values (nextval('player_id_seq'), $1, $2, $3, $4, $5, $6, $7, $8, '{}'::jsonb)
            on conflict (uuid) do nothing
            returning id
            """;
        command.Parameters.AddWithValue(uuid);
        var defaults = new SessionState();
        command.Parameters.AddWithValue(defaults.KickerId);
        command.Parameters.AddWithValue(defaults.KickerCostumeId);
        command.Parameters.AddWithValue(defaults.ActiveDeckNumber);
        command.Parameters.AddWithValue(defaults.ItemJetCoins);
        command.Parameters.AddWithValue(defaults.ItemPaidJetCoins);
        command.Parameters.AddWithValue(defaults.ItemDiscForce);
        command.Parameters.AddWithValue(defaults.ItemKickPoints);

        var inserted = command.ExecuteScalar();
        if (inserted is not null and not DBNull) return Convert.ToInt64(inserted);

        using var read = connection.CreateCommand();
        read.CommandText = "select id from players where uuid = $1";
        read.Parameters.AddWithValue(uuid);
        return Convert.ToInt64(read.ExecuteScalar());
    }

    public SessionState? TryLoad(long playerId)
    {
        using var connection = _dataSource.OpenConnection();
        using var command = connection.CreateCommand();
        command.CommandText = """
            select display_name, kicker_id, kicker_costume_id, active_deck_number,
                   item_jet_coins, item_paid_jet_coins, item_disc_force, item_kick_points, state
            from players where id = $1
            """;
        command.Parameters.AddWithValue(playerId);

        using var reader = command.ExecuteReader();
        if (!reader.Read()) return null;

        // The document carries everything except the identity and the columns that a service queries; those
        // are authoritative in their own columns and are copied over whatever the document said.
        var state = DecodeDocument(reader.GetString(8));
        state.UserId = playerId.ToString();
        state.UserName = reader.IsDBNull(0) ? "" : reader.GetString(0);
        state.KickerId = reader.GetInt32(1);
        state.KickerCostumeId = reader.GetInt32(2);
        state.ActiveDeckNumber = reader.GetInt32(3);
        state.ItemJetCoins = reader.GetInt32(4);
        state.ItemPaidJetCoins = reader.GetInt32(5);
        state.ItemDiscForce = reader.GetInt32(6);
        state.ItemKickPoints = reader.GetInt32(7);
        return state;
    }

    private SessionState DecodeDocument(string json)
    {
        if (string.IsNullOrWhiteSpace(json) || json == "{}") return new SessionState();
        try
        {
            var state = JsonSerializer.Deserialize<SessionState>(json);
            if (state is null) return new SessionState();
            state.CostumeGears ??= new Dictionary<int, int[]>();
            state.PendingGear ??= new PendingGearState();
            state.ItemAmounts ??= new Dictionary<int, int>();
            state.Discs ??= new Dictionary<int, UserDiscState>();
            state.Decks ??= new Dictionary<int, List<int>>();
            return state;
        }
        catch (JsonException ex)
        {
            // A corrupt document must not take the player's whole account down, but it must be visible.
            _logger.LogError(ex, "Player state document is not readable as JSON; starting from defaults");
            return new SessionState();
        }
    }

    public void Save(SessionState state, string? uuid = null)
    {
        if (state.PlayerId == 0)
        {
            _logger.LogWarning("Refusing to save a state whose UserId {UserId} is not a player id", state.UserId);
            return;
        }

        // The document excludes nothing today, but the columns above are the ones services read, so they are
        // written from the state and the document keeps the rest. uuid is only ever set at creation, and is
        // left alone here: a device that reconnects must not be able to move a player to another uuid.
        var document = JsonSerializer.Serialize(state);

        using var connection = _dataSource.OpenConnection();
        using var command = connection.CreateCommand();
        command.CommandText = """
            update players set
                display_name        = nullif($2, ''),
                kicker_id           = $3,
                kicker_costume_id   = $4,
                active_deck_number  = $5,
                item_jet_coins      = $6,
                item_paid_jet_coins = $7,
                item_disc_force     = $8,
                item_kick_points    = $9,
                state               = $10::jsonb,
                updated_at          = now()
            where id = $1
            """;
        command.Parameters.AddWithValue(state.PlayerId);
        // The empty name is stored as NULL: it is the absence of a name that ends onboarding, and NULL says
        // that unambiguously where '' could also be read as a name someone chose.
        command.Parameters.AddWithValue(state.UserName);
        command.Parameters.AddWithValue(state.KickerId);
        command.Parameters.AddWithValue(state.KickerCostumeId);
        command.Parameters.AddWithValue(state.ActiveDeckNumber);
        command.Parameters.AddWithValue(state.ItemJetCoins);
        command.Parameters.AddWithValue(state.ItemPaidJetCoins);
        command.Parameters.AddWithValue(state.ItemDiscForce);
        command.Parameters.AddWithValue(state.ItemKickPoints);
        command.Parameters.AddWithValue(document);

        if (command.ExecuteNonQuery() == 0)
        {
            _logger.LogWarning("Save for player {PlayerId} matched no row", state.PlayerId);
        }
    }

    public void SaveSession(string accessToken, long playerId, byte[] key)
    {
        using var connection = _dataSource.OpenConnection();
        using var command = connection.CreateCommand();
        command.CommandText = """
            insert into sessions (access_token, player_id, session_key) values ($1, $2, $3)
            on conflict (access_token) do update set player_id = excluded.player_id, session_key = excluded.session_key
            """;
        command.Parameters.AddWithValue(accessToken);
        command.Parameters.AddWithValue(playerId);
        command.Parameters.AddWithValue(key);
        command.ExecuteNonQuery();
    }

    public SessionRecord? FindSession(string accessToken)
    {
        using var connection = _dataSource.OpenConnection();
        using var command = connection.CreateCommand();
        command.CommandText = "select player_id, session_key from sessions where access_token = $1";
        command.Parameters.AddWithValue(accessToken);
        using var reader = command.ExecuteReader();
        return reader.Read() ? new SessionRecord(reader.GetInt64(0), reader.GetFieldValue<byte[]>(1)) : null;
    }

    public RankState LoadRank(long playerId, int battleRuleType)
    {
        using var connection = _dataSource.OpenConnection();
        using var command = connection.CreateCommand();
        command.CommandText = "select battle_point, rank from player_ranks where player_id = $1 and battle_rule_type = $2";
        command.Parameters.AddWithValue(playerId);
        command.Parameters.AddWithValue(battleRuleType);
        using var reader = command.ExecuteReader();
        return reader.Read() ? new RankState(reader.GetInt32(0), reader.GetInt32(1)) : RankProgression.Starting;
    }

    public void SaveRank(long playerId, int battleRuleType, RankState rank)
    {
        using var connection = _dataSource.OpenConnection();
        using var command = connection.CreateCommand();
        command.CommandText = """
            insert into player_ranks (player_id, battle_rule_type, battle_point, rank)
            values ($1, $2, $3, $4)
            on conflict (player_id, battle_rule_type) do update set
                battle_point = excluded.battle_point,
                rank         = excluded.rank,
                updated_at   = now()
            """;
        command.Parameters.AddWithValue(playerId);
        command.Parameters.AddWithValue(battleRuleType);
        command.Parameters.AddWithValue(rank.BattlePoint);
        command.Parameters.AddWithValue(rank.Rank);
        command.ExecuteNonQuery();
    }

    public bool IsNameTaken(string name, long exceptPlayerId)
    {
        using var connection = _dataSource.OpenConnection();
        using var command = connection.CreateCommand();
        command.CommandText =
            "select exists (select 1 from players where lower(display_name) = lower($1) and id <> $2)";
        command.Parameters.AddWithValue(name);
        command.Parameters.AddWithValue(exceptPlayerId);
        return Convert.ToBoolean(command.ExecuteScalar());
    }
}
