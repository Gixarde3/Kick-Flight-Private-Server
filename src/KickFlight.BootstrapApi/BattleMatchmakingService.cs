using System.Collections.Concurrent;
using System.Globalization;
using System.Text.Json;
using Google.Protobuf.WellKnownTypes;
using Grpc.Core;
using OpenMatch;

namespace KickFlight.BootstrapApi;

public sealed class BattleMatchmakingService
{
    private readonly ILogger<BattleMatchmakingService> _logger;
    private readonly IPhotonServerManager _photonManager;
    private readonly ConcurrentDictionary<string, BattleEntrySession> _entriesByTicket = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, ActiveBattleRoom> _roomsByBattleId = new(StringComparer.Ordinal);
    // Luxon can outlive this API process. Seed the compact numeric suffix from
    // the current UTC second so an API restart cannot accidentally reuse a
    // still-cached Photon room from the previous process.
    private int _battleCounter = (int)(DateTimeOffset.UtcNow.ToUnixTimeSeconds() % 1_000_000_000);

    public BattleMatchmakingService(ILogger<BattleMatchmakingService> logger, IPhotonServerManager photonManager)
    {
        _logger = logger;
        _photonManager = photonManager;
    }

    public sealed class BattleEntrySession
    {
        public string TicketId { get; set; } = "";
        public string BattleEntryId { get; set; } = "";
        public string UserId { get; set; } = "";
        public string UserName { get; set; } = "";
        public int KickerId { get; set; } = 1;
        public int KickerCostumeId { get; set; } = 2010101;
        public int BattleRuleId { get; set; } = 1;
        public List<int> DeckDiscs { get; set; } = [];
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }

    public sealed class ActiveBattleRoom
    {
        public string BattleId { get; set; } = "";
        public int BattleRuleId { get; set; } = 1;
        public int FieldId { get; set; } = 101;
        public List<BattleEntrySession> HumanPlayers { get; set; } = [];
        public MatchingBattleInfo MatchingInfo { get; set; } = new();

        // --- matchmaking window (2026-09-21) ---
        // Humans keep joining until WindowDeadline; only then do bots take the empty slots. MatchingInfo stays
        // empty while the window is open (interim rosters are built on the fly), which is what keeps the
        // "room already started" replay check honest.
        public DateTime WindowDeadline { get; set; }

        /// <summary>The window closed and the final bot-filled roster was built; no further human can join.</summary>
        public bool IsFinalized { get; set; }

        /// <summary>Completes with the final roster; every waiting GetAssignments stream is parked on it.</summary>
        public TaskCompletionSource<MatchingBattleInfo> Finalized { get; } =
            new(TaskCreationOptions.RunContinuationsAsynchronously);

        /// <summary>One entry per waiting stream, so a join can refresh the other clients' slots.</summary>
        public List<AssignmentSubscriber> Subscribers { get; } = [];
    }

    private const string MatchmakingNeverExpires = "2030-01-01 00:00:00";

    /// <summary>
    /// 4v4: eight slots, so four humans per team is also the join cap. Shared by the join check and the bot fill;
    /// `tests/test_teamtype.py` guards it against drifting from the team rules.
    /// </summary>
    public const int MaxPerTeam = 4;

    public sealed class MatchingBattleInfo
    {
        public string matchmakingExpirationDatetime { get; set; } = "2030-01-01 00:00:00";
        public int photonCloudRegionId { get; set; } = 1;
        public List<MatchingPlayerBattleInfo> battlePlayerList { get; set; } = [];
    }

