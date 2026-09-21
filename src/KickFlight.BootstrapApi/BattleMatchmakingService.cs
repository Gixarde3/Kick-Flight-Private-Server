using System.Collections.Concurrent;
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
        public int KickerCostumeId { get; set; } = 1;
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
    }

    private const string MatchmakingNeverExpires = "2030-01-01 00:00:00";

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
    private TaskCompletionSource<MatchingBattleInfo>? _pendingRoomTcs;

    public (string connection, string battleJson)? ResolveAssignment(string ticketId)
    {
        return ResolveAssignmentAsync(ticketId).GetAwaiter().GetResult();
    }

    public async Task<(string connection, string battleJson)?> ResolveAssignmentAsync(string ticketId, CancellationToken cancellationToken = default)
    {
        if (!_entriesByTicket.TryGetValue(ticketId, out var playerSession))
        {
            // Fallback for demo ticket if not directly found
            playerSession = new BattleEntrySession
            {
                TicketId = ticketId,
                BattleEntryId = "be-demo-001",
                UserId = "1000001",
                UserName = "Gixarde3",
                KickerId = 1,
                KickerCostumeId = 1,
                BattleRuleId = 1,
                DeckDiscs = [3010001, 3010002, 3010003, 3010004]
            };
        }

        ActiveBattleRoom? targetRoom = null;
        Task<MatchingBattleInfo>? waitTask = null;

        lock (_matchLock)
        {
            // Check if user is already in an active room with completed roster
            foreach (var room in _roomsByBattleId.Values)
            {
                if (room.HumanPlayers.Any(p => p.UserId == playerSession.UserId) && room.MatchingInfo.battlePlayerList.Count > 0)
                {
                    var cachedJson = JsonSerializer.Serialize(room.MatchingInfo);
                    return (room.BattleId, cachedJson);
                }
            }

            // Multi-client matching check: check if there is an active pending room waiting for player 2
            if (_pendingRoom != null &&
                _pendingRoom.BattleRuleId == playerSession.BattleRuleId &&
                _pendingRoom.HumanPlayers.Count == 1 &&
                !_pendingRoom.HumanPlayers.Any(p => p.UserId == playerSession.UserId))
            {
                targetRoom = _pendingRoom;
                targetRoom.HumanPlayers.Add(playerSession);
                CanonicalizeHumanOrder(targetRoom);
                _logger.LogInformation("Matched second human player {UserId} into room {BattleId}", playerSession.UserId, targetRoom.BattleId);

                var roster = BuildRoster(targetRoom);
                targetRoom.MatchingInfo = roster;

                var tcs = _pendingRoomTcs;
                _pendingRoom = null;
                _pendingRoomTcs = null;
                tcs?.TrySetResult(roster);

                var json = JsonSerializer.Serialize(roster);
                return (targetRoom.BattleId, json);
            }

            // Otherwise create a new room and wait for a second player
            var nextId = Interlocked.Increment(ref _battleCounter);
            var battleId = $"battle-{nextId}";
            targetRoom = new ActiveBattleRoom
            {
                BattleId = battleId,
                BattleRuleId = playerSession.BattleRuleId,
                FieldId = PickRandomField(),
                HumanPlayers = [playerSession]
            };
            _roomsByBattleId[battleId] = targetRoom;
            _pendingRoom = targetRoom;
            _pendingRoomTcs = new TaskCompletionSource<MatchingBattleInfo>(TaskCreationOptions.RunContinuationsAsynchronously);
            waitTask = _pendingRoomTcs.Task;
            _logger.LogInformation("Created pending battle room {BattleId} for user {UserId}, waiting up to 4s for second player", battleId, playerSession.UserId);
        }

        // Wait up to 25 seconds for opponent to join
        try
        {
            var completedTask = await Task.WhenAny(waitTask, Task.Delay(25000, cancellationToken));
            if (completedTask == waitTask)
            {
                var roster = await waitTask;
                _logger.LogInformation("Returning matched 2-player roster for user {UserId} in room {BattleId}", playerSession.UserId, targetRoom.BattleId);
                return (targetRoom.BattleId, JsonSerializer.Serialize(roster));
            }
        }
        catch (OperationCanceledException)
        {
            // Client disconnected or cancelled
        }

        // Timeout expired: fill with AI bots and start solo
        lock (_matchLock)
        {
            if (_pendingRoom == targetRoom)
            {
                _pendingRoom = null;
                _pendingRoomTcs = null;
                var soloRoster = BuildRoster(targetRoom);
                targetRoom.MatchingInfo = soloRoster;
                _logger.LogInformation("Room {BattleId} matchmaking timed out, starting solo match with AI bots for user {UserId}", targetRoom.BattleId, playerSession.UserId);
                return (targetRoom.BattleId, JsonSerializer.Serialize(soloRoster));
            }
            else
            {
                // Second player joined right before timeout
                return (targetRoom.BattleId, JsonSerializer.Serialize(targetRoom.MatchingInfo));
            }
        }
    }

    private static MatchingBattleInfo BuildInitialRoster(BattleEntrySession player)
    {
        var discs = player.DeckDiscs.Count >= 4 ? player.DeckDiscs : [3010001, 3010002, 3010003, 3010004];
        return new MatchingBattleInfo
        {
            // Bare wall-clock string: the client reads it in its own time base, so a UTC "now + 30 min" is already
            // hours in the past on a phone in UTC+8 and the very first roster update fails with "Timeout" (2026-09-14);
            // the emulator only worked because its clock runs on UTC. Use the far-future default instead.
            matchmakingExpirationDatetime = MatchmakingNeverExpires,
            photonCloudRegionId = 1,
            battlePlayerList =
            [
                new MatchingPlayerBattleInfo
                {
                    userId = player.UserId,
                    matchmakingTeamId = "team-1",
                    battleEntryId = player.BattleEntryId,
                    name = player.UserName,
                    rank = 13,
                    kickerId = player.KickerId,
                    kickerCostumeId = player.KickerCostumeId,
                    honorId = 6010000,
                    teamType = 0,
                    kickerAiParameterId = 0,
                    kickerAiDiscDeckId = 0,
                    languageCode = "es",
                    frameId = 1,
                    discId1 = discs[0], discLevel1 = 10,
                    discId2 = discs[1], discLevel2 = 10,
                    discId3 = discs[2], discLevel3 = 10,
                    discId4 = discs[3], discLevel4 = 10
                }
            ]
        };
    }

    public async Task StreamAssignmentsAsync(
        string ticketId,
        IServerStreamWriter<GetAssignmentsResponse> responseStream,
        CancellationToken cancellationToken)
    {
        if (!_entriesByTicket.TryGetValue(ticketId, out var playerSession))
        {
            playerSession = new BattleEntrySession
            {
                TicketId = ticketId,
                BattleEntryId = "be-demo-001",
                UserId = "1000001",
                UserName = "Gixarde3",
                KickerId = 1,
                KickerCostumeId = 1,
                BattleRuleId = 1,
                DeckDiscs = [3010001, 3010002, 3010003, 3010004]
            };
        }

        // A reconnect/retry for a completed ticket must replay the same final
        // assignment. Creating a second room here leaves the client and Photon
        // with different room identities and makes recovery impossible.
        ActiveBattleRoom? completedRoom;
        lock (_matchLock)
        {
            completedRoom = _roomsByBattleId.Values.FirstOrDefault(room =>
                room.MatchingInfo.battlePlayerList.Count > 0 &&
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

        ActiveBattleRoom targetRoom;
        Task<MatchingBattleInfo>? waitTask = null;
        bool isSecondPlayer = false;

        lock (_matchLock)
        {
            // Check if there is an active pending room waiting for player 2
            if (_pendingRoom != null &&
                _pendingRoom.BattleRuleId == playerSession.BattleRuleId &&
                _pendingRoom.HumanPlayers.Count == 1 &&
                !_pendingRoom.HumanPlayers.Any(p => p.UserId == playerSession.UserId))
            {
                targetRoom = _pendingRoom;
                targetRoom.HumanPlayers.Add(playerSession);
                CanonicalizeHumanOrder(targetRoom);
                isSecondPlayer = true;
                _logger.LogInformation("Matched second human player {UserId} into room {BattleId}", playerSession.UserId, targetRoom.BattleId);

                var roster = BuildRoster(targetRoom);
                targetRoom.MatchingInfo = roster;

                var tcs = _pendingRoomTcs;
                _pendingRoom = null;
                _pendingRoomTcs = null;
                tcs?.TrySetResult(roster);
            }
            else
            {
                var nextId = Interlocked.Increment(ref _battleCounter);
                var battleId = $"battle-{nextId}";
                targetRoom = new ActiveBattleRoom
                {
                    BattleId = battleId,
                    BattleRuleId = playerSession.BattleRuleId,
                    FieldId = PickRandomField(),
                    HumanPlayers = [playerSession]
                };
                _roomsByBattleId[battleId] = targetRoom;
                _pendingRoom = targetRoom;
                _pendingRoomTcs = new TaskCompletionSource<MatchingBattleInfo>(TaskCreationOptions.RunContinuationsAsynchronously);
                waitTask = _pendingRoomTcs.Task;
                _logger.LogInformation("Created pending battle room {BattleId} for user {UserId}", battleId, playerSession.UserId);
            }
        }

        // --- STAGE 1: Stream initial update so MatchingWaitMemberDisplay renders with 'Buscando...' slots ---
        var initialRoster = BuildInitialRoster(playerSession);
        await SendAssignmentUpdateAsync(responseStream, "", initialRoster);
        _logger.LogInformation("Streamed Stage 1 (room preparation / searching) for user {UserId}", playerSession.UserId);

        // --- STAGE 2: Wait for second player or countdown, then stream full roster ---
        MatchingBattleInfo fullRoster;
        if (isSecondPlayer)
        {
            fullRoster = targetRoom.MatchingInfo;
        }
        else
        {
            try
            {
                var completed = await Task.WhenAny(waitTask!, Task.Delay(25000, cancellationToken));
                if (completed == waitTask)
                {
                    fullRoster = await waitTask!;
                }
                else
                {
                    lock (_matchLock)
                    {
                        if (_pendingRoom == targetRoom)
                        {
                            _pendingRoom = null;
                            _pendingRoomTcs = null;
                        }
                    }
                    fullRoster = BuildRoster(targetRoom);
                    targetRoom.MatchingInfo = fullRoster;
                }
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }

        // Stream Stage 2: All 8 slots populated -> UI switches to 'Iniciar combate'!
        await SendAssignmentUpdateAsync(responseStream, "", fullRoster);
        _logger.LogInformation("Streamed Stage 2 (full roster / Iniciar combate) for user {UserId}", playerSession.UserId);

        // Keep this close to the successful client trace: the runner primes the
        // start control before Stage 1, and Stage 3 must arrive while that local
        // ready state is still active. A longer (12 s) hold was consumed and
        // acknowledged by both clients but neither opened Photon afterwards.
        await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken);

        // --- STAGE 3: Final assignment with non-empty Connection -> triggers Success (Result 1) and enters battle! ---
        await SendAssignmentUpdateAsync(responseStream, targetRoom.BattleId, fullRoster);
        _logger.LogInformation("Streamed Stage 3 (battle start assignment: {BattleId}) for user {UserId}", targetRoom.BattleId, playerSession.UserId);

        // Keep the server-streaming call alive until the client consumes Stage 3 and
        // cancels GetAssignments while changing state.  Completing the RPC here can
        // enqueue the terminal callback beside the Stage 3 callback on Unity's
        // SynchronizationContext; on slower emulators that race leaves the client in
        // MatchingScene even though the final assignment was delivered successfully.
        // The upper bound only protects abandoned clients; healthy clients cancel
        // this delay as soon as they enter JoinBattleRoom.
        await HoldFinalAssignmentAsync(playerSession.UserId, cancellationToken);
    }

    private async Task HoldFinalAssignmentAsync(string userId, CancellationToken cancellationToken)
    {
        _logger.LogInformation("Holding GetAssignments open for Stage 3 acknowledgement from user {UserId}", userId);
        await Task.Delay(TimeSpan.FromSeconds(30), cancellationToken);
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

    private static MatchingBattleInfo BuildRoster(ActiveBattleRoom room)
    {
        var info = new MatchingBattleInfo
        {
            // Bare wall-clock string: the client reads it in its own time base, so a UTC "now + 30 min" is already
            // hours in the past on a phone in UTC+8 and the very first roster update fails with "Timeout" (2026-09-14);
            // the emulator only worked because its clock runs on UTC. Use the far-future default instead.
            matchmakingExpirationDatetime = MatchmakingNeverExpires,
            photonCloudRegionId = 1,
            battlePlayerList = []
        };

        var usedKickers = new HashSet<int>();
        int team0Count = 0;
        int team1Count = 0;

        // 1. Add human players
        for (int i = 0; i < room.HumanPlayers.Count; i++)
        {
            var p = room.HumanPlayers[i];
            int team = (i % 2 == 0) ? 0 : 1;
            if (team == 0) team0Count++; else team1Count++;
            usedKickers.Add(p.KickerId);

            var playerName = p.UserName;
            if (i > 0 && playerName == room.HumanPlayers[0].UserName)
            {
                playerName = $"{p.UserName} (P{i + 1})";
            }

            var discs = p.DeckDiscs.Count >= 4 ? p.DeckDiscs : [3010001, 3010002, 3010003, 3010004];
            info.battlePlayerList.Add(new MatchingPlayerBattleInfo
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

        // 2. Fill remaining slots with AI Bots up to 4 on Team 0 (Blue) and 4 on Team 1 (Red) (8 total for 4v4)
        var availableBots = BotProfiles.Where(b => !usedKickers.Contains(b.KickerId)).ToList();
        var botIdx = 0;

        const int maxPerTeam = 4;
        var gym = GymEnabled;
        var totalPlayers = gym ? room.HumanPlayers.Count + GymBotCount : maxPerTeam * 2;

        while (info.battlePlayerList.Count < totalPlayers)
        {
            int team = gym ? 1 : (team0Count < maxPerTeam) ? 0 : 1;
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

