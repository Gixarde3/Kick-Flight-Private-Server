using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using KickFlight.BootstrapApi.PlayerStore;

namespace KickFlight.BootstrapApi;

public sealed partial class DemoSessionApi
{
    private const string CommonCode = "1a837b9ee2ae11a07a0f529a4cd4b61c";
    // The client keeps its downloaded masters until this header changes, so it must follow the content:
    // a SHA-256 over every served table (see the end of the constructor). Editing any config/masters_*.json
    // and restarting the server therefore makes the client re-download on its next launch.
    public string MasterVersion { get; private set; } = "demo-master-v27";
    private const string AccessToken = "demo-access-token-0000000000000000000000000000";

    // Rank is per player and persisted now (player_ranks, via IPlayerStore); the table it indexes into, the
    // range that renders, and the per-battle delta live in RankProgression.

    // Onboarding status, which is how the player is made to choose a name.
    //
    // TutorialUtil.IsTutorial is literally "tutorialProgressStatus != 207", and GetTutorialInitialSubStep maps
    // 206 to sub-step 16 (InputName), which HomeCharacterSelectView.RefreshTutorial opens as the name-entry
    // window. So: 206 while the player has no name, 207 once they do. Never 0 - that starts the long tutorial
    // at TapSlot, whose capsuleOpen / discBuildup / gachaDraw steps would each need a real inventory.
    //
    // Verified by decompiling the client; no client modification is involved.
    public const int TutorialStatusInputName = 206;
    public const int TutorialStatusComplete = 207;

    private static int TutorialStatus(SessionState state) =>
        state.HasName ? TutorialStatusComplete : TutorialStatusInputName;

    // The regular ladder. Only this one is progressed today (see HandleBattleResultAsync); the other two rule
    // types are reported at the same standing so the client's rank list has all three entries it expects.
    public const int RegularBattleRuleType = 1;
    private static readonly int[] RankedBattleRuleTypes = [1, 2, 3];

    private object[] BuildBattleRankList(SessionState state) =>
        RankedBattleRuleTypes.Select(ruleType =>
        {
            var rank = _playerStore.LoadRank(state.PlayerId, ruleType);
            return (object)new { battleRuleType = ruleType, battlePoint = rank.BattlePoint, rank = rank.Rank };
        }).ToArray();

    private readonly string _contentRoot;
    // A live session, key and state together. One dictionary rather than two parallel ones so the two can
    // never disagree about which tokens are known.
    //
    // This is a cache, not the record: the record is the store's sessions table. A token that is not here may
    // still be valid - it was issued before a restart - so a miss is resolved against the store, and only a
    // miss in both is a rejection.
    private sealed record CachedSession(byte[] Key, SessionState State);

    private readonly ConcurrentDictionary<string, CachedSession> _sessions = new(StringComparer.Ordinal);
    private readonly IPlayerStore _playerStore;
    private readonly Dictionary<string, byte[]> _encryptedMasters = new(StringComparer.Ordinal);
    private readonly Dictionary<int, int> _battleRuleTypeById = [];
    private readonly List<KickerInfo> _kickerList = [];
    // kickerId -> KickerCostume master ROW ids. The client keys everything by row id (KickerCostumeMaster is a plain
    // TMasterBase: UserKickerInfo.kickerCostumeId, /kicker/change, BattleInfo all carry the row id; it saves e.g. 110
    // for Hitagi's standard colour, 64 for Owlbert's), not by the per-kicker costumeId column (1, 2, 3...).
    private readonly Dictionary<int, List<int>> _costumesByKicker = [];
    private readonly Dictionary<int, int> _costumeKicker = [];   // row id -> kickerId
    private readonly List<int> _discIdList = [];
    private readonly List<int> _gearIdList = [];                 // Gear master row ids, the pool gear/create rolls from
    private readonly ILogger<DemoSessionApi> _logger;
    private readonly BattleMatchmakingService _matchmaking;

    public DemoSessionApi(ILogger<DemoSessionApi> logger, IWebHostEnvironment environment,
        BattleMatchmakingService matchmaking, IPlayerStore playerStore)
    {
        _logger = logger;
        _matchmaking = matchmaking;
        _playerStore = playerStore;
        _contentRoot = environment.ContentRootPath;
        InitializeMasters(environment.ContentRootPath);
    }