    public sealed class MatchingPlayerBattleInfo
    {
        public string userId { get; set; } = "";
        public string matchmakingTeamId { get; set; } = "";
        public string battleEntryId { get; set; } = "";
        public string name { get; set; } = "";
        public int rank { get; set; } = 13;
        public int kickerId { get; set; } = 1;
        public int kickerCostumeId { get; set; } = 1;
        public int honorId { get; set; } = 6010000;
        public int teamType { get; set; } = 0; // 0 = Blue, 1 = Red (Colorful.TeamType)
        public int kickerAiParameterId { get; set; } = 0; // 0 for human, > 0 for bot
        public int kickerAiDiscDeckId { get; set; } = 0; // 0 for human, > 0 for bot
        public string languageCode { get; set; } = "es";
        public int frameId { get; set; } = 1;
        public int discId1 { get; set; } = 3010001;
        public int discLevel1 { get; set; } = 10;
        public int discId2 { get; set; } = 3010002;
        public int discLevel2 { get; set; } = 10;
        public int discId3 { get; set; } = 3010003;
        public int discLevel3 { get; set; } = 10;
        public int discId4 { get; set; } = 3010004;
        public int discLevel4 { get; set; } = 10;
        public int gearId1 { get; set; } = 0;
        public int gearId2 { get; set; } = 0;
        public int gearId3 { get; set; } = 0;
    }

    public (string battleEntryId, string ticketId) RegisterEntry(
        string userId, string userName, int kickerId, int costumeId, int battleRuleId, List<int> deck)
    {
        var entryId = $"be-{Guid.NewGuid():N}"[..12];
        var ticketId = $"ticket-{Guid.NewGuid():N}"[..16];

        var session = new BattleEntrySession
        {
            TicketId = ticketId,
            BattleEntryId = entryId,
            UserId = userId,
            UserName = userName,
            KickerId = kickerId,
            KickerCostumeId = costumeId,
            BattleRuleId = battleRuleId,
            DeckDiscs = deck
        };

        _entriesByTicket[ticketId] = session;
        _logger.LogInformation("Registered battle entry: user={UserId} ({UserName}), ticket={TicketId}, kicker={KickerId}, rule={RuleId}",
            userId, userName, ticketId, kickerId, battleRuleId);

        return (entryId, ticketId);
    }

    // Arenas that ship complete in the capture: field/fld{id:05}, fielddata/fld{id:05}_{1,2,3} (crystal / flag / ball
    // variants), itemdata/ite{id:05}_{1,2,3} and minimap/mim{id:05}_0. 102/302/402/602/702/902 have a model but no
    // fielddata, 11/0 are tutorial, 801 is the Trial arena, 9000x are the home stages. Every room draws one at random;
    // /battle/start answers it (the client only reads the field from that response). Set KF_FIELDS=101 to pin one.
    public static readonly int[] FieldPool = ParseFieldPool(Environment.GetEnvironmentVariable("KF_FIELDS"));
    private static readonly Random _fieldRandom = new();

