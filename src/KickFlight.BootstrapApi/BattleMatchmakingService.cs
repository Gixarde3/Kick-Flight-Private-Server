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
        public int teamType { get; set; } = 1; // 1 = Blue, 2 = Red
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

    public (string connection, string battleJson)? ResolveAssignment(string ticketId)
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

        // Multi-client matching check: find existing room with available human player slot for the same rule
        ActiveBattleRoom? matchedRoom = null;
        lock (_roomsByBattleId)
        {
            foreach (var room in _roomsByBattleId.Values)
            {
                if (room.BattleRuleId == playerSession.BattleRuleId && room.HumanPlayers.Count < 6)
                {
                    // Check if already in this room
                    if (room.HumanPlayers.Any(p => p.UserId == playerSession.UserId))
                    {
                        matchedRoom = room;
                        break;
                    }
                    if (room.HumanPlayers.Count < 2) // Join as second player!
                    {
                        matchedRoom = room;
                        room.HumanPlayers.Add(playerSession);
                        _logger.LogInformation("Matched second human player {UserId} into room {BattleId}", playerSession.UserId, room.BattleId);
                        break;
                    }
                }
            }

            if (matchedRoom == null)
            {
                var nextId = Interlocked.Increment(ref _battleCounter);
                var battleId = $"battle-{nextId}";
                matchedRoom = new ActiveBattleRoom
                {
                    BattleId = battleId,
                    BattleRuleId = playerSession.BattleRuleId,
                    FieldId = 101,
                    HumanPlayers = [playerSession]
                };
                _roomsByBattleId[battleId] = matchedRoom;
                _logger.LogInformation("Created new battle room {BattleId} for user {UserId}", battleId, playerSession.UserId);
            }
        }

        // Build 6-player battle roster (Human players + AI Bots for 3v3 arena)
        var battleInfo = BuildRoster(matchedRoom);
        matchedRoom.MatchingInfo = battleInfo;

        var json = JsonSerializer.Serialize(battleInfo);
        return (matchedRoom.BattleId, json);
    }

    public sealed record BotProfile(int KickerId, string Name);

    private static readonly BotProfile[] BotProfiles =
    [
        new(1, "Tsubame Bot"),
        new(2, "Kaito Bot"),
        new(3, "Ruriha Bot"),
        new(5, "Owlbert Bot"),
        new(6, "Grenhawk Bot"),
        new(7, "Pit Bot"),
        new(8, "Anna Bot"),
        new(9, "Diatrius Bot"),
        new(10, "Jay Bot"),
        new(12, "Yukari Bot"),
        new(13, "Yui Bot"),
        new(14, "Hitagi Bot"),
        new(4, "Coco Bot"),
        new(11, "Eleonora Bot")
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

        // 2. Fill remaining slots with AI Bots up to 3 on Team 0 (Blue) and 3 on Team 1 (Red) (6 total for 3v3)
        var availableBots = BotProfiles.Where(b => !usedKickers.Contains(b.KickerId)).ToList();
        var botIdx = 0;

        const int maxPerTeam = 3;
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

        var assignment = _matchmaking.ResolveAssignment(request.TicketId);
        if (assignment == null)
        {
            _logger.LogWarning("Could not resolve assignment for ticket {TicketId}", request.TicketId);
            return;
        }

        var (connection, battleJson) = assignment.Value;
        _logger.LogInformation("Resolved ticket {TicketId} -> connection: {Connection}", request.TicketId, connection);

        var battleStruct = Struct.Parser.ParseJson(battleJson);
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
        _logger.LogInformation("Streamed GetAssignmentsResponse for ticket {TicketId} successfully", request.TicketId);
    }
}
