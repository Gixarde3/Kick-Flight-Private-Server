namespace KickFlight.BootstrapApi.PlayerStore;

// A resolved session token: which player it belongs to, and the key their bodies are encrypted with.
public sealed record SessionRecord(long PlayerId, byte[] Key);

// A player's standing in one battle rule. Rank is what the client renders as a league badge.
public sealed record RankState(int BattlePoint, int Rank);

// Where player state lives.
//
// Two implementations, chosen by whether a connection string is configured (see PlayerStoreFactory):
// PostgresPlayerStore for the deployment, JsonPlayerStore for local runs and the test suite, which must not
// need a database to be reachable.
//
// Everything here is deliberately synchronous. The callers are the existing synchronous request handlers,
// reached from ~13 call sites, and Npgsql has first-class sync methods; making this async would convert a
// large part of DemoSessionApi for no benefit at this scale.
public interface IPlayerStore
{
    // The device uuid's player, created on first contact. This is the identity guarantee the store exists
    // for: the same uuid must resolve to the same player id forever, across restarts and redeploys.
    long ResolvePlayerId(string uuid);

    // The player's state, or null if that id has never been seen.
    SessionState? TryLoad(long playerId);

    // Upsert. Also records the uuid -> player id mapping when the state carries one (see SessionState).
    void Save(SessionState state, string? uuid = null);

    // Session tokens outlive the process: a restart must not drop every logged-in client and re-issue them
    // a different identity.
    void SaveSession(string accessToken, long playerId, byte[] key);

    // The session for a token, or null. A null result is a rejection, not a licence to guess: the caller
    // must not fall back to another player's session.
    SessionRecord? FindSession(string accessToken);

    // Rank per battle rule type. Absent rows read as the starting rank, so a new player needs no seeding.
    RankState LoadRank(long playerId, int battleRuleType);

    void SaveRank(long playerId, int battleRuleType, RankState rank);

    // Whether another player already goes by this name. Case-insensitive, because a name is how a player is
    // identified on the ranking and profile screens, where "Tanuki" and "tanuki" reading as two people is a bug
    // rather than a feature. `exceptPlayerId` is the caller, so re-submitting one's own name is not a clash.
    bool IsNameTaken(string name, long exceptPlayerId);
}