    private static int[] ParseFieldPool(string? value)
    {
        var ids = (value ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(v => int.TryParse(v, out var id) ? id : 0).Where(id => id > 0).ToArray();
        return ids.Length > 0 ? ids : [101, 301, 401, 601, 701, 901];
    }

    public static int PickRandomField()
    {
        lock (_fieldRandom) return FieldPool[_fieldRandom.Next(FieldPool.Length)];
    }

    /// <summary>Field of an existing room (both humans of a room must load the same arena), else null.</summary>
    public int? GetRoomFieldId(string battleId)
    {
        return _roomsByBattleId.TryGetValue(battleId, out var room) ? room.FieldId : null;
    }

    private readonly object _matchLock = new();
    private ActiveBattleRoom? _pendingRoom;

    // How long a room stays open for more humans. The first entry opens this window and every human that joins
    // extends it (JoinIncrementSeconds); bots only take the empty slots when it runs out, so humans ending up in
    // the same match is the priority and bots are the fallback. KF_MATCH_WINDOW_SECONDS=0 restores the old
    // behaviour of starting the moment a second human appears.
    public TimeSpan MatchWindow { get; set; } =
        TimeSpan.FromSeconds(ParseMatchConfiguration("KF_MATCH_WINDOW_SECONDS", 20.0));

    /// <summary>
    /// Seconds the second human adds to the window. Each later join adds a tenth of this less
    /// (<see cref="JoinIncrementSeconds"/>): 5, 4.5, 4, … Tune with KF_MATCH_JOIN_INCREMENT_SECONDS.
    /// </summary>
    public double JoinIncrementBaseSeconds { get; set; } =
        ParseMatchConfiguration("KF_MATCH_JOIN_INCREMENT_SECONDS", 5.0);

    private static double ParseMatchConfiguration(string variable, double fallback)
    {
        // Invariant culture: with a comma-decimal culture "5.0" parses as 50.
        return double.TryParse(Environment.GetEnvironmentVariable(variable), NumberStyles.Float,
            CultureInfo.InvariantCulture, out var seconds) && seconds >= 0
            ? seconds
            : fallback;
    }

    /// <summary>
    /// How much a join extends the window, counting the joiner: 5 s for the second human, then half a second
    /// less each time (4.5, 4, … 2 s for the eighth), so eight humans stay 20 + 5 + 4.5 + … + 2 = 44.5 s.
    /// </summary>
    public double JoinIncrementSeconds(int humansInRoom)
    {
        if (humansInRoom < 2) return 0;
        var step = JoinIncrementBaseSeconds / 10.0;
        return Math.Max(0, JoinIncrementBaseSeconds - step * (humansInRoom - 2));
    }

    /// <summary>A room takes more humans while its window is open and it still has a free slot.</summary>
    private static bool IsJoinable(ActiveBattleRoom? room, BattleEntrySession player)
    {
        return room is not null
            && !room.IsFinalized
            && room.BattleRuleId == player.BattleRuleId
            && room.HumanPlayers.Count < MaxPerTeam * 2;
    }

    /// <summary>
    /// Closes the room's window: builds the final roster (humans, plus bots for the empty slots) and wakes every
    /// waiting stream. Idempotent — both the window task and a room that filled up with humans call it.
    /// </summary>
    private void FinalizeRoom(ActiveBattleRoom room)
    {
        MatchingBattleInfo roster;
        lock (_matchLock)
        {
            // Nothing to finalize once every human has left, and a room that reached 8 humans was already
            // finalized by the join that filled it.
            if (room.IsFinalized || room.HumanPlayers.Count == 0) return;

            room.IsFinalized = true;
            roster = BuildRoster(room);
            room.MatchingInfo = roster;
            if (ReferenceEquals(_pendingRoom, room)) _pendingRoom = null;
        }

        _logger.LogInformation(
            "Matchmaking window of room {BattleId} closed with {Humans} human(s); filling empty slots with bots",
            room.BattleId, room.HumanPlayers.Count);

        room.Finalized.TrySetResult(roster);
    }

    /// <summary>
    /// Waits out the room's window. Task.Delay cannot be extended, so the deadline is re-read on every iteration:
    /// that is what lets a join push the end of the window further away.
    /// </summary>
    private async Task RunMatchWindowAsync(ActiveBattleRoom room)
    {
        try
        {
            while (true)
            {
                TimeSpan remaining;
                lock (_matchLock)
                {
                    if (room.IsFinalized || room.HumanPlayers.Count == 0) return;
                    remaining = room.WindowDeadline - DateTime.UtcNow;
                }

                if (remaining <= TimeSpan.Zero) break;
                await Task.Delay(remaining + TimeSpan.FromMilliseconds(50));
            }
        }
        catch (Exception ex)
        {
            // Fire and forget: a fault here would leave a room that can never start.
            _logger.LogError(ex, "Matchmaking window of room {BattleId} failed", room.BattleId);
        }

        FinalizeRoom(room);
    }

    // ResolveAssignment/ResolveAssignmentAsync used to live here: the pre-stream matching path, unreachable since
    // GetAssignments took over (nothing in src/ or tests/ called it) and unable to compile without _pendingRoomTcs,
    // which the per-room window now owns.

    /// <summary>Fallback session for a ticket this process does not know (demo tickets).</summary>
    private static BattleEntrySession DemoEntrySession(string ticketId) => new()
    {
        TicketId = ticketId,
        BattleEntryId = "be-demo-001",
        UserId = "1000001",
        UserName = "Gixarde3",
        KickerId = 1,
        KickerCostumeId = 2010101,
        BattleRuleId = 1,
        DeckDiscs = [3010001, 3010002, 3010003, 3010004]
    };

    public async Task StreamAssignmentsAsync(
        string ticketId,
        IServerStreamWriter<GetAssignmentsResponse> responseStream,
        CancellationToken cancellationToken)
    {
        var playerSession = _entriesByTicket.TryGetValue(ticketId, out var registered)
            ? registered
            : DemoEntrySession(ticketId);

        // A reconnect/retry for a ticket whose room already started must replay the same final
        // assignment. Creating a second room here leaves the client and Photon
        // with different room identities and makes recovery impossible.
        // Only a finalized room counts: while the window is open the roster is deliberately partial, so replaying
        // on a non-empty roster would hand out a Connection before the match exists.
        ActiveBattleRoom? completedRoom;
        lock (_matchLock)
        {
            completedRoom = _roomsByBattleId.Values.FirstOrDefault(room =>
                room.IsFinalized &&
                room.HumanPlayers.Any(player => player.TicketId == ticketId));
        }
        if (completedRoom is not null)
        {
            _logger.LogInformation(
                "Replaying completed Stage 3 assignment {BattleId} for ticket {TicketId}",
                completedRoom.BattleId,
                ticketId);
            await SendAssignmentUpdateAsync(responseStream, completedRoom.BattleId, completedRoom.MatchingInfo);
            await HoldFinalAssignmentAsync(playerSession.UserId, cancellationToken);
            return;
        }

        var subscriber = new AssignmentSubscriber(responseStream);
        ActiveBattleRoom room;
        bool joinedExistingRoom;
        bool roomIsFull;
        MatchingBattleInfo interimRoster;

        lock (_matchLock)
        {
            var openRoom = IsJoinable(_pendingRoom, playerSession) ? _pendingRoom : null;

            if (openRoom is not null)
            {
                // The third, fourth, … human lands in the first player's room: a join never tears the pending room
                // down, it only makes its window longer.
                room = openRoom;
                joinedExistingRoom = true;
                var humansBefore = room.HumanPlayers.Count;

                // A retried stream, or the same user entering again with a fresh ticket, replaces its own stale
                // session instead of taking a second slot.
                room.HumanPlayers.RemoveAll(player =>
                    player.UserId == playerSession.UserId || player.TicketId == ticketId);
                room.HumanPlayers.Add(playerSession);
                CanonicalizeHumanOrder(room);

                if (room.HumanPlayers.Count > humansBefore)
                {
                    var increment = JoinIncrementSeconds(room.HumanPlayers.Count);
                    room.WindowDeadline += TimeSpan.FromSeconds(increment);
                    _logger.LogInformation(
                        "Human {UserId} joined room {BattleId} ({Humans} human(s) waiting); window extended by {Increment:0.#}s",
                        playerSession.UserId, room.BattleId, room.HumanPlayers.Count, increment);
                }
                else
                {
                    _logger.LogInformation("Ticket {TicketId} re-attached to open room {BattleId}",
                        ticketId, room.BattleId);
                }
            }
            else
            {
                room = new ActiveBattleRoom
                {
                    BattleId = $"battle-{Interlocked.Increment(ref _battleCounter)}",
                    BattleRuleId = playerSession.BattleRuleId,
                    FieldId = PickRandomField(),
                    HumanPlayers = [playerSession],
                    WindowDeadline = DateTime.UtcNow + MatchWindow
                };
                _roomsByBattleId[room.BattleId] = room;
                _pendingRoom = room;
                joinedExistingRoom = false;
                _logger.LogInformation(
                    "Created battle room {BattleId} for user {UserId}; window open for {Seconds:0.#}s",
                    room.BattleId, playerSession.UserId, MatchWindow.TotalSeconds);
            }

            room.Subscribers.Add(subscriber);
            interimRoster = BuildHumanRoster(room);
            roomIsFull = room.HumanPlayers.Count >= MaxPerTeam * 2;
        }

        if (!joinedExistingRoom)
        {
            // Only the stream that opened the room starts its clock; joins extend it from here on.
            _ = RunMatchWindowAsync(room);
        }

        try
        {
            // --- STAGE 1: the humans waiting in this room, so a late joiner sees everyone at once and the clients
            // already waiting watch each other arrive. No bots yet: they only take the empty slots once the window
            // closes.
            await subscriber.SendStageAsync("", interimRoster);
            _logger.LogInformation(
                "Streamed Stage 1 (room preparation / searching; {Humans} human(s)) for user {UserId}",
                interimRoster.battlePlayerList.Count, playerSession.UserId);

            if (joinedExistingRoom)
            {
                await BroadcastInterimRosterAsync(room, subscriber, interimRoster);
            }

            if (roomIsFull)
            {
                // No slot left for anyone else: no reason to keep the window open.
                FinalizeRoom(room);
            }

            // --- STAGE 2: every waiting stream has been parked here for the whole window, which closes when the
            // deadline runs out or the room filled up with humans; the empty slots are bots by now.
            var fullRoster = await room.Finalized.Task.WaitAsync(cancellationToken);
            await subscriber.SendStageAsync("", fullRoster);
            _logger.LogInformation("Streamed Stage 2 (full roster / Iniciar combate) for user {UserId}", playerSession.UserId);

            // Keep this close to the successful client trace: the runner primes the
            // start control before Stage 1, and Stage 3 must arrive while that local
            // ready state is still active. A longer (12 s) hold was consumed and
            // acknowledged by both clients but neither opened Photon afterwards.
            await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken);

            // --- STAGE 3: Final assignment with non-empty Connection -> triggers Success (Result 1) and enters battle! ---
            await subscriber.SendFinalStageAsync(room.BattleId, fullRoster);
            _logger.LogInformation("Streamed Stage 3 (battle start assignment: {BattleId}) for user {UserId}", room.BattleId, playerSession.UserId);

            // Keep the server-streaming call alive until the client consumes Stage 3 and
            // cancels GetAssignments while changing state.  Completing the RPC here can
            // enqueue the terminal callback beside the Stage 3 callback on Unity's
            // SynchronizationContext; on slower emulators that race leaves the client in
            // MatchingScene even though the final assignment was delivered successfully.
            // The upper bound only protects abandoned clients; healthy clients cancel
            // this delay as soon as they enter JoinBattleRoom.
            await HoldFinalAssignmentAsync(playerSession.UserId, cancellationToken);
        }
        finally
        {
            // Leaving the matching screen destroys the GetAssignments stream, and /battle/cancel never reaches this
            // service: a stream that ends before its room starts is the only sign that a waiting human withdrew.
            // Drop them, and drop the room with the last one.
            lock (_matchLock)
            {
                room.Subscribers.Remove(subscriber);

                if (!room.IsFinalized)
                {
                    room.HumanPlayers.RemoveAll(player => player.TicketId == ticketId);
                    if (room.HumanPlayers.Count == 0)
                    {
                        _roomsByBattleId.TryRemove(room.BattleId, out _);
                        if (ReferenceEquals(_pendingRoom, room)) _pendingRoom = null;
                        _logger.LogInformation("Room {BattleId} dropped: every waiting human left", room.BattleId);
                    }
                }
            }
        }
    }