    private void InitializeMasters(string contentRoot)
    {
        var kickerJson = LoadJson(contentRoot, "config/masters_kicker.json", """[{"id":1,"name":"Tsubame","shortName":"Tsubame","nameSpelling":"Tsubame","voiceActorName":"CV: Yuma Uchida"}]""");
        var costumeJson = LoadJson(contentRoot, "config/masters_kicker_costume.json", """[{"id":1,"kickerId":1,"costumeId":1,"costumeName":"Tsubame - Color estándar","sortOrder":1,"battleResultPositionSortOrder":1,"battleResultModelScale":1.0,"exclusiveFlag":false,"releaseDatetime":"2019-01-01 00:00:00"}]""");
        var detailJson = LoadJson(contentRoot, "config/masters_kicker_detail.json", """[{"id":1,"kickerId":1,"kickerIntroductionText":"Veloz como el viento","kickerSkillName":"Corte Relámpago","kickerSkillShortText":"Ataque rápido","kickerSkillLongText":"Se lanza al frente","specialSkillName":"Torbellino","specialSkillShortText":"Tornado masivo","specialSkillLongText":"Crea un poderoso tornado","kickerAbilityName":"Paso Ligero","kickerAbilityShortText":"Velocidad","kickerAbilityLongText":"Más veloz con cristales","kickerDiscDistinctionText":"Combate aéreo","kickerGraphHpRate":0.8,"kickerGraphAttackRate":0.9,"kickerGraphSpeedRate":1.0,"age":18,"birthday":"1/1","height":"165cm","profileText":"Veloz como el viento"}]""");
        var parameterJson = LoadJson(contentRoot, "config/masters_kicker_parameter.json", "[]");
        var abilityJson = LoadJson(contentRoot, "config/masters_kicker_ability.json", "[]");
        var abilityConditionJson = LoadJson(contentRoot, "config/masters_kicker_ability_condition.json", "[]");
        var translationJson = LoadJson(contentRoot, "config/masters_translation.json", "[]");

        try
        {
            using var kDoc = JsonDocument.Parse(kickerJson);
            foreach (var el in kDoc.RootElement.EnumerateArray())
            {
                var id = el.GetProperty("id").GetInt32();
                var name = el.GetProperty("name").GetString() ?? $"Kicker {id}";
                _kickerList.Add(new KickerInfo(id, name));
            }

            using var cDoc = JsonDocument.Parse(costumeJson);
            foreach (var el in cDoc.RootElement.EnumerateArray())
            {
                var kickerId = el.GetProperty("kickerId").GetInt32();
                var costumeRowId = el.GetProperty("id").GetInt32();
                if (!_costumesByKicker.TryGetValue(kickerId, out var cList))
                {
                    cList = [];
                    _costumesByKicker[kickerId] = cList;
                }
                cList.Add(costumeRowId);
                _costumeKicker[costumeRowId] = kickerId;
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error parsing master json definitions: {Error}", ex.Message);
        }

        if (_kickerList.Count == 0)
        {
            // Only reached when the masters above could not be parsed at all. The costume is KickerCostume's
            // composite row id for kicker 1 / costume 1 rather than "1", because every id the server hands
            // the client is a lookup key into that master, not an index into our own files.
            _kickerList.Add(new KickerInfo(1, "Tsubame"));
            _costumesByKicker[1] = [2010101];
            _costumeKicker[2010101] = 1;
        }

        _encryptedMasters["Kicker"] = EncryptMaster(kickerJson);
        _encryptedMasters["KickerCostume"] = EncryptMaster(costumeJson);
        _encryptedMasters["KickerDetail"] = EncryptMaster(detailJson);
        _encryptedMasters["KickerParameter"] = EncryptMaster(parameterJson);
        _encryptedMasters["KickerAbility"] = EncryptMaster(ApplyObscuredOffsets("KickerAbility", abilityJson));
        _encryptedMasters["KickerAbilityCondition"] = EncryptMaster(abilityConditionJson);
        _encryptedMasters["Translation"] = EncryptMaster(translationJson);

        // FieldManager.InitializeAsync does FieldMaster[fieldId] and silently gives up (FieldInfo stays null, every
        // PlayerCharacter.Initialize then NREs and the loading screen never ends) when the row is missing. 801 is the
        // flat Trial arena BattleUtil.CreateTrialBattleInfo hard-codes (fld00801 / fielddata/fld00801_100 / mim00801_0).
        // One row per arena of BattleMatchmakingService.FieldPool (+ the home stage 99999 and the Trial arena 801).
        _encryptedMasters["Field"] = EncryptMaster("""[{"id":99999,"name":"FLD99999","minimapId":99999,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0},{"id":801,"name":"FLD00801","minimapId":801,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0},{"id":101,"name":"FLD00101","minimapId":101,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0},{"id":301,"name":"FLD00301","minimapId":301,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0},{"id":401,"name":"FLD00401","minimapId":401,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0},{"id":601,"name":"FLD00601","minimapId":601,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0},{"id":701,"name":"FLD00701","minimapId":701,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0},{"id":901,"name":"FLD00901","minimapId":901,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0}]""");
        // hp = turret HP per deposited crystal (StepHpValue; max HP = hp x crystal carry limit). Basic hits deal their
        // raw attack x coefficient to the turret and a kicker with four lv10 discs attacks for ~2000-3000, so 8000 =
        // about three hits per crystal (300 stripped ~10 crystals per hit). attack = beam damage before the receiver's
        // scaling (150 came out as ~50 on a ~40k HP kicker; 6000 = ~2000 per shot). Row 2 is the ball-rule goal
        // guardian: NPCRevivalableGuardian.SetMaxHP is MAX_HP_STEP_AMOUNT (6) x hp, so 6 x 3000 = 18000 = ~7 hits.
        // The file is the source; the literal is only the fallback for a checkout without config/.
        var guardianParameterJson = LoadJson(contentRoot, "config/masters_guardian_parameter.json", """[{"id":1,"matchType":1,"rank":1,"hp":8000,"attack":6000}]""");
        _encryptedMasters["GuardianParameter"] = EncryptMaster(guardianParameterJson);
        // guardianAmount is per team: GameManager.CreateGuardian spawns it for both teams and indexes
        // FieldManager.GetGuardianInitialPosition, and FLD00101_1 (the crystal-rule variant) has exactly two
        // guardian points; the ball variants (rules 3/4) also spawn one guard per goal, which must be destroyed
        // before the team can score. The file is the source; the literal is only the fallback.
        var battleRuleJson = LoadJson(contentRoot, "config/masters_battle_rule.json", """
            [
              {"id":1,"name":"Cristalmanía","seasonName":"Temporada 1","festivalName":"","matchType":1,"battleRuleType":1,"regularMatchFlag":true,"guardianAmount":1,"crystalAmount":50,"flagAmount":0,"generalAmount":0,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"},
              {"id":2,"name":"Vuelo de banderas","seasonName":"Temporada 1","festivalName":"","matchType":1,"battleRuleType":2,"regularMatchFlag":true,"guardianAmount":0,"crystalAmount":0,"flagAmount":1,"generalAmount":0,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"},
              {"id":3,"name":"Bola rápida","seasonName":"Temporada 1","festivalName":"","matchType":1,"battleRuleType":3,"regularMatchFlag":true,"guardianAmount":1,"crystalAmount":0,"flagAmount":0,"generalAmount":1,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"},
              {"id":4,"name":"Bola rápida","seasonName":"","festivalName":"","matchType":2,"battleRuleType":3,"regularMatchFlag":false,"guardianAmount":1,"crystalAmount":0,"flagAmount":0,"generalAmount":1,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"},
              {"id":5,"name":"Cristalmanía","seasonName":"Temporada 1","festivalName":"","matchType":3,"battleRuleType":1,"regularMatchFlag":false,"guardianAmount":1,"crystalAmount":50,"flagAmount":0,"generalAmount":0,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2020-01-01 00:00:00"},
              {"id":6,"name":"Festival Kick-Flight","seasonName":"","festivalName":"Festival Kick-Flight","matchType":4,"battleRuleType":1,"regularMatchFlag":false,"guardianAmount":1,"crystalAmount":50,"flagAmount":0,"generalAmount":0,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2020-01-01 00:00:00"}
            ]
            """);
        _encryptedMasters["BattleRule"] = EncryptMaster(battleRuleJson);
        // id -> battleRuleType, read by /battle/start to pick the guardian for the requested rule. Parsed once here
        // because the request handler only sees the rule id, not its type.
        try
        {
            using var brDoc = JsonDocument.Parse(battleRuleJson);
            foreach (var el in brDoc.RootElement.EnumerateArray())
            {
                if (el.TryGetProperty("id", out var idProp) && el.TryGetProperty("battleRuleType", out var typeProp))
                {
                    _battleRuleTypeById[idProp.GetInt32()] = typeProp.GetInt32();
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error parsing battle rule json: {Error}", ex.Message);
        }

        // every rule can be played on every arena of the pool (equal ratio); the server, not the client, draws the field
        _encryptedMasters["BattleRuleField"] = EncryptMaster("""[{"id":1,"battleRuleId":1,"fieldId":101,"ratio":16},{"id":2,"battleRuleId":1,"fieldId":301,"ratio":16},{"id":3,"battleRuleId":1,"fieldId":401,"ratio":16},{"id":4,"battleRuleId":1,"fieldId":601,"ratio":16},{"id":5,"battleRuleId":1,"fieldId":701,"ratio":16},{"id":6,"battleRuleId":1,"fieldId":901,"ratio":16},{"id":7,"battleRuleId":2,"fieldId":101,"ratio":16},{"id":8,"battleRuleId":2,"fieldId":301,"ratio":16},{"id":9,"battleRuleId":2,"fieldId":401,"ratio":16},{"id":10,"battleRuleId":2,"fieldId":601,"ratio":16},{"id":11,"battleRuleId":2,"fieldId":701,"ratio":16},{"id":12,"battleRuleId":2,"fieldId":901,"ratio":16},{"id":13,"battleRuleId":3,"fieldId":101,"ratio":16},{"id":14,"battleRuleId":3,"fieldId":301,"ratio":16},{"id":15,"battleRuleId":3,"fieldId":401,"ratio":16},{"id":16,"battleRuleId":3,"fieldId":601,"ratio":16},{"id":17,"battleRuleId":3,"fieldId":701,"ratio":16},{"id":18,"battleRuleId":3,"fieldId":901,"ratio":16},{"id":19,"battleRuleId":4,"fieldId":101,"ratio":16},{"id":20,"battleRuleId":4,"fieldId":301,"ratio":16},{"id":21,"battleRuleId":4,"fieldId":401,"ratio":16},{"id":22,"battleRuleId":4,"fieldId":601,"ratio":16},{"id":23,"battleRuleId":4,"fieldId":701,"ratio":16},{"id":24,"battleRuleId":4,"fieldId":901,"ratio":16},{"id":25,"battleRuleId":5,"fieldId":101,"ratio":16},{"id":26,"battleRuleId":5,"fieldId":301,"ratio":16},{"id":27,"battleRuleId":5,"fieldId":401,"ratio":16},{"id":28,"battleRuleId":5,"fieldId":601,"ratio":16},{"id":29,"battleRuleId":5,"fieldId":701,"ratio":16},{"id":30,"battleRuleId":5,"fieldId":901,"ratio":16},{"id":31,"battleRuleId":6,"fieldId":101,"ratio":16},{"id":32,"battleRuleId":6,"fieldId":301,"ratio":16},{"id":33,"battleRuleId":6,"fieldId":401,"ratio":16},{"id":34,"battleRuleId":6,"fieldId":601,"ratio":16},{"id":35,"battleRuleId":6,"fieldId":701,"ratio":16},{"id":36,"battleRuleId":6,"fieldId":901,"ratio":16}]""");
        // The file is the source; the literal is only the fallback.
        var regularMatchScheduleJson = LoadJson(contentRoot, "config/masters_regular_match_battle_schedule.json", """
            [
              {"id":1,"seasonMatchBattleRuleType":3,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":1,"sortOrder":1},
              {"id":2,"seasonMatchBattleRuleType":3,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":2,"sortOrder":2},
              {"id":3,"seasonMatchBattleRuleType":3,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":3,"sortOrder":3},
              {"id":4,"seasonMatchBattleRuleType":-1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":1,"sortOrder":1},
              {"id":5,"seasonMatchBattleRuleType":-1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":2,"sortOrder":2},
              {"id":6,"seasonMatchBattleRuleType":-1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":3,"sortOrder":3}
            ]
            """);
        _encryptedMasters["RegularMatchBattleSchedule"] = EncryptMaster(regularMatchScheduleJson);
        _encryptedMasters["RankerMatchBattleSchedule"] = EncryptMaster("""
            [
              {"id":1,"seasonMatchBattleRuleType":1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":4,"sortOrder":1},
              {"id":2,"seasonMatchBattleRuleType":2,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":4,"sortOrder":1},
              {"id":3,"seasonMatchBattleRuleType":3,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":4,"sortOrder":1},
              {"id":4,"seasonMatchBattleRuleType":-1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":4,"sortOrder":1}
            ]
            """);
        // Retail is rows 1..17 (rank 0..16): D, C, C⁺, B, B⁺, A, A⁺, S, S⁺1 … S⁺9 — one row per league badge the
        // client ships (ui/league/thumbnail_league_0 … _16, see config/resources/catalog.json). The rank glyphs are
        // resolved by index, so a short table shifts every name by one and the two top ranks have no sprite at all:
        // BattleRankMaster.OnLoadComplete picks RegularEndRank as the first row with regularMatchFlag == 0, and
        // BattleUtil.GetDisplayRankPath caps rank to RegularEndRank.Rank with variant 1 (asset thumbnail_league_<n>_1)
        // for battleRuleType 1. Retail ships exactly one such variant asset, thumbnail_league_7_1 (S with the up
        // arrow), so RegularEndRank must be rank 7 = S: regularMatchFlag is true for ranks 0..6 and false from rank 7.
        // With the old 12-row table RegularEndRank was rank 4 and an S-rank player asked for thumbnail_league_4_1 /
        // _11_1, neither of which exists — the Image kept a null sprite, which is the empty rectangle in the
        // mode-selection banner and the black rectangle beside the lobby portrait.
        _encryptedMasters["BattleRank"] = EncryptMaster("""
            [
              {"id":1,"name":"D","rank":0,"regularMatchFlag":true,"totalBattlePoint":0,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":2,"name":"C","rank":1,"regularMatchFlag":true,"totalBattlePoint":200,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":3,"name":"C⁺","rank":2,"regularMatchFlag":true,"totalBattlePoint":500,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":4,"name":"B","rank":3,"regularMatchFlag":true,"totalBattlePoint":900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":5,"name":"B⁺","rank":4,"regularMatchFlag":true,"totalBattlePoint":1400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":6,"name":"A","rank":5,"regularMatchFlag":true,"totalBattlePoint":1900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":7,"name":"A⁺","rank":6,"regularMatchFlag":true,"totalBattlePoint":2400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":8,"name":"S","rank":7,"regularMatchFlag":false,"totalBattlePoint":2900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":9,"name":"S⁺1","rank":8,"regularMatchFlag":false,"totalBattlePoint":3400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":10,"name":"S⁺2","rank":9,"regularMatchFlag":false,"totalBattlePoint":3900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":11,"name":"S⁺3","rank":10,"regularMatchFlag":false,"totalBattlePoint":4400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":12,"name":"S⁺4","rank":11,"regularMatchFlag":false,"totalBattlePoint":4900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":13,"name":"S⁺5","rank":12,"regularMatchFlag":false,"totalBattlePoint":5400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":14,"name":"S⁺6","rank":13,"regularMatchFlag":false,"totalBattlePoint":5900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":15,"name":"S⁺7","rank":14,"regularMatchFlag":false,"totalBattlePoint":6400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":16,"name":"S⁺8","rank":15,"regularMatchFlag":false,"totalBattlePoint":6900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":17,"name":"S⁺9","rank":16,"regularMatchFlag":false,"totalBattlePoint":7500,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false}
            ]
            """);
        _encryptedMasters["CapsuleCampaign"] = EncryptMaster("""[{"id":1,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59","coefficient":0.5}]""");
        _encryptedMasters["CapsuleDropCampaign"] = EncryptMaster("""[{"id":1,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"}]""");
        _encryptedMasters["BattleRankingClass"] = EncryptMaster("""[{"id":1,"battleRuleId":1,"name":"Clase 1","minBattlePoint":0},{"id":2,"battleRuleId":2,"name":"Clase 1","minBattlePoint":0},{"id":3,"battleRuleId":3,"name":"Clase 1","minBattlePoint":0},{"id":4,"battleRuleId":4,"name":"Div.1","minBattlePoint":0},{"id":5,"battleRuleId":5,"name":"Div.1","minBattlePoint":0},{"id":6,"battleRuleId":6,"name":"Clase 1","minBattlePoint":0}]""");
        _encryptedMasters["HomeFieldSchedule"] = EncryptMaster("""[{"id":1,"fieldId":99999,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"}]""");
        _encryptedMasters["Festival"] = EncryptMaster("""[{"id":1,"battleRuleId":6,"theme":"Festival Kick-Flight"}]""");
        _encryptedMasters["FestivalTeam"] = EncryptMaster("""[{"id":1,"battleRuleId":6,"name":"Equipo Rojo","color":"#FF0000"},{"id":2,"battleRuleId":6,"name":"Equipo Azul","color":"#0000FF"}]""");
        _encryptedMasters["BattleRuleParameter"] = EncryptMaster("""
            [
              {"id":1,"battleRuleId":1,"description":"sin afectar tu rango","subRuleName":"Combate por diversión","itemDecelerationMaxCount":0},
              {"id":2,"battleRuleId":2,"description":"sin afectar tu rango","subRuleName":"Combate por diversión","itemDecelerationMaxCount":0},
              {"id":3,"battleRuleId":3,"description":"sin afectar tu rango","subRuleName":"Combate por diversión","itemDecelerationMaxCount":0},
              {"id":4,"battleRuleId":4,"description":"Combate feroz con rangos S","subRuleName":"Combate de clasificación","itemDecelerationMaxCount":0},
              {"id":5,"battleRuleId":5,"description":"Temporada 1","subRuleName":"Combate de temporada","itemDecelerationMaxCount":0},
              {"id":6,"battleRuleId":6,"description":"Combate de festival","subRuleName":"Festival Kick-Flight","itemDecelerationMaxCount":0}
            ]
            """);
        _encryptedMasters["Capsule"] = EncryptMaster("""
            [
              {"id":5010001,"lotteryId":1,"name":"Cápsula estándar","openTime":"01:00:00","lotteryDiscRarityGroupId":1,"lotteryDiscDropAmountGroupId":1},
              {"id":5010002,"lotteryId":2,"name":"Cápsula dorada","openTime":"12:00:00","lotteryDiscRarityGroupId":2,"lotteryDiscDropAmountGroupId":2},
              {"id":5010003,"lotteryId":3,"name":"Cápsula de madera","openTime":"03:00:00","lotteryDiscRarityGroupId":1,"lotteryDiscDropAmountGroupId":1}
            ]
            """);

        var weaponList = new List<object>();
        int weaponId = 1;
        var catalogPath = RepositoryPaths.Resolve("config/resources/catalog.json", contentRoot);
        bool loadedFromCatalog = false;

        if (File.Exists(catalogPath))
        {
            try
            {
                using var catDoc = JsonDocument.Parse(File.ReadAllText(catalogPath));
                if (catDoc.RootElement.TryGetProperty("resources", out var resArray))
                {
                    // weaponType per kicker: a Drone (4) is not held, it hovers from the body's Prop_Common bone
                    var weaponTypes = new Dictionary<int, int>();
                    try
                    {
                        using var kpDoc = JsonDocument.Parse(parameterJson);
                        foreach (var k in kpDoc.RootElement.EnumerateArray())
                            if (k.TryGetProperty("weaponType", out var wt)) weaponTypes[k.GetProperty("kickerId").GetInt32()] = wt.GetInt32();
                    }
                    catch (Exception ex) { _logger.LogWarning("Could not read weapon types: {Error}", ex.Message); }
                    var validWeapons = new SortedSet<(int kickerId, int modelId, int propId)>();
                    var weaponRegex = new System.Text.RegularExpressions.Regex(@"weapon/wp_(\d+)/wp_\d+_(\d+)_(\d+)\.unity3d");
                    foreach (var res in resArray.EnumerateArray())
                    {
                        if (res.TryGetProperty("logicalName", out var logName))
                        {
                            var match = weaponRegex.Match(logName.GetString() ?? "");
                            if (match.Success)
                            {
                                validWeapons.Add((
                                    int.Parse(match.Groups[1].Value),
                                    int.Parse(match.Groups[2].Value),
                                    int.Parse(match.Groups[3].Value)
                                ));
                            }
                        }
                    }

                    if (validWeapons.Count > 0)
                    {
                        foreach (var (k, m, p) in validWeapons)
                        {
                            // props 101/201 are alternate right-hand models, 102/202 alternate left-hand ones (JapaneseSword
                            // "OverSoul" 201/202, Drone/Laser 101...). A row with an empty bone is parented to nothing and
                            // JapaneseSwordAction.Initialize then dies in GetComponentInParent -> the whole home/select model fails.
                            // Only the base props are attach rows. 101/201/202 (Drone extras, JapaneseSword "OverSoul"
                            // forms...) are swapped in by the weapon/skill code itself; served as attach rows they leave
                            // Owlbert/Jay/Yuyan/Hitagi without a model in Home and character select.
                            weaponTypes.TryGetValue(k, out var kwt);
                            string bone;
                            var attach = 1;                                               // PropAttachType.Child
                            // Bone names come from the client: ShieldPropTypeExtensions/LaserPropTypeTypeExtensions.AttachBoneName
                            // resolve the wrist props by "Prop_R2"/"Prop_L2" (Buzzy's shields, Sid's lasers - the *2 bones sit on
                            // the forearm with the opposite orientation, which is why Prop_L put the left shield on the wrong side of
                            // the arm and the lasers pointed sideways); everything hand-held uses "Prop_R"/"Prop_L".
                            // Drone (Owlbert) and Nunchaku (Yuyan) weapons are animated by the body clips: the clips bind
                            // "Root/wp_005_001_Root/wp_005_001_Hip/..." (the drone hover, and the SS mini drones under
                            // wp_005_101_Root / wp_005_201_Root), ".../Hand_R/Prop_R/wp_010_001_Root/wp_010_001_Grip_L" (the
                            // nunchaku swing / dangling panda head) and "Root/wp_010_201_Root" (the SS panda mount), so those rows
                            // need the exact bone and the model root renamed to "wp_<kicker>_<prop>_Root" (Weapon.Initialize sets
                            // the instantiated model's name from rootName). Verified with scripts/re/anim_paths.py (CRC32 path
                            // hashes of every clip vs. the body + weapon prefab hierarchies).
                            var wristProps = kwt == 9 || kwt == 13;                       // Shield, Laser
                            if (p == 1) bone = kwt == 4 ? "Root" : wristProps ? "Prop_R2" : "Prop_R";
                            else if (p == 2) bone = wristProps ? "Prop_L2" : "Prop_L";
                            else if (p == 201 && kwt == 11) bone = "Root";               // Nunchaku panda mount (NunchakuPandaAction)
                            else if (p == 101 && kwt == 13) bone = "Root";               // Laser prop 101 = Sid's decoy statue (LaserPropType.KickerSkillStatue):
                                                                                        // StatueTrapAction..ctor does ModelManager.InstantiateWeaponModel(kicker,
                                                                                        // model, 101, parent: trap) and LoadManager only preloads the weapon
                                                                                        // bundles that have a Weapon row (LoadWeaponModelAsync ->
                                                                                        // GetWeaponAttachData), so without this row the cache misses and the
                                                                                        // kicker skill NREs in the ctor (logcat 2026-09-21). Hidden on the
                                                                                        // player like every prop >= 100; "Root" so LaserAttackAction's
                                                                                        // GetWeapon("Prop_R2") never resolves to the statue.
                            else if ((p == 201 && (kwt == 4 || kwt == 10)) || (p == 101 && kwt == 4))
                            {
                                // Drone prop 101 is the drone unit itself: NPCDrone.InitializeAsync instantiates weapon prop 101
                                // and reads owner.GetWeapon(101).ModelCtr, so Owlbert's kicker skill (silence drone trap) and
                                // special (smog drones for the team) spawn nothing without this row.
                                // HighPlayerCharacter builds its weapons from the modelId-1 rows too (ObjectUtil.
                                // GetHighWeaponAttachData(id, 1)), so the cut-in rows must exist for modelId 1, not only 101.
                                // Drone (Owlbert) and Bat (Jay) special-skill cut-ins call HighPlayerCharacter.GetWeapon(201)
                                // and dereference its ModelCtr (DroneSpecialSkillCutAction/BatSpecialSkillCutAction.Initialize):
                                // without a 201 row the NRE kills PlayerCharacter.ResetPlayer and the battle never loads.
                                // Attached as a Child like prop 1 (props >= 100 are hidden by Weapon.Initialize and shown by the
                                // skill code itself); the old breakage with 101/201 rows came from serving them as
                                // PropAttachType.Replace rows.
                                bone = kwt == 4 ? "Root" : "Prop_R";
                            }
                            else continue;
                            weaponList.Add(new { id = weaponId++, kickerId = k, modelId = m, propId = p, boneName = bone, rootName = $"wp_{k:000}_{p:000}_Root", attachType = attach });
                        }
                        loadedFromCatalog = true;
                        _logger.LogInformation("Loaded {Count} authentic weapon master entries from catalog.json", weaponList.Count);
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning("Failed to parse weapon catalog from {Path}: {Error}", catalogPath, ex.Message);
            }
        }

        if (!loadedFromCatalog)
        {
            var kickerProps = new Dictionary<int, int[]>
            {
                [1] = [1],
                [2] = [1],
                [3] = [1],
                // 4 has no weapons
                [5] = [1],
                [6] = [1],
                [7] = [1],
                [8] = [1],
                [9] = [1],
                [10] = [1],
                // 11 has no weapons
                [12] = [1, 2],
                [13] = [1, 2],
                [14] = [1, 2]
            };

            foreach (var (k, props) in kickerProps)
            {
                foreach (var mId in new[] { 1, 101 })
                {
                    foreach (var pId in props)
                    {
                        var bone = pId == 1 ? "Prop_R" : pId == 2 ? "Prop_L" : "";
                        var attach = (pId == 1 || pId == 2) ? 1 : 2;
                        weaponList.Add(new { id = weaponId++, kickerId = k, modelId = mId, propId = pId, boneName = bone, rootName = "", attachType = attach });
                    }
                }
            }
        }

        // TwoGuns kickers fire from both hands: TwoGunsAttackAction resolves the weapon by bone name ("Prop_R" for
        // RightHandWeapon, "Prop_L" for LeftHandWeapon) and the only bundle that exists is prop 1, so the left gun is a
        // second attach row of the same model on Prop_L (otherwise PlayerCharacter.GetWeapon returns null -> NRE per shot).
        try
        {
            using var kpDoc = JsonDocument.Parse(parameterJson);
            var twoGunKickers = kpDoc.RootElement.EnumerateArray()
                .Where(k => k.TryGetProperty("weaponType", out var wt) && wt.GetInt32() == 1)
                .Select(k => k.GetProperty("kickerId").GetInt32()).ToHashSet();
            var leftHand = new List<object>();
            foreach (var w in weaponList)
            {
                var wj = JsonSerializer.SerializeToElement(w);
                if (twoGunKickers.Contains(wj.GetProperty("kickerId").GetInt32()) && wj.GetProperty("propId").GetInt32() == 1)
                    leftHand.Add(new { id = weaponId++, kickerId = wj.GetProperty("kickerId").GetInt32(), modelId = wj.GetProperty("modelId").GetInt32(), propId = 1, boneName = "Prop_L", rootName = "", attachType = 1 });
            }
            weaponList.AddRange(leftHand);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not add left-hand weapon rows: {Error}", ex.Message);
        }
        _encryptedMasters["Weapon"] = EncryptMaster(JsonSerializer.Serialize(weaponList));



        var levelExpList = Enumerable.Range(1, 50).Select(lvl => new
        {
            id = lvl,
            level = lvl,
            totalExp = (lvl - 1) * 1000
        });
        _encryptedMasters["PlayerLevelExp"] = EncryptMaster(JsonSerializer.Serialize(levelExpList));

        _encryptedMasters["Frame"] = EncryptMaster("""[{"id":1,"name":"Marco estándar","battleRuleId":0}]""");
        // ItemMasterData: MasterData(id) + goodsType, name, maxAmount. ids 1-4 are the legacy counters; 5-8 carry the
        // goodsTypes the gear screen (202 gear stamps), the gacha (401/402 tickets) and the goods shop trade in.
        var itemJson = """
            [
              {"id":1,"goodsType":101,"name":"JetCoin","maxAmount":9999999},
              {"id":2,"goodsType":102,"name":"PaidJetCoin","maxAmount":9999999},
              {"id":3,"goodsType":302,"name":"DiscForce","maxAmount":9999999},
              {"id":4,"goodsType":701,"name":"KickPoint","maxAmount":9999999},
              {"id":5,"goodsType":202,"name":"GearMaterial","maxAmount":9999999},
              {"id":6,"goodsType":303,"name":"DiscFragment","maxAmount":9999999},
              {"id":7,"goodsType":401,"name":"KickerGachaTicket","maxAmount":9999999},
              {"id":8,"goodsType":402,"name":"DiscGachaTicket","maxAmount":9999999}
            ]
            """;
        _encryptedMasters["Item"] = EncryptMaster(itemJson);
        ParseItemMaster(itemJson);

        var discJson = LoadJson(contentRoot, "config/masters_disc.json", "[]");
        var skillJson = LoadJson(contentRoot, "config/masters_skill.json", "[]");
        var discGrowJson = LoadJson(contentRoot, "config/masters_disc_grow.json", "[]");
        var discBuildupJson = LoadJson(contentRoot, "config/masters_disc_buildup.json", "[]");
        var initialDiscDeckJson = LoadJson(contentRoot, "config/masters_initial_disc_deck.json", "[]");
        var gearJson = LoadJson(contentRoot, "config/masters_gear.json", "[]");
        var gearSkillJson = LoadJson(contentRoot, "config/masters_gear_skill.json", "[]");
        var gearSameColorBonusJson = LoadJson(contentRoot, "config/masters_gear_same_color_bonus.json", "[]");

        try
        {
            using var dDoc = JsonDocument.Parse(discJson);
            foreach (var el in dDoc.RootElement.EnumerateArray())
            {
                var id = el.GetProperty("id").GetInt32();
                _discIdList.Add(id);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error parsing disc master json: {Error}", ex.Message);
        }

        if (_discIdList.Count == 0)
        {
            for (var i = 3010001; i <= 3010135; i++) _discIdList.Add(i);
        }

        try
        {
            using var gDoc = JsonDocument.Parse(gearJson);
            foreach (var el in gDoc.RootElement.EnumerateArray())
            {
                _gearIdList.Add(el.GetProperty("id").GetInt32());
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error parsing gear master json: {Error}", ex.Message);
        }

        _encryptedMasters["Disc"] = EncryptMaster(ApplyObscuredOffsets("Disc", discJson));
        _encryptedMasters["Skill"] = EncryptMaster(ApplyObscuredOffsets("Skill", skillJson));
        _encryptedMasters["DiscGrow"] = EncryptMaster(discGrowJson);
        _encryptedMasters["DiscBuildup"] = EncryptMaster(discBuildupJson);
        _encryptedMasters["DiscForceCampaign"] = EncryptMaster("[]");
        _encryptedMasters["InitialDiscDeck"] = EncryptMaster(initialDiscDeckJson);
        _encryptedMasters["Gear"] = EncryptMaster(gearJson);
        _encryptedMasters["GearSkill"] = EncryptMaster(gearSkillJson);
        _encryptedMasters["GearSameColorBonus"] = EncryptMaster(gearSameColorBonusJson);

        var aiParamJson = LoadJson(contentRoot, "config/masters_kicker_ai_parameter.json", "[]");
        var aiDiscJson = LoadJson(contentRoot, "config/masters_kicker_ai_disc.json", "[]");
        var aiDeckJson = LoadJson(contentRoot, "config/masters_kicker_ai_disc_deck.json", "[]");
        var pingThresholdJson = LoadJson(contentRoot, "config/masters_matchmaking_ping_threshold.json", "[]");

        _encryptedMasters["KickerAiParameter"] = EncryptMaster(AppendGymAiRows(aiParamJson));
        _encryptedMasters["KickerAiDisc"] = EncryptMaster(aiDiscJson);
        _encryptedMasters["KickerAiDiscDeck"] = EncryptMaster(aiDeckJson);
        _encryptedMasters["MatchmakingPingThreshold"] = EncryptMaster(pingThresholdJson);

        // Battle & Combat Masters. Every table is a config/masters_*.json file (templates come from
        // scripts/generate_combat_masters.py, column meanings in docs/COMBAT_MASTERS_FILL_IN.md). The client
        // throws NullReferenceException inside animation events when the per-kicker WeaponAttackHit/Collision
        // rows or the per-skill Summon row are missing, so a missing file falls back to an empty table only.
        foreach (var (masterName, fileName) in new (string, string)[]
        {
            ("WeaponAttack", "masters_weapon_attack.json"),
            ("WeaponAttackHit", "masters_weapon_attack_hit.json"),
            ("WeaponAttackCollision", "masters_weapon_attack_collision.json"),
            ("WeaponAttackBullet", "masters_weapon_attack_bullet.json"),
            ("WeaponAttackCondition", "masters_weapon_attack_condition.json"),
            ("SkillCondition", "masters_skill_condition.json"),
            ("SkillHeal", "masters_skill_heal.json"),
            ("SkillBlowOff", "masters_skill_blow_off.json"),
            ("SkillPullIn", "masters_skill_pull_in.json"),
            ("SkillTrap", "masters_skill_trap.json"),
            ("SkillCollision", "masters_skill_collision.json"),   // guardian turret beam (NPCSkillParameter.SetCollisionInitInfos)
            ("SkillHit", "masters_skill_hit.json"),               // guardian turret beam (NPCSkillParameter.SetAttackHitInfos)
            ("Summon", "masters_summon.json"),
            ("CommonConditionHit", "masters_common_condition_hit.json"),
            ("SpecialSkill", "masters_special_skill.json"),
            ("SpecialSkillHit", "masters_special_skill_hit.json"),
            ("SpecialSkillCollision", "masters_special_skill_collision.json"),
            ("SpecialSkillBullet", "masters_special_skill_bullet.json"),
            ("SpecialSkillCondition", "masters_special_skill_condition.json"),
            ("SpecialSkillBlowOff", "masters_special_skill_blow_off.json"),
            ("SpecialSkillTrap", "masters_special_skill_trap.json"),
        })
        {
            var json = LoadJson(contentRoot, "config/" + fileName, "[]");
            if (json.Trim() == "[]" && masterName is "WeaponAttack" or "WeaponAttackHit" or "WeaponAttackCollision" or "Summon" or "SpecialSkill" or "SpecialSkillHit" or "SpecialSkillCollision")
                _logger.LogWarning("Combat master {Master} is empty ({File} missing?) - attacks/skills will throw in the client", masterName, fileName);
            _encryptedMasters[masterName] = EncryptMaster(ApplyObscuredOffsets(masterName, json));
        }

        // PlayerStateDeposit.get_DepositTime = powf(depositCount, crystalDepositSpeedCoefficient) - 0.2, depositCount
        // starting at 1 and +1 per crystal of the same deposit. 1.0 made every consecutive crystal slower (0.8, 1.8,
        // 2.8 s ...); a negative exponent makes them faster: -0.5 -> 0.8, 0.51, 0.38, 0.30, 0.25 s.
        _encryptedMasters["BattleRuleScramble"] = EncryptMaster("""
            [
              {"id":1,"battleRuleId":1,"crystalDepositSpeedCoefficient":-0.1},
              {"id":2,"battleRuleId":5,"crystalDepositSpeedCoefficient":-0.1},
              {"id":3,"battleRuleId":6,"crystalDepositSpeedCoefficient":-0.1}
            ]
            """);

        var roleParams = new List<object>();
        int rId = 1;
        for (int rule = 1; rule <= 6; rule++)
        {
            for (int role = 1; role <= 4; role++)
            {
                roleParams.Add(new { id = rId++, battleRuleId = rule, roleType = role, crystalCountSpeedCorrection = 1.0f });
            }
        }
        _encryptedMasters["BattleRuleRoleParameter"] = EncryptMaster(JsonSerializer.Serialize(roleParams));

        _encryptedMasters["BattleRuleScrambleScore"] = EncryptMaster("""
            [
              {
                "id": 1,
                "battleRuleId": 1,
                "baseScore": 100,
                "stackedCountScore": 10,
                "depositCount": 10,
                "crystalCountScore": 10,
                "dropCountScore": 10,
                "killCountScore": 50,
                "killAssistCountScore": 25,
                "assistCountScore": 25,
                "specialSkillCountScore": 30,
                "winScoreCorrection": 1.5
              }
            ]
            """);

        // BallShootRuleController.GetScore / FlagFlightRuleController.GetScore read these every frame and at match end
        // (RuleControllerBase.CalcScore); a missing row NREs and the client never leaves "Cargando". The lookup is
        // TMasterBase.get_Item(battleRuleId) - by row *id*, with a hard-coded fallback to id 3 - so each row's id must
        // equal its battleRuleId (verified 2026-09-19: ids 1/2 kept the NRE, ids 3/4 fixed it).
        _encryptedMasters["BattleRuleRapidBallScore"] = EncryptMaster(LoadJson(contentRoot, "config/masters_battle_rule_rapid_ball_score.json", "[]"));
        _encryptedMasters["BattleRuleFlagFlightScore"] = EncryptMaster(LoadJson(contentRoot, "config/masters_battle_rule_flag_flight_score.json", "[]"));

        _encryptedMasters["Guardian"] = EncryptMaster("""
            [
              {"id":1,"modelId":1,"skillId":1,"attack":100,"defense":100,"laserLength":50.0,"targetSearchRadius":30.0,"aIInterval":1.0}
            ]
            """);

        var kickerAis = Enumerable.Range(1, 14).Select(k => new
        {
            id = k,
            kickerId = k,
            kickerAiParameterId = k
        });
        _encryptedMasters["KickerAi"] = EncryptMaster(JsonSerializer.Serialize(kickerAis));

        // The tutorial fights a scripted battle instead of loading a normal home, which is why this table cannot
        // stay empty. HomeScene.<PreBeginAsync>d__3 skips NetworkManager.HomeAsync whenever TutorialUtil.IsTutorial
        // (tutorialProgressStatus != 207), so the tutorial scene has to get everything it needs from the masters;
        // with no rows here the lookup came back null, the home never finished loading and the client hung on the
        // LOADING splash with a NullReferenceException in that same MoveNext (verified 2026-09-22: logcat
        // 17:30:52.923, and no POST /home/index in the API log at all).
        //
        // The rows mirror KickerAi, whose shape is proven against this client (bots fight with it). The extra keys
        // are deliberate: the tutorial's row class is TutorialKickerAiMasterData and we have not recovered its
        // field list, so each row carries the spellings the KickerAi family uses - the family prefixes the *class*
        // (KickerAiMasterData, KickerAiDiscDeckMasterData) but shares the *fields* (id, kickerAiParameterId,
        // kickerAiDiscId1..4) - and Unity's JsonUtility ignores the ones the class does not declare. Remove the
        // aliases once the real field list is known. kickerAiDiscDeckId stays 1 because KickerAiDiscDeck has rows
        // 1..6 and a reference to a missing deck is the same kind of null.
        var tutorialKickerAis = Enumerable.Range(1, 14).Select(k => new
        {
            id = k,
            kickerId = k,
            kickerAiParameterId = k,
            kickerAiDiscDeckId = 1,
            tutorialKickerAiId = k,
            tutorialKickerAiParameterId = k
        });
        _encryptedMasters["TutorialKickerAi"] = EncryptMaster(JsonSerializer.Serialize(tutorialKickerAis));

        // Round C: the gacha and goods shop tables (config/masters_gacha_group.json and friends), plus the drop
        // tables the draw endpoints read. Registered here so the master hash covers them too.
        InitializeGachaMasters(contentRoot);

        using (var sha = SHA256.Create())
        {
            foreach (var kvp in _encryptedMasters.OrderBy(k => k.Key, StringComparer.Ordinal))
            {
                var nameBytes = Encoding.UTF8.GetBytes(kvp.Key);
                sha.TransformBlock(nameBytes, 0, nameBytes.Length, null, 0);
                sha.TransformBlock(kvp.Value, 0, kvp.Value.Length, null, 0);
            }
            sha.TransformFinalBlock(Array.Empty<byte>(), 0, 0);
            MasterVersion = "demo-master-" + Convert.ToHexString(sha.Hash!)[..16].ToLowerInvariant();
        }
        _logger.LogInformation("Master version {MasterVersion} ({Count} tables)", MasterVersion, _encryptedMasters.Count);
    }

    // Loads a player, creating them empty if the id is unknown, and repairs whatever the masters no longer
    // support. The repair is policy, which is why it stays here: it needs _discIdList, and the store is only
    // responsible for persisting the document.
    private SessionState GetOrCreateUserState(long playerId)
    {
        var loaded = _playerStore.TryLoad(playerId);
        if (loaded is not null)
        {
            foreach (var discId in _discIdList)
            {
                if (!loaded.Discs.ContainsKey(discId))
                {
                    // A disc added to the masters after this save was written: hand it over at the base level so
                    // the client's disc list matches the masters it just downloaded.
                    loaded.Discs[discId] = new UserDiscState { DiscId = discId, Level = 10, Amount = 99 };
                }
            }
            // a deck slot pointing at a disc that no longer exists in masters_disc.json makes the
            // client throw in PlayerDeckParameter..ctor and the battle never loads: swap it for a valid disc
            foreach (var (deckNumber, deck) in loaded.Decks)
            {
                for (var slot = 0; slot < deck.Count; slot++)
                {
                    if (_discIdList.Contains(deck[slot])) continue;
                    var replacement = _discIdList.FirstOrDefault(id => !deck.Contains(id), _discIdList[0]);
                    _logger.LogWarning("User {PlayerId} deck {Deck} slot {Slot}: disc {DiscId} is not in the masters, replaced with {Replacement}",
                        playerId, deckNumber, slot + 1, deck[slot], replacement);
                    deck[slot] = replacement;
                }
            }
            return loaded;
        }

        var state = NewUserState(playerId);
        SaveUserState(state);
        return state;
    }

    private SessionState NewUserState(long playerId)
    {
        var state = new SessionState { UserId = playerId.ToString() };
        foreach (var discId in _discIdList)
        {
            state.Discs[discId] = new UserDiscState { DiscId = discId, Level = 10, Amount = 99 };
        }
        return state;
    }

    private void SaveUserState(SessionState state, string? uuid = null) => _playerStore.Save(state, uuid);

    // Gym-mode bots use KickerAiParameter row id 100 + kickerId (BattleMatchmakingService.GymAiParameterBase): a copy
    // of the kicker's real row with every motivation at 0, no lock-on and very long skill/dash intervals, so even a
    // client without the Mannequin patch mostly stands still. The row must exist or the bot never gets an AI engine.
    private static string AppendGymAiRows(string aiParamJson)
    {
        try
        {
            var rows = System.Text.Json.Nodes.JsonNode.Parse(aiParamJson) as System.Text.Json.Nodes.JsonArray;
            if (rows is null) return aiParamJson;
            var extra = new List<System.Text.Json.Nodes.JsonNode>();
            foreach (var row in rows)
            {
                if (row is not System.Text.Json.Nodes.JsonObject obj) continue;
                var copy = (System.Text.Json.Nodes.JsonObject)obj.DeepClone();
                copy["id"] = BattleMatchmakingService.GymAiParameterBase + (obj["id"]?.GetValue<int>() ?? 0);
                copy["attackMotivation"] = 0;
                copy["defenseMotivation"] = 0;
                copy["scoreMotivation"] = 0;
                copy["canLockon"] = false;
                foreach (var col in new[] { "attackDashInterval", "defenseDashInterval", "scoreDashInterval", "attackSkillInterval",
                                            "healSkillInterval", "buffSkillInterval", "trapSkillInterval", "warpSkillInterval" })
                {
                    copy[col] = 9999.0;
                }
                extra.Add(copy);
            }
            foreach (var e in extra) rows.Add(e);
            return rows.ToJsonString();
        }
        catch (Exception)
        {
            return aiParamJson;
        }
    }

    // A costume row that belongs to another kicker (hand-edited user file, or a file saved before costume ids were
    // row ids) makes KickerDisplayPresenter.UpdateView work on the wrong kicker's costume; fall back to the kicker's
    // first row (its standard colour).
    private void NormalizeCostume(SessionState state)
    {
        if (_costumeKicker.TryGetValue(state.KickerCostumeId, out var owner) && owner == state.KickerId)
        {
            return;
        }
        if (_costumesByKicker.TryGetValue(state.KickerId, out var rows) && rows.Count > 0)
        {
            _logger.LogInformation("Costume {Costume} does not belong to kicker {Kicker}; using row {Row}", state.KickerCostumeId, state.KickerId, rows[0]);
            state.KickerCostumeId = rows[0];
        }
    }

    private static string LoadJson(string contentRoot, string relativePath, string fallback)
    {
        var resolved = RepositoryPaths.Resolve(relativePath, contentRoot);
        return File.Exists(resolved) ? File.ReadAllText(resolved) : fallback;
    }

    // The client's master getters subtract a fixed anti-tamper offset from these integer columns
    // (SkillMasterData.get_CoolTime = coolTime - 230, DiscMasterData.get_MinHp = minHp - 928, ...), so the served
    // JSON must carry value + offset. Config files hold the human-readable values; the offset is added here.
    private static readonly Dictionary<string, (string field, int offset)[]> ObscuredMasterOffsets = new(StringComparer.Ordinal)
    {
        ["Skill"] = [("coolTime", 0xe6)],
        ["Disc"] = [("minHp", 0x3a0), ("maxHp", 0x2cb), ("minAttack", 0xa7), ("maxAttack", 0x2ad)],
        ["KickerAbility"] = [("overlapCount", 0xcb)],
        ["SpecialSkillHit"] = [("fixedDamage", 0x1c6)],
    };

    private static string ApplyObscuredOffsets(string masterName, string json)
    {
        if (!ObscuredMasterOffsets.TryGetValue(masterName, out var fields)) return json;
        var root = System.Text.Json.Nodes.JsonNode.Parse(json) as System.Text.Json.Nodes.JsonArray;
        if (root == null) return json;
        foreach (var row in root.OfType<System.Text.Json.Nodes.JsonObject>())
        {
            foreach (var (field, offset) in fields)
            {
                if (row[field] is System.Text.Json.Nodes.JsonValue v && v.TryGetValue<double>(out var d))
                    row[field] = (int)Math.Round(d) + offset;
            }
        }
        return root.ToJsonString();
    }

    private static byte[] EncryptMaster(string json) =>
        D2CCodec.Encode(Encoding.UTF8.GetBytes(json), Encoding.ASCII.GetBytes(CommonCode), new byte[16]);

    public async Task<IResult?> TryHandleAsync(HttpContext context)
    {
        context.Response.Headers["x-app-datetime"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
        context.Response.Headers["x-app-master-hash"] = MasterVersion;
        var path = context.Request.Path.Value ?? "/";

        if (HttpMethods.IsGet(context.Request.Method) && path.StartsWith("/demo-master/", StringComparison.Ordinal))
        {
            var masterName = path["/demo-master/".Length..];
            if (_encryptedMasters.TryGetValue(masterName, out var masterBytes))
            {
                return new LocalFixtureResult(masterBytes, "application/octet-stream", StatusCodes.Status200OK);
            }
            return Results.NotFound();
        }

        if (!HttpMethods.IsPost(context.Request.Method)) return null;

        if (path == "/auth/index") return await HandleAuthAsync(context);

        var accessToken = context.Request.Headers["x-app-access-token"].ToString();
        if (string.IsNullOrEmpty(accessToken)) return null;

        // The access token decides whose state this is, and there is deliberately no fallback: the previous
        // behaviour, handing an unrecognised token the most recently issued session key, meant a stale or
        // forged token read and wrote another player's state. A token the store does not know is a rejection.
        if (!_sessions.TryGetValue(accessToken, out var cached))
        {
            var session = _playerStore.FindSession(accessToken);
            if (session is null)
            {
                _logger.LogWarning("Rejecting unknown access token {Token}", accessToken);
                context.Response.StatusCode = StatusCodes.Status401Unauthorized;
                context.Response.Headers["x-app-status-code"] = "1";
                return Results.Empty;
            }
            // Issued before this process started, which is why the player id comes from the session row rather
            // than from anything in memory: that is what makes a client's identity survive a redeploy.
            cached = new CachedSession(session.Key, GetOrCreateUserState(session.PlayerId));
            cached = _sessions.GetOrAdd(accessToken, cached);
        }

        var key = cached.Key;
        var state = cached.State;

        if (path == "/training/index")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("""{"trainingMissionTaskIdList":[]}""", key);
        }

        if (path == "/kicker/change")
        {
            return await HandleKickerChangeAsync(context, state, key);
        }

        if (path == "/disc/change")
        {
            return await HandleDiscChangeAsync(context, state, key);
        }

        if (path == "/disc/buildup")
        {
            return await HandleDiscBuildupAsync(context, state, key);
        }

        if (path == "/gear/create")
        {
            return await HandleGearCreateAsync(context, state, key);
        }

        if (path == "/gear/set")
        {
            return await HandleGearSetAsync(context, state, key);
        }

        if (path == "/gear/destroy")
        {
            return await HandleGearDestroyAsync(context, state, key);
        }

        // Round C: the gacha screens, the goods shop, and the real-money IAP endpoints the shop view also calls.
        if (path.StartsWith("/gacha/", StringComparison.Ordinal))
        {
            var gacha = await TryHandleGachaAsync(path, context, state, key);
            if (gacha is not null) return gacha;
        }

        if (path.StartsWith("/goodsShop/", StringComparison.Ordinal) || path.StartsWith("/shop/", StringComparison.Ordinal))
        {
            var shop = await TryHandleShopAsync(path, context, state, key);
            if (shop is not null) return shop;
        }

        // The name-entry window's submit. This is the only place a name is set on a new account, so it must
        // persist before answering: the client re-issues /startup/index the moment this returns, and that reply
        // has to carry both the name and tutorialProgressStatus = 207 or the home is left inconsistent.
        if (path == "/tutorial/end")
        {
            return await HandleTutorialEndAsync(context, state, key);
        }

        // Every other /tutorial/* step (capsuleOpen, discBuildup, gachaDraw, ...) belongs to the long tutorial
        // the player is never put on - see TutorialStatus - so they stay stubs.
        if (path.StartsWith("/tutorial/", StringComparison.Ordinal))
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("{}", key);
        }

        if (path == "/download/master")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-demo-session";
            context.Response.Headers["x-app-master-hash"] = MasterVersion;
            var json = BuildDownloadMasterJson(context.Request);
            _logger.LogInformation("Serving dynamic master list ({Count} masters)", _encryptedMasters.Count);
            return BinaryJson(json, key);
        }

        if (path == "/startup/index")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-demo-session";
            var json = BuildStartupJson(state, context.Request);
            _logger.LogInformation("Serving dynamic startup index ({KickerCount} kickers, {DiscCount} discs)", _kickerList.Count, _discIdList.Count);
            return BinaryJson(json, key);
        }

        if (path == "/home/index")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-demo-session";
            var json = BuildHomeJson(state);
            _logger.LogInformation("Serving dynamic home index (active kickerId={KickerId}, costumeId={CostumeId}, activeDeck={Deck})", state.KickerId, state.KickerCostumeId, state.ActiveDeckNumber);
            return BinaryJson(json, key);
        }

        if (path == "/battle/entry" || path == "/battle/teamEntry")
        {
            return await HandleBattleEntryAsync(context, state, key);
        }

        if (path == "/battle/start" || path == "/customBattle/start")
        {
            return await HandleBattleStartAsync(context, state, key);
        }

        if (path == "/battle/end" || path == "/customBattle/end")
        {
            return await HandleBattleEndAsync(context, state, key);
        }

        if (path == "/battle/result" || path == "/customBattle/result")
        {
            return await HandleBattleResultAsync(context, state, key);
        }

        if (path == "/battle/cancel" || path == "/battle/teamCancel" || path == "/matching/cancel")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("{}", key);
        }

        if (path == "/battle/good")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("{}", key);
        }

        if (path.StartsWith("/battle/", StringComparison.Ordinal) || path.StartsWith("/customBattle/", StringComparison.Ordinal) || path.StartsWith("/matching/", StringComparison.Ordinal))
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("{}", key);
        }

        if (path == "/ping/index")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("{}", key);
        }

