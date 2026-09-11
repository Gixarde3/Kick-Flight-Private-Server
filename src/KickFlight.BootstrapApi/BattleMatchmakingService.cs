using System.Collections.Concurrent;
using System.Text.Json;
using Google.Protobuf.WellKnownTypes;
using Grpc.Core;
using OpenMatch;

namespace KickFlight.BootstrapApi;

public sealed class BattleMatchmakingService
{
    private readonly ILogger<BattleMatchmakingService> _logger;
    private readonly ConcurrentDictionary<string, BattleEntrySession> _entriesByTicket = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, ActiveBattleRoom> _roomsByBattleId = new(StringComparer.Ordinal);
    private int _battleCounter = 1000;

    public BattleMatchmakingService(ILogger<BattleMatchmakingService> logger)
    {
        _logger = logger;
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
                FieldId = 101,
                HumanPlayers = [playerSession]
            };
            _roomsByBattleId[battleId] = targetRoom;
            _pendingRoom = targetRoom;
            _pendingRoomTcs = new TaskCompletionSource<MatchingBattleInfo>(TaskCreationOptions.RunContinuationsAsynchronously);
            waitTask = _pendingRoomTcs.Task;
            _logger.LogInformation("Created pending battle room {BattleId} for user {UserId}, waiting up to 4s for second player", battleId, playerSession.UserId);
        }

        // Wait up to 4 seconds for opponent to join
        try
        {
            var completedTask = await Task.WhenAny(waitTask, Task.Delay(4000, cancellationToken));
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
            matchmakingExpirationDatetime = DateTime.UtcNow.AddMinutes(30).ToString("yyyy-MM-dd HH:mm:ss"),
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
                    FieldId = 101,
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
            await Task.Delay(1500, cancellationToken);
        }
        else
        {
            try
            {
                var completed = await Task.WhenAny(waitTask!, Task.Delay(3500, cancellationToken));
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

        // Hold room on 'Iniciar combate' for 2 seconds so user sees the complete roster
        await Task.Delay(2000, cancellationToken);

        // --- STAGE 3: Final assignment with non-empty Connection -> triggers Success (Result 1) and enters battle! ---
        await SendAssignmentUpdateAsync(responseStream, targetRoom.BattleId, fullRoster);
        _logger.LogInformation("Streamed Stage 3 (battle start assignment: {BattleId}) for user {UserId}", targetRoom.BattleId, playerSession.UserId);
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

    private static readonly BotProfile[] BotProfiles =
    [
        new(1, "Tsubame Bot"),
        new(2, "Kaito Bot"),
        new(3, "Ruriha Bot"),
        new(4, "Coco Bot"),
        new(6, "Grenhawk Bot"),
        new(7, "Pit Bot"),
        new(8, "Anna Bot"),
        new(9, "Diatrius Bot"),
        new(10, "Jay Bot"),
        new(12, "Yukari Bot"),
        new(13, "Yui Bot"),
        new(14, "Hitagi Bot"),
        new(11, "Eleonora Bot"),
        new(5, "Owlbert Bot")
    ];

    private static MatchingBattleInfo BuildRoster(ActiveBattleRoom room)
    {
        var info = new MatchingBattleInfo
        {
            matchmakingExpirationDatetime = DateTime.UtcNow.AddMinutes(30).ToString("yyyy-MM-dd HH:mm:ss"),
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

            var discs = p.DeckDiscs.Count >= 4 ? p.DeckDiscs : [3010001, 3010002, 3010003, 3010004];
            info.battlePlayerList.Add(new MatchingPlayerBattleInfo
            {
                userId = p.UserId,
                matchmakingTeamId = $"team-{(team == 0 ? 1 : 2)}",
                battleEntryId = p.BattleEntryId,
                name = p.UserName,
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
        const int totalPlayers = maxPerTeam * 2;

        while (info.battlePlayerList.Count < totalPlayers)
        {
            int team = (team0Count < maxPerTeam) ? 0 : 1;
            if (team == 0) team0Count++; else team1Count++;

            var profile = (botIdx < availableBots.Count) ? availableBots[botIdx++] : new BotProfile(botIdx + 1, $"Bot {botIdx + 1}");
            var botDiscs = new[] { 3010001, 3010002, 3010003, 3010004 };

            info.battlePlayerList.Add(new MatchingPlayerBattleInfo
            {
                userId = $"bot-{1000 + info.battlePlayerList.Count}",
                matchmakingTeamId = $"team-{(team == 0 ? 1 : 2)}",
                battleEntryId = $"be-bot-{info.battlePlayerList.Count}",
                name = profile.Name,
                rank = 10 + (info.battlePlayerList.Count % 4),
                kickerId = profile.KickerId,
                kickerCostumeId = 1,
                honorId = 6010000,
                teamType = team,
                kickerAiParameterId = profile.KickerId, // Valid AI parameter
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