    private async Task HoldFinalAssignmentAsync(string userId, CancellationToken cancellationToken)
    {
        _logger.LogInformation("Holding GetAssignments open for Stage 3 acknowledgement from user {UserId}", userId);
        await Task.Delay(TimeSpan.FromSeconds(30), cancellationToken);
    }

    /// <summary>
    /// Refreshes the other waiting clients' slots with the room's humans (the joiner already got the same roster as
    /// its Stage 1). A client that is gone only fails its own stream, which cleans itself up.
    /// </summary>
    private async Task BroadcastInterimRosterAsync(
        ActiveBattleRoom room,
        AssignmentSubscriber sender,
        MatchingBattleInfo roster)
    {
        AssignmentSubscriber[] subscribers;
        lock (_matchLock) subscribers = [.. room.Subscribers];

        foreach (var subscriber in subscribers)
        {
            if (ReferenceEquals(subscriber, sender)) continue;

            try
            {
                await subscriber.BroadcastAsync(roster);
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Interim roster update to a waiting stream of room {BattleId} failed", room.BattleId);
            }
        }
    }

    private static void CanonicalizeHumanOrder(ActiveBattleRoom room)
    {
        // The original client derives team/room ownership from roster position.
        // Arrival order varies with emulator load, so never let it alter the
        // authoritative player ordering sent to either client.
        room.HumanPlayers.Sort((left, right) =>
        {
            var userComparison = string.CompareOrdinal(left.UserId, right.UserId);
            return userComparison != 0
                ? userComparison
                : string.CompareOrdinal(left.BattleEntryId, right.BattleEntryId);
        });
    }