        if (path == "/follow/index")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("""{"userProfileList":[],"mutualFollowCount":0,"followerCount":0,"followingCount":0,"followLimit":100}""", key);
        }

        if (path == "/follow/online")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("{\"userProfileList\":[]}", key);
        }

        if (path == "/user/online")
        {
            context.Response.Headers["x-app-status-code"] = "0";
            return BinaryJson("{}", key);
        }

        // Screens the client opens but this server has no data for (rankings, presents, missions, replays...).
        // They answer with a schema-complete neutral payload so the UI renders instead of showing "Network Error".
        var stub = await TryHandleStubAsync(path, context, state, key);
        if (stub is not null) return stub;

        return null;
    }

    private async Task<IResult?> HandleKickerChangeAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        try
        {
            var plaintext = D2CCodec.Decode(body, key);
            using var document = JsonDocument.Parse(plaintext);
            var root = document.RootElement;
            if (root.TryGetProperty("kickerId", out var kickerProp))
            {
                state.KickerId = kickerProp.GetInt32();
            }
            if (root.TryGetProperty("kickerCostumeId", out var costumeProp))
            {
                state.KickerCostumeId = costumeProp.GetInt32();
            }
            NormalizeCostume(state);

            SaveUserState(state);
            _logger.LogInformation("Session updated: KickerId={KickerId}, CostumeId={CostumeId}", state.KickerId, state.KickerCostumeId);
            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-kicker-change";
            return BinaryJson("{}", key);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode kicker change request: {Error}", ex.Message);
            return null;
        }
    }

    private async Task<IResult?> HandleDiscChangeAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        try
        {
            var plaintext = D2CCodec.Decode(body, key);
            using var document = JsonDocument.Parse(plaintext);
            var root = document.RootElement;
            if (root.TryGetProperty("discDeckNumber", out var deckProp))
            {
                state.ActiveDeckNumber = deckProp.GetInt32();
            }
            if (root.TryGetProperty("userDiscDeckList", out var deckListProp) && deckListProp.ValueKind == JsonValueKind.Array)
            {
                foreach (var deckEl in deckListProp.EnumerateArray())
                {
                    if (deckEl.TryGetProperty("number", out var numProp) &&
                        deckEl.TryGetProperty("discIdList", out var discListProp) &&
                        discListProp.ValueKind == JsonValueKind.Array)
                    {
                        var deckNumber = numProp.GetInt32();
                        var ids = discListProp.EnumerateArray().Select(x => x.GetInt32()).ToList();
                        state.Decks[deckNumber] = ids;
                    }
                }
            }

            SaveUserState(state);
            _logger.LogInformation("Disc deck updated: activeDeck={ActiveDeck}", state.ActiveDeckNumber);
            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-disc-change";
            return BinaryJson("{}", key);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode disc change request: {Error}", ex.Message);
            return null;
        }
    }

    private async Task<IResult?> HandleDiscBuildupAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        try
        {
            var plaintext = D2CCodec.Decode(body, key);
            using var document = JsonDocument.Parse(plaintext);
            var root = document.RootElement;
            var discId = root.GetProperty("discId").GetInt32();
            var targetLevel = root.TryGetProperty("level", out var lvlProp) ? lvlProp.GetInt32() : -1;

            if (!state.Discs.TryGetValue(discId, out var discState))
            {
                discState = new UserDiscState { DiscId = discId, Level = 10, Amount = 99 };
                state.Discs[discId] = discState;
            }

            if (targetLevel > 0)
            {
                discState.Level = targetLevel;
            }
            else
            {
                discState.Level = Math.Min(50, discState.Level + 1);
            }

            state.ItemDiscForce = Math.Max(0, state.ItemDiscForce - 1100);
            SaveUserState(state);

            var resp = new
            {
                userDisc = new
                {
                    discId = discState.DiscId,
                    amount = discState.Amount,
                    level = discState.Level,
                    exp = 0,
                    registerDatetime = "2026-09-01 00:00:00"
                },
                userItem = new
                {
                    itemId = 3,
                    amount = state.ItemDiscForce
                }
            };

            _logger.LogInformation("Disc buildup succeeded: discId={DiscId}, newLevel={Level}", discId, discState.Level);
            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-disc-buildup";
            return BinaryJson(JsonSerializer.Serialize(resp), key);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode disc buildup request: {Error}", ex.Message);
            return null;
        }
    }

    // Slot array of a costume: always three entries, padded from whatever the save file holds (a file from before
    // gear support, or a short hand-edited array, must read as empty slots instead of throwing).
    private static int[] GearSlots(SessionState state, int kickerCostumeId)
    {
        var slots = new int[3];
        if (state.CostumeGears is not null && state.CostumeGears.TryGetValue(kickerCostumeId, out var stored) && stored is not null)
        {
            Array.Copy(stored, slots, Math.Min(stored.Length, slots.Length));
        }
        return slots;
    }

    // The one error shape this server uses: any non-zero x-app-status-code aborts the client flow and it shows the
    // generic error toast for that screen. The body stays schema-shaped so nothing is left half-deserialized.
    private static LocalFixtureResult StatusError(HttpContext context, byte[] key)
    {
        context.Response.Headers["x-app-status-code"] = "1";
        return BinaryJson("{}", key);
    }

    // gear/create: retail rolls a random gear for the requested kicker and hands the id back; the player then either
    // equips it (gear/set) or discards it (gear/destroy), both of which clear the pending roll.
    private async Task<IResult?> HandleGearCreateAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        var kickerId = state.KickerId;
        try
        {
            if (body.Length > 0)
            {
                var plaintext = D2CCodec.Decode(body, key);
                using var document = JsonDocument.Parse(plaintext);
                if (document.RootElement.TryGetProperty("kickerId", out var kickerProp))
                {
                    kickerId = kickerProp.GetInt32();
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode gear create request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        if (_gearIdList.Count == 0 || _kickerList.All(k => k.Id != kickerId))
        {
            _logger.LogWarning("Rejected gear/create for unknown kicker {KickerId} ({GearCount} gears in master)", kickerId, _gearIdList.Count);
            return StatusError(context, key);
        }

        var gearId = _gearIdList[Random.Shared.Next(_gearIdList.Count)];
        state.PendingGear = new PendingGearState { KickerId = kickerId, GearId = gearId };
        SaveUserState(state);

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-gear-create";
        _logger.LogInformation("Rolled gear {GearId} for kicker {KickerId} (user {UserId})", gearId, kickerId, state.UserId);
        return BinaryJson($"{{\"gearId\":{gearId}}}", key);
    }

    private async Task<IResult?> HandleGearSetAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        try
        {
            var plaintext = D2CCodec.Decode(body, key);
            using var document = JsonDocument.Parse(plaintext);
            var root = document.RootElement;
            var costumeId = root.TryGetProperty("kickerCostumeId", out var costumeProp) ? costumeProp.GetInt32() : 0;
            var slotNumber = root.TryGetProperty("gearIdNumber", out var slotProp) ? slotProp.GetInt32() : 0;

            var gearId = state.PendingGear?.GearId ?? 0;
            if (slotNumber is < 1 or > 3 || !_costumeKicker.ContainsKey(costumeId) || !_gearIdList.Contains(gearId))
            {
                _logger.LogWarning("Rejected gear/set: costume={CostumeId} slot={Slot} pendingGear={GearId}", costumeId, slotNumber, gearId);
                return StatusError(context, key);
            }

            if (!state.CostumeGears.TryGetValue(costumeId, out var slots))
            {
                slots = new int[3];
                state.CostumeGears[costumeId] = slots;
            }
            else if (slots.Length < 3)
            {
                Array.Resize(ref slots, 3);
                state.CostumeGears[costumeId] = slots;
            }
            slots[slotNumber - 1] = gearId;
            state.PendingGear = new PendingGearState();
            SaveUserState(state);

            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-gear-set";
            _logger.LogInformation("Equipped gear {GearId} in slot {Slot} of costume {CostumeId} (user {UserId})", gearId, slotNumber, costumeId, state.UserId);
            return BinaryJson("{}", key);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode gear set request: {Error}", ex.Message);
            return StatusError(context, key);
        }
    }

    private Task<IResult?> HandleGearDestroyAsync(HttpContext context, SessionState state, byte[] key)
    {
        state.PendingGear = new PendingGearState();
        SaveUserState(state);

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-gear-destroy";
        _logger.LogInformation("Discarded the pending gear of user {UserId}", state.UserId);
        return Task.FromResult<IResult?>(BinaryJson("{}", key));
    }

    private string BuildStartupJson(SessionState state, HttpRequest request)
    {
        NormalizeCostume(state);
        var pendingGear = state.PendingGear ?? new PendingGearState();
        var userKickerList = _kickerList.Select(k =>
        {
            var costumes = _costumesByKicker.GetValueOrDefault(k.Id, [1]);
            var selectedCostume = k.Id == state.KickerId ? state.KickerCostumeId : costumes[0];
            return new
            {
                kickerId = k.Id,
                kickerCostumeId = selectedCostume,
                userKickerCostumeList = costumes.Select(c =>
                {
                    var slots = GearSlots(state, c);
                    return new
                    {
                        kickerCostumeId = c,
                        gearId1 = slots[0],
                        gearId2 = slots[1],
                        gearId3 = slots[2]
                    };
                }).ToArray()
            };
        }).ToArray();

        var kickerTrainingList = _kickerList.Select(k => new
        {
            kickerId = k.Id,
            clearTrainingMissionTaskCount = 0
        }).ToArray();

        var userDiscList = _discIdList.Select(discId =>
        {
            var dState = state.Discs.GetValueOrDefault(discId) ?? new UserDiscState { DiscId = discId, Level = 10, Amount = 99 };
            return new
            {
                discId = dState.DiscId,
                amount = dState.Amount,
                level = dState.Level,
                exp = 0,
                registerDatetime = "2026-09-01 00:00:00"
            };
        }).ToArray();

        var data = new
        {
            userKickerList,
            userDiscList,
            userHonorList = new[] { new { honorId = 6010000, newFlag = false } },
            // All 8 Item master rows: 1-4 the legacy counters, 5-8 the round C stocks (gear stamps, disc fragments
            // and the two gacha tickets) that the gear screen and the shop read their counters from.
            userItemList = BuildUserItemList(state),
            // The client reads userGear.gearId != 0 as "there is a rolled gear waiting for equip/discard", and
            // userGear.kickerId as whose it is; with nothing pending it keeps pointing at the active kicker.
            userGear = new
            {
                kickerId = pendingGear.GearId != 0 ? pendingGear.KickerId : state.KickerId,
                gearId = pendingGear.GearId
            },
            userStampList = Array.Empty<object>(),
            userMissionProgressList = Array.Empty<object>(),
            userDailyRandomMissionTaskList = Array.Empty<object>(),
            kickerTrainingList,
            userPremium = new { premiumId = 0, startDatetime = "", endDatetime = "" },
            userSeasonPass = new { seasonPassId = 1, startDatetime = "2019-01-01 00:00:00", endDatetime = "2030-01-01 23:59:59" },
            userFestivalTeam = new { battleRuleId = 5, festivalTeamId = 1, festivalPoint = 0 },
            tutorialProgressStatus = TutorialStatus(state),
            birthdayConfirmFlag = true,
            dataUsageAgreementConfirmFlag = true,
            dataUsageAgreementAvailableFlag = false,
            userDataUsageAgreementList = Array.Empty<object>(),
            birthdayRegistrationFlag = true,
            purchaseAlertFlag = false,
            connectionSnsList = Array.Empty<object>(),
            connectionPlatformFlag = false,
            photonCloudRegionList = new[]
            {
                new { id = 1, code = "jp", appId = "local-demo-app" }
            },
            matchmakingFrontend = new { host = request.Host.Host, port = 18081 },
            battleTeamPhotonCloudRegionIdList = new[] { 1 },
            interruptNotificationList = Array.Empty<object>(),
            teamBattleInvitationCustomToken = "",
            teamBattleInvitationId = "",
            chatRoomConnectionCustomToken = "",
            chatRoomConnectionId = "",
            officialUrl = ""
        };

        return JsonSerializer.Serialize(data);
    }

    private string BuildHomeJson(SessionState state)
    {
        NormalizeCostume(state);

        var userPlayer = new
        {
            userId = state.UserId,
            displayUserId = int.TryParse(state.UserId, out var uid) ? uid : 1000001,
            name = CurrentUserName(state),
            exp = 38500,
            honorId = 6010000,
            userFrameList = new[]
            {
                new { battleRuleType = 1, frameId = 1 },
                new { battleRuleType = 2, frameId = 1 },
                new { battleRuleType = 3, frameId = 1 }
            },
            lastLoginDatetime = "2026-09-03 00:00:00",
            lastNameUpdateDatetime = "2026-09-03 00:00:00",
            kickerId = state.KickerId,
            kickerCostumeId = state.KickerCostumeId,
            discDeckNumber = state.ActiveDeckNumber,
            officialFlag = false
        };

        var userDiscDeckList = state.Decks.Select(d => new
        {
            number = d.Key,
            discIdList = d.Value.ToArray()
        }).ToArray();

        var data = new
        {
            userPlayer,
            userDiscDeckList,
            userCapsuleList = new[]
            {
                new
                {
                    slotNumber = 1,
                    capsuleId = 5010001,
                    completeDatetime = "2026-10-01 00:00:00",
                    openTimeSecond = 3600
                }
            },
            // The shop's disc/kicker scrollers (Colorful.ShopDiscScroller._data : List<GachaGroupInfo>) are filled
            // from these two lists through GachaGroupListInfo(ResponseGachaGroup[]); serving them empty left the
            // scroller with a data list shorter than the cell range EnhancedScroller._Resize walks and GetCellHeight
            // threw ArgumentOutOfRangeException (List<T>.get_Item).
            discGachaGroupList = BuildHomeGachaGroupList(DiscGachaGroupId),
            kickerGachaGroupList = BuildHomeGachaGroupList(KickerGachaGroupId),
            userBattleRankList = BuildBattleRankList(state),
            userMissionProgressList = Array.Empty<object>(),
            // shopProductList is the real-money IAP list, which this server does not sell; the goods shop is the
            // JetCoin one and is served in full.
            shopProductList = Array.Empty<object>(),
            goodsShopProductList = BuildGoodsShopProducts(),
            // The exchange tab's own scroller (ShopExchangeScroller) stays empty: no disc fragments are converted.
            discFragmentConversionDiscIdList = Array.Empty<int>(),
            userMissionTaskStatusNotification = new { newFlagCount = 0, completionCount = 0 },
            presentNotificationCount = 0,
            appInformationNotificationFlag = false,
            newFollowerNotificationFlag = false,
            appMovieNotificationCount = 0,
            userBattleBreakaway = new { breakawayCount = 0 },
            mutualFollowBattleId = 0,
            mutualFollowBattleEndDatetime = "",
            mutualFollowBattleRewardCompleteCount = 0,
            userBattleReplayNotificationList = Array.Empty<object>(),
            seasonMatchBattleRankResetNotificationFlag = false,
            seasonMatchResultNotification = (object?)null,
            festivalMatchTeamSelectionNotificationFlag = false,
            festivalMatchResultNotification = (object?)null,
            appFestivalMatchResult = (object?)null,
            photonReconnectWaitTimeList = new[] { 0.5, 1.0, 2.0 },
            battleStartWaitTime = 0.0,
            battlePlayablePingThreshold = 1000,
            battleRetryPingThreshold = 1000,
            battleRetryPingMaxCount = 0,
            battleTeamPhotonCloudRegionIdList = new[] { 1 },
            teamBattleCampaign = (object?)null,
            userTeamBattleCampaignList = Array.Empty<object>(),
            userNoticeList = Array.Empty<object>()
        };

        return JsonSerializer.Serialize(data);
    }

    private string BuildDownloadMasterJson(HttpRequest request)
    {
        var host = request.Host;
        var scheme = request.Scheme;
        return JsonSerializer.Serialize(new
        {
            masterDownloadList = _encryptedMasters.Select(kvp => new
            {
                name = kvp.Key,
                hash = Convert.ToHexString(SHA256.HashData(kvp.Value)).ToLowerInvariant(),
                url = $"{scheme}://{host}/demo-master/{kvp.Key}",
                size = kvp.Value.Length
            }).ToArray()
        });
    }

    private async Task<IResult?> HandleAuthAsync(HttpContext context)
    {
        var requestBody = await ReadBodyAsync(context.Request);
        try
        {
            var plaintext = D2CCodec.Decode(requestBody, Encoding.ASCII.GetBytes(CommonCode));
            using var document = JsonDocument.Parse(plaintext);
            var root = document.RootElement;
            var hash = root.GetProperty("hash").GetString();
            if (hash is null || Encoding.ASCII.GetByteCount(hash) != D2CCodec.KeySizeBytes) return null;

            var uuid = root.TryGetProperty("uuid", out var uuidProp) ? uuidProp.GetString() ?? "default-user" : "default-user";

            // The device uuid's player, created on first contact and the same one forever after. This is what
            // used to be an in-memory counter, which re-issued 1000002 to whichever device authenticated first
            // after a restart.
            var playerId = _playerStore.ResolvePlayerId(uuid);
            var state = GetOrCreateUserState(playerId);

            // No name is invented here. An empty name is what puts the client on the name-entry window; a
            // name is only ever set by the player, through POST /tutorial/end.

            var key = Encoding.ASCII.GetBytes(hash);
            var sessionToken = $"demo-token-{playerId}-{Guid.NewGuid():N}";
            _sessions[sessionToken] = new CachedSession(key, state);
            _sessions[AccessToken] = new CachedSession(key, state);
            _playerStore.SaveSession(sessionToken, playerId, key);
            _playerStore.SaveSession(AccessToken, playerId, key);

            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-app-user-id"] = playerId.ToString();
            context.Response.Headers["x-app-access-token"] = sessionToken;
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-demo-auth";
            context.Response.Headers["x-app-datetime"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
            _logger.LogInformation("Created session for player {PlayerId} (name {UserName:l}) with token {Token}",
                playerId, state.HasName ? state.UserName : "<unset>", sessionToken);
            return BinaryJson("{}", key);
        }
        catch (Exception exception) when (exception is CryptographicException or JsonException or ArgumentException)
        {
            _logger.LogWarning("Could not decode local demo authentication request: {Error}", exception.Message);
            return null;
        }
    }

    // The name-entry window's submit, and the only place a new account gets a name. It persists before
    // answering because the client re-issues /startup/index the moment this returns, and that reply has to carry
    // both the name and tutorialProgressStatus = 207 or the home is left inconsistent.
    //
    // TutorialEndRequestData carries the name in a field spelled "name"; "userName" is accepted too, for the same
    // reason /user/change accepts both.
    private async Task<IResult?> HandleTutorialEndAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        string name;
        try
        {
            var plaintext = D2CCodec.Decode(body, key);
            using var document = JsonDocument.Parse(plaintext);
            name = TryGetString(document.RootElement, "name", out var decoded) || TryGetString(document.RootElement, "userName", out decoded)
                ? decoded.Trim()
                : "";
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode tutorial end request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        var rejection = NameRejection(state, name);
        if (rejection is not null)
        {
            _logger.LogInformation("Rejected the name submitted by player {PlayerId}: {Reason} ({Length} code units)",
                state.PlayerId, rejection, name.Length);
            return NameRejected(context, key, rejection);
        }

        state.UserName = name;
        SaveUserState(state);
        _logger.LogInformation("Player {PlayerId} chose the name {UserName:l}", state.PlayerId, name);
        return OkJson(context, key, "{}");
    }

    // The client caps typing at 10 UTF-16 code units and truncates with Substring(0, 10) on end-edit, so 10 is the
    // limit here too: the server must never reject a name the client let the player type. Surrogates and the
    // zero-width joiner would let a name render as something other than what it compares as, and a control
    // character would break the single line the name is drawn on.
    private const int NameMaxLength = 10;

    private string? NameRejection(SessionState state, string name)
    {
        if (name.Length == 0) return "empty";
        if (name.Length > NameMaxLength) return "too-long";
        if (name.Any(char.IsSurrogate)) return "surrogate";
        if (name.Contains('‍')) return "zero-width-joiner";
        if (name.Any(char.IsControl)) return "control-character";
        if (_playerStore.IsNameTaken(name, state.PlayerId)) return "taken";
        return null;
    }

    // A rejection is HTTP 200 carrying a non-zero x-app-status-code: the code, not the HTTP status, is what the
    // client reads as the failure signal. Only 2005 opens its name-rule popup - the canned text lives in the
    // prefab, so it explains the rules it knows and cannot be reworded from here - while 2002/2003/2004 fall
    // through to the generic error dialog. The body stays schema-shaped so nothing comes out half-deserialized.
    private static LocalFixtureResult NameRejected(HttpContext context, byte[] key, string reason)
    {
        context.Response.Headers["x-app-status-code"] = "2005";
        var body = JsonSerializer.Serialize(new
        {
            error = new
            {
                code = "2005",
                title = "Nombre no valido",
                message = reason switch
                {
                    "empty" => "Escribe un nombre.",
                    "too-long" => $"El nombre no puede pasar de {NameMaxLength} caracteres.",
                    "taken" => "Ese nombre ya lo usa otro jugador.",
                    _ => "Ese nombre no se puede usar."
                }
            }
        });
        return BinaryJson(body, key);
    }

    private async Task<IResult?> HandleBattleEntryAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        int battleRuleId = 1;
        try
        {
            if (body.Length > 16)
            {
                var plaintext = D2CCodec.Decode(body, key);
                using var document = JsonDocument.Parse(plaintext);
                if (document.RootElement.TryGetProperty("battleRuleId", out var ruleProp))
                {
                    battleRuleId = ruleProp.GetInt32();
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Failed to parse battle entry body: {Error}, using rule 1", ex.Message);
        }

        var deck = state.Decks.GetValueOrDefault(state.ActiveDeckNumber) ?? [3010001, 3010002, 3010003, 3010004];
        NormalizeCostume(state);
        var (battleEntryId, ticketId) = _matchmaking.RegisterEntry(
            state.UserId, state.UserName, state.KickerId, state.KickerCostumeId, battleRuleId, deck);

        var resp = new
        {
            battleEntryTicketId = ticketId,
            matchmakingCancelWaitingTimeSecond = 5,
            campaignList = Array.Empty<object>(),
            scf = false
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-battle-entry";
        _logger.LogInformation("Handled /battle/entry for {UserId}: ticket={TicketId}", state.UserId, ticketId);
        return BinaryJson(JsonSerializer.Serialize(resp), key);
    }

    private async Task<IResult?> HandleBattleStartAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        var battleRuleId = 1;
        var battleRuleType = 1;
        var battleId = "";
        try
        {
            if (body.Length > 16)
            {
                var plaintext = D2CCodec.Decode(body, key);
                using var document = JsonDocument.Parse(plaintext);
                if (document.RootElement.TryGetProperty("battleRuleId", out var ruleProp))
                {
                    battleRuleId = ruleProp.GetInt32();
                }
                if (document.RootElement.TryGetProperty("battleId", out var battleProp) && battleProp.ValueKind == JsonValueKind.String)
                {
                    battleId = battleProp.GetString() ?? "";
                }
            }
            if (!_battleRuleTypeById.TryGetValue(battleRuleId, out battleRuleType)) battleRuleType = 1;
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Failed to parse battle start body: {Error}, using rule 1", ex.Message);
            battleRuleId = 1;
            battleRuleType = 1;
        }

        // GuardianParameterMaster is looked up by the id returned here (CallbackBattleStartSuccess), so a rule
        // whose guardian is the revivable ball-goal variant (battleRuleType 3) gets the weaker row 2.
        // Gym: row 3 = same HP, attack 0, so the guardian's eye laser cannot hurt anyone.
        var guardianId = BattleMatchmakingService.GymEnabled ? 3 : battleRuleType == 3 ? 2 : 1;
        // The arena: the room's draw (same for every human in it) or a fresh draw when the room is unknown.
        var fieldId = _matchmaking.GetRoomFieldId(battleId) ?? BattleMatchmakingService.PickRandomField();
        var resp = new
        {
            fieldId,
            guardianParameter = new
            {
                id = guardianId,
                rank = 1
            },
            lotteryFestivalPointId = 0
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-battle-start";
        _logger.LogInformation("Handled /battle/start for {UserId}: rule={RuleId} type={RuleType} guardianParameter={GuardianId} field={FieldId}",
            state.UserId, battleRuleId, battleRuleType, guardianId, fieldId);
        return BinaryJson(JsonSerializer.Serialize(resp), key);
    }

    // Colorful.Networking.BattleResultResponseData: every list must be present (empty is fine); the client
    // constructs BattleResultInfo from it unconditionally and NREs on a missing array, which leaves the
    // ResultScene stuck on the score board.
    //
    // Rank is real here: the battle's outcome is applied to the player's persisted standing, so
    // beforeUserBattleRank and userBattleRank differ and the result screen animates a change. Caveat: the
    // outcome is not read out of the request yet - the body's shape was never decoded - so every completed
    // battle is scored as a win, which matches what this handler already did with its rewards.
    private Task<IResult?> HandleBattleResultAsync(HttpContext context, SessionState state, byte[] key)
    {
        var before = _playerStore.LoadRank(state.PlayerId, RegularBattleRuleType);
        var after = RankProgression.Apply(before, won: true);
        _playerStore.SaveRank(state.PlayerId, RegularBattleRuleType, after);

        var rank = new { battleRuleType = RegularBattleRuleType, battlePoint = after.BattlePoint, rank = after.Rank };
        var resp = new
        {
            userExp = 38500 + 800, // the user's total exp (see the static exp served at startup) plus this battle's reward
            userBattleRank = rank,
            beforeUserBattleRank = new { battleRuleType = RegularBattleRuleType, battlePoint = before.BattlePoint, rank = before.Rank },
            playerLevelUpRewardList = Array.Empty<object>(),
            receivedUserCapsuleList = Array.Empty<object>(),
            receivedUserItemList = Array.Empty<object>(),
            receivedUserPresentList = Array.Empty<object>(),
            userMissionProgressList = Array.Empty<object>(),
            userDailyRandomMissionTaskList = Array.Empty<object>(),
            receivedRewardList = Array.Empty<object>(),
            badConnectionReliefFlag = false,
            battleCount = 1,
            battleWinCount = 0,
            matchmakingTeamId = "team-1",
            campaignList = Array.Empty<object>(),
            userFestivalTeam = new { battleRuleId = 1, festivalTeamId = 0, festivalPoint = 0 },
            festivalPoint = 0,
            lotteryFestivalPointId = 0
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-battle-result";
        _logger.LogInformation("Handled /battle/result for {UserId}", state.UserId);
        return Task.FromResult<IResult?>(BinaryJson(JsonSerializer.Serialize(resp), key));
    }

    private Task<IResult?> HandleBattleEndAsync(HttpContext context, SessionState state, byte[] key)
    {
        state.ItemKickPoints += 200;
        state.ItemJetCoins += 1000;
        SaveUserState(state);

        var resp = new
        {
            replayUploadFlag = false,
            // The same delta /battle/result persisted, so the reward screen and the stored rank agree.
            battlePoint = RankProgression.WinBattlePoint,
            exp = 800,
            kickPoint = 200,
            jetCoin = 1000
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-battle-end";
        _logger.LogInformation("Handled /battle/end for {UserId}", state.UserId);
        return Task.FromResult<IResult?>(BinaryJson(JsonSerializer.Serialize(resp), key));
    }

    private static LocalFixtureResult BinaryJson(string json, byte[] key) =>
        new(D2CCodec.Encode(Encoding.UTF8.GetBytes(json), key, RandomNumberGenerator.GetBytes(D2CCodec.VectorSizeBytes)),
            "application/octet-stream", StatusCodes.Status200OK);

    private static async Task<byte[]> ReadBodyAsync(HttpRequest request)
    {
        request.EnableBuffering();
        request.Body.Position = 0;
        using var stream = new MemoryStream();
        await request.Body.CopyToAsync(stream, request.HttpContext.RequestAborted);
        request.Body.Position = 0;
        return stream.ToArray();
    }

    private sealed record KickerInfo(int Id, string Name);
}