    private static async Task SendAssignmentUpdateAsync(
        IServerStreamWriter<GetAssignmentsResponse> responseStream,
        string connection,
        MatchingBattleInfo roster)
    {
        var json = JsonSerializer.Serialize(roster);
        var battleStruct = Struct.Parser.ParseJson(json);
        var propertiesStruct = new Struct();
        propertiesStruct.Fields["battle"] = Value.ForStruct(battleStruct);
        propertiesStruct.Fields["RoomBattleInfo"] = Value.ForStruct(battleStruct);
        propertiesStruct.Fields["matchStatus"] = Value.ForStruct(battleStruct);

        var response = new GetAssignmentsResponse
        {
            Assignment = new Assignment
            {
                Connection = connection,
                Properties = propertiesStruct
            }
        };

        await responseStream.WriteAsync(response);
    }

    /// <summary>
    /// One waiting client. Its stream may be written by two things at once — its own stage sequence and the
    /// interim roster broadcast that a join triggers — and they must not interleave: gRPC allows a single
    /// in-flight write per stream, and a broadcast landing after the final assignment would drag the client back
    /// to the matching screen.
    /// </summary>
    public sealed class AssignmentSubscriber
    {
        private readonly IServerStreamWriter<GetAssignmentsResponse> _responseStream;
        private readonly SemaphoreSlim _gate = new(1, 1);
        private bool _stagingComplete;

        public AssignmentSubscriber(IServerStreamWriter<GetAssignmentsResponse> responseStream)
        {
            _responseStream = responseStream;
        }

        /// <summary>Shows the waiting client the room's current humans; a no-op once its final assignment went out.</summary>
        public async Task BroadcastAsync(MatchingBattleInfo roster)
        {
            await _gate.WaitAsync();
            try
            {
                if (_stagingComplete) return;
                await SendAssignmentUpdateAsync(_responseStream, "", roster);
            }
            finally
            {
                _gate.Release();
            }
        }

        public Task SendStageAsync(string connection, MatchingBattleInfo roster) =>
            SendAsync(connection, roster, stagingComplete: false);

        /// <summary>Stage 3: with the Connection set the client leaves the matching screen, so stop broadcasting.</summary>
        public Task SendFinalStageAsync(string connection, MatchingBattleInfo roster) =>
            SendAsync(connection, roster, stagingComplete: true);

        private async Task SendAsync(string connection, MatchingBattleInfo roster, bool stagingComplete)
        {
            await _gate.WaitAsync();
            try
            {
                if (stagingComplete) _stagingComplete = true;
                await SendAssignmentUpdateAsync(_responseStream, connection, roster);
            }
            finally
            {
                _gate.Release();
            }
        }
    }

    public sealed record BotProfile(int KickerId, string Name);

    // Gym mode (toggled at runtime with GET /gym/on | /gym/off | /gym): the next match is the human(s) on Blue against
    // exactly GymBotCount mannequin bots on Red, and /battle/start hands out the harmless guardian row. Mannequin =
    // kickerAiParameterId 100 + kickerId: the client patch (scripts/re/bot_special_skill_cave.py) sets
    // PlayerCharacter.AIOption = Mannequin (63) for any id >= 100, and DemoSessionApi serves those ids as copies of
    // the real AI rows with zero motivation so an unpatched client gets a mostly idle bot too.
    public static volatile bool GymEnabled;
    public const int GymAiParameterBase = 100;
    public const int GymBotCount = 3;

    // Names from config/masters_kicker.json. Bots are taken in this order (skipping the human's kicker), so the
    // kickers whose weapons/skills were reworked on 2026-09-19 (Owlbert drone + smog, Buzzy Big shields + front
    // barrier, Yuyan nunchaku + panda, Sid wrist lasers) come first and show up in every solo match for testing.
    private static readonly BotProfile[] BotProfiles =
    [
        new(5, "Owlbert Bot"),
        new(12, "Buzzy Big Bot"),
        new(10, "Yuyan Bot"),
        new(14, "Sid Bot"),
        new(1, "Tsubame Bot"),
        new(2, "Ruriha Bot"),
        new(3, "Coco Bot"),
        new(4, "Kite Bot"),
        new(6, "Pitophy Bot"),
        new(7, "Grenhawk Bot"),
        new(8, "Anna Bot"),
        new(9, "Jay Bot"),
        new(11, "Diatrius Bot"),
        new(13, "Hitagi Bot")
    ];

    /// <summary>
    /// What a waiting client sees while the room's window is still open: the humans already in it and no bots.
    /// </summary>
    private static MatchingBattleInfo BuildHumanRoster(ActiveBattleRoom room)
    {
        return new MatchingBattleInfo
        {
            // Bare wall-clock string: the client reads it in its own time base, so a UTC "now + 30 min" is already
            // hours in the past on a phone in UTC+8 and the very first roster update fails with "Timeout" (2026-09-14);
            // the emulator only worked because its clock runs on UTC. Use the far-future default instead.
            matchmakingExpirationDatetime = MatchmakingNeverExpires,
            photonCloudRegionId = 1,
            battlePlayerList = BuildHumanEntries(room)
        };
    }

    /// <summary>One entry per human waiting in the room; the order is what the client reads as Blue/Red slots.</summary>
    private static List<MatchingPlayerBattleInfo> BuildHumanEntries(ActiveBattleRoom room)
    {
        var entries = new List<MatchingPlayerBattleInfo>();

        for (int i = 0; i < room.HumanPlayers.Count; i++)
        {
            var p = room.HumanPlayers[i];
            int team = (i % 2 == 0) ? 0 : 1;

            var playerName = p.UserName;
            if (i > 0 && playerName == room.HumanPlayers[0].UserName)
            {
                playerName = $"{p.UserName} (P{i + 1})";
            }

            var discs = p.DeckDiscs.Count >= 4 ? p.DeckDiscs : [3010001, 3010002, 3010003, 3010004];
            entries.Add(new MatchingPlayerBattleInfo
            {
                userId = p.UserId,
                matchmakingTeamId = $"team-{(team == 0 ? 1 : 2)}",
                battleEntryId = p.BattleEntryId,
                name = playerName,
                rank = 13,
                kickerId = p.KickerId,
                kickerCostumeId = p.KickerCostumeId,
                honorId = 6010000,
                teamType = team,
                kickerAiParameterId = 0, // Human
                kickerAiDiscDeckId = 0,  // Human
                languageCode = "es",
                frameId = 1,
                discId1 = discs[0], discLevel1 = 10,
                discId2 = discs[1], discLevel2 = 10,
                discId3 = discs[2], discLevel3 = 10,
                discId4 = discs[3], discLevel4 = 10
            });
        }

        return entries;
    }

    /// <summary>Final roster, built only when the room's window closes: the humans plus the bots for the free slots.</summary>
    private static MatchingBattleInfo BuildRoster(ActiveBattleRoom room)
    {
        // Humans alternate Blue/Red in canonical order, so the two teams are never more than one human apart and
        // the bots below only have to top each side up to MaxPerTeam. That is the whole team balance, and it holds
        // for any number of humans from 1 to 8 (5 humans -> 3 Blue + 2 Red, bots taking one Blue and two Red).
        var humanEntries = BuildHumanEntries(room);
        var info = new MatchingBattleInfo
        {
            matchmakingExpirationDatetime = MatchmakingNeverExpires,
            photonCloudRegionId = 1,
            battlePlayerList = [.. humanEntries]
        };

        var usedKickers = new HashSet<int>(room.HumanPlayers.Select(player => player.KickerId));
        int team0Count = humanEntries.Count(entry => entry.teamType == 0);
        int team1Count = humanEntries.Count - team0Count;

        // 2. Fill remaining slots with AI Bots up to 4 on Team 0 (Blue) and 4 on Team 1 (Red) (8 total for 4v4)
        var availableBots = BotProfiles.Where(b => !usedKickers.Contains(b.KickerId)).ToList();
        var botIdx = 0;

        var gym = GymEnabled;
        var totalPlayers = gym ? room.HumanPlayers.Count + GymBotCount : MaxPerTeam * 2;

        while (info.battlePlayerList.Count < totalPlayers)
        {
            int team = gym ? 1 : (team0Count < MaxPerTeam) ? 0 : 1;
            if (team == 0) team0Count++; else team1Count++;

            var profile = (botIdx < availableBots.Count) ? availableBots[botIdx++] : new BotProfile(botIdx + 1, $"Bot {botIdx + 1}");
            var botDiscs = new[] { 3010001, 3010002, 3010003, 3010004 };

            info.battlePlayerList.Add(new MatchingPlayerBattleInfo
            {
                userId = $"bot-{1000 + info.battlePlayerList.Count}",
                matchmakingTeamId = $"team-{(team == 0 ? 1 : 2)}",
                battleEntryId = $"be-bot-{info.battlePlayerList.Count}",
                name = gym ? $"{profile.Name} (gym)" : profile.Name,
                // Must be >= the `rank` of the kicker's rows in masters_kicker_ai_parameter.json (all 13):
                // PlayerCharacter.GetKickerAIParameterMaster picks the closest row with row.rank <= player rank,
                // so a lower rank leaves the bot without AI parameters and it never acts.
                rank = 13,
                kickerId = profile.KickerId,
                kickerCostumeId = 1,
                honorId = 6010000,
                teamType = team,
                // KickerAiParameterMaster row *id* (PlayerCharacter.GetKickerAIParameterMaster = get_Item(_kickerAiParameterId))
                kickerAiParameterId = gym ? GymAiParameterBase + profile.KickerId : profile.KickerId,
                kickerAiDiscDeckId = 1,                 // Valid AI deck
                languageCode = "es",
                frameId = 1,
                discId1 = botDiscs[0], discLevel1 = 10,
                discId2 = botDiscs[1], discLevel2 = 10,
                discId3 = botDiscs[2], discLevel3 = 10,
                discId4 = botDiscs[3], discLevel4 = 10
            });
        }

        return info;
    }
}

public sealed class OpenMatchFrontendService : Frontend.FrontendBase
{
    private readonly BattleMatchmakingService _matchmaking;
    private readonly ILogger<OpenMatchFrontendService> _logger;

    public OpenMatchFrontendService(BattleMatchmakingService matchmaking, ILogger<OpenMatchFrontendService> logger)
    {
        _matchmaking = matchmaking;
        _logger = logger;
    }

    public override async Task GetAssignments(
        GetAssignmentsRequest request,
        IServerStreamWriter<GetAssignmentsResponse> responseStream,
        ServerCallContext context)
    {
        _logger.LogInformation("gRPC GetAssignments invoked for ticket {TicketId}", request.TicketId);

        try
        {
            await _matchmaking.StreamAssignmentsAsync(request.TicketId, responseStream, context.CancellationToken);
        }
        catch (OperationCanceledException)
        {
            _logger.LogInformation("GetAssignments stream cancelled for ticket {TicketId}", request.TicketId);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error in GetAssignments for ticket {TicketId}", request.TicketId);
        }
    }
}

