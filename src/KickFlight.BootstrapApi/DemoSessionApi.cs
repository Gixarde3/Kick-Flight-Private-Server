using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace KickFlight.BootstrapApi;

public sealed class DemoSessionApi
{
    private const string CommonCode = "1a837b9ee2ae11a07a0f529a4cd4b61c";
    // The client keeps its downloaded masters until this header changes, so it must follow the content:
    // a SHA-256 over every served table (see the end of the constructor). Editing any config/masters_*.json
    // and restarting the server therefore makes the client re-download on its next launch.
    public string MasterVersion { get; private set; } = "demo-master-v27";
    private const string AccessToken = "demo-access-token-0000000000000000000000000000";

    public sealed class SessionState
    {
        public string UserId { get; set; } = "1000001";
        public string UserName { get; set; } = "Gixarde3";
        public int KickerId { get; set; } = 1;
        public int KickerCostumeId { get; set; } = 1;
        public int ActiveDeckNumber { get; set; } = 1;
        public Dictionary<int, List<int>> Decks { get; set; } = new()
        {
            [1] = [3010001, 3010002, 3010003, 3010004],
            [2] = [3010005, 3010006, 3010007, 3010008],
            [3] = [3010009, 3010010, 3010011, 3010012],
            [4] = [3010013, 3010014, 3010020, 3010022],
            [5] = [3010023, 3010024, 3010029, 3010030]
        };
        public Dictionary<int, UserDiscState> Discs { get; set; } = new();
        public int ItemJetCoins { get; set; } = 208754;
        public int ItemPaidJetCoins { get; set; } = 10000;
        public int ItemDiscForce { get; set; } = 999999;
        public int ItemKickPoints { get; set; } = 50000;
    }

    public sealed class UserDiscState
    {
        public int DiscId { get; set; }
        public int Level { get; set; } = 10;
        public int Amount { get; set; } = 99;
    }

    private readonly string _contentRoot;
    private readonly ConcurrentDictionary<string, byte[]> _keysByAccessToken = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, SessionState> _sessionStateByToken = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, string> _userIdByUuid = new(StringComparer.Ordinal);
    private int _userCounter = 1000000;
    private readonly Dictionary<string, byte[]> _encryptedMasters = new(StringComparer.Ordinal);
    private readonly List<KickerInfo> _kickerList = [];
    private readonly Dictionary<int, List<int>> _costumesByKicker = [];
    private readonly List<int> _discIdList = [];
    private readonly ILogger<DemoSessionApi> _logger;
    private readonly BattleMatchmakingService _matchmaking;

    public DemoSessionApi(ILogger<DemoSessionApi> logger, IWebHostEnvironment environment, BattleMatchmakingService matchmaking)
    {
        _logger = logger;
        _matchmaking = matchmaking;
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
                var costumeId = el.TryGetProperty("costumeId", out var cProp) ? cProp.GetInt32() : el.GetProperty("id").GetInt32();
                if (!_costumesByKicker.TryGetValue(kickerId, out var cList))
                {
                    cList = [];
                    _costumesByKicker[kickerId] = cList;
                }
                cList.Add(costumeId);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error parsing master json definitions: {Error}", ex.Message);
        }

        if (_kickerList.Count == 0)
        {
            _kickerList.Add(new KickerInfo(1, "Tsubame"));
            _costumesByKicker[1] = [1];
        }

        _encryptedMasters["Kicker"] = EncryptMaster(kickerJson);
        _encryptedMasters["KickerCostume"] = EncryptMaster(costumeJson);
        _encryptedMasters["KickerDetail"] = EncryptMaster(detailJson);
        _encryptedMasters["KickerParameter"] = EncryptMaster(parameterJson);
        _encryptedMasters["KickerAbility"] = EncryptMaster(ApplyObscuredOffsets("KickerAbility", abilityJson));
        _encryptedMasters["KickerAbilityCondition"] = EncryptMaster(abilityConditionJson);
        _encryptedMasters["Translation"] = EncryptMaster(translationJson);

        _encryptedMasters["Field"] = EncryptMaster("""[{"id":99999,"name":"FLD99999","minimapId":99999,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0},{"id":101,"name":"FLD00101","minimapId":101,"minimapSizeX":100,"minimapSizeY":100,"itemPostionMasterId":0}]""");
        _encryptedMasters["GuardianParameter"] = EncryptMaster("""[{"id":1,"matchType":1,"rank":1,"hp":10000,"attack":1000}]""");
        _encryptedMasters["BattleRule"] = EncryptMaster("""
            [
              {"id":1,"name":"Cristalmanía","seasonName":"Temporada 1","festivalName":"","matchType":1,"battleRuleType":1,"regularMatchFlag":true,"guardianAmount":0,"crystalAmount":50,"flagAmount":0,"generalAmount":0,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"},
              {"id":2,"name":"Vuelo de banderas","seasonName":"Temporada 1","festivalName":"","matchType":1,"battleRuleType":2,"regularMatchFlag":true,"guardianAmount":0,"crystalAmount":0,"flagAmount":3,"generalAmount":0,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"},
              {"id":3,"name":"Bola rápida","seasonName":"Temporada 1","festivalName":"","matchType":1,"battleRuleType":3,"regularMatchFlag":true,"guardianAmount":0,"crystalAmount":0,"flagAmount":0,"generalAmount":1,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"},
              {"id":4,"name":"Bola rápida","seasonName":"","festivalName":"","matchType":2,"battleRuleType":3,"regularMatchFlag":false,"guardianAmount":0,"crystalAmount":0,"flagAmount":0,"generalAmount":1,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2030-01-01 23:59:59"},
              {"id":5,"name":"Cristalmanía","seasonName":"Temporada 1","festivalName":"","matchType":3,"battleRuleType":1,"regularMatchFlag":false,"guardianAmount":0,"crystalAmount":50,"flagAmount":0,"generalAmount":0,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2020-01-01 00:00:00"},
              {"id":6,"name":"Festival Kick-Flight","seasonName":"","festivalName":"Festival Kick-Flight","matchType":4,"battleRuleType":1,"regularMatchFlag":false,"guardianAmount":0,"crystalAmount":50,"flagAmount":0,"generalAmount":0,"minimapVisibleType":1,"battleTimeSecond":180,"startDatetime":"2019-01-01 00:00:00","endDatetime":"2020-01-01 00:00:00"}
            ]
            """);
        _encryptedMasters["BattleRuleField"] = EncryptMaster("""[{"id":1,"battleRuleId":1,"fieldId":101,"ratio":100},{"id":2,"battleRuleId":2,"fieldId":101,"ratio":100},{"id":3,"battleRuleId":3,"fieldId":101,"ratio":100},{"id":4,"battleRuleId":4,"fieldId":101,"ratio":100},{"id":5,"battleRuleId":5,"fieldId":101,"ratio":100},{"id":6,"battleRuleId":6,"fieldId":101,"ratio":100}]""");
        _encryptedMasters["RegularMatchBattleSchedule"] = EncryptMaster("""
            [
              {"id":1,"seasonMatchBattleRuleType":3,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":1,"sortOrder":1},
              {"id":2,"seasonMatchBattleRuleType":3,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":2,"sortOrder":2},
              {"id":3,"seasonMatchBattleRuleType":3,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":3,"sortOrder":3},
              {"id":4,"seasonMatchBattleRuleType":-1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":1,"sortOrder":1},
              {"id":5,"seasonMatchBattleRuleType":-1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":2,"sortOrder":2},
              {"id":6,"seasonMatchBattleRuleType":-1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":3,"sortOrder":3}
            ]
            """);
        _encryptedMasters["RankerMatchBattleSchedule"] = EncryptMaster("""
            [
              {"id":1,"seasonMatchBattleRuleType":1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":4,"sortOrder":1},
              {"id":2,"seasonMatchBattleRuleType":2,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":4,"sortOrder":1},
              {"id":3,"seasonMatchBattleRuleType":3,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":4,"sortOrder":1},
              {"id":4,"seasonMatchBattleRuleType":-1,"groupId":1,"startTime":"00:00:00","endTime":"23:59:59","battleRuleId":4,"sortOrder":1}
            ]
            """);
        _encryptedMasters["BattleRank"] = EncryptMaster("""
            [
              {"id":1,"name":"D","rank":0,"regularMatchFlag":true,"totalBattlePoint":0,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":2,"name":"C","rank":1,"regularMatchFlag":true,"totalBattlePoint":200,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":3,"name":"B","rank":2,"regularMatchFlag":true,"totalBattlePoint":500,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":4,"name":"A","rank":3,"regularMatchFlag":true,"totalBattlePoint":900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":5,"name":"S","rank":4,"regularMatchFlag":false,"totalBattlePoint":1400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":6,"name":"S⁺1","rank":5,"regularMatchFlag":false,"totalBattlePoint":1900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":7,"name":"S⁺2","rank":6,"regularMatchFlag":false,"totalBattlePoint":2400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":8,"name":"S⁺3","rank":7,"regularMatchFlag":false,"totalBattlePoint":2900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":9,"name":"S⁺4","rank":8,"regularMatchFlag":false,"totalBattlePoint":3400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":10,"name":"S⁺5","rank":9,"regularMatchFlag":false,"totalBattlePoint":3900,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":11,"name":"S⁺6","rank":10,"regularMatchFlag":false,"totalBattlePoint":4400,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":12,"name":"S⁺7","rank":11,"regularMatchFlag":false,"totalBattlePoint":5000,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false},
              {"id":13,"name":"S⁺6","rank":13,"regularMatchFlag":false,"totalBattlePoint":4877,"winBattlePointCoefficient":1.0,"loseBattlePointCoefficient":1.0,"demontioableFlag":false}
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
                            if (p == 1) bone = kwt == 4 ? "Prop_Common" : "Prop_R";      // a Drone hovers from the body
                            else if (p == 2) bone = "Prop_L";
                            else if (p == 201 && kwt == 11) bone = "wp_010_001_Grip_L";  // Nunchaku free stick hangs off the handle's Grip_L locator
                            else continue;
                            var attach = 1;
                            weaponList.Add(new { id = weaponId++, kickerId = k, modelId = m, propId = p, boneName = bone, rootName = "", attachType = attach });
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
        _encryptedMasters["Item"] = EncryptMaster("""
            [
              {"id":1,"goodsType":101,"name":"JetCoin","maxAmount":9999999},
              {"id":2,"goodsType":102,"name":"PaidJetCoin","maxAmount":9999999},
              {"id":3,"goodsType":302,"name":"DiscForce","maxAmount":9999999},
              {"id":4,"goodsType":701,"name":"KickPoint","maxAmount":9999999}
            ]
            """);

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

        _encryptedMasters["KickerAiParameter"] = EncryptMaster(aiParamJson);
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

        _encryptedMasters["BattleRuleScramble"] = EncryptMaster("""
            [
              {"id":1,"battleRuleId":1,"crystalDepositSpeedCoefficient":1.0},
              {"id":2,"battleRuleId":5,"crystalDepositSpeedCoefficient":1.0},
              {"id":3,"battleRuleId":6,"crystalDepositSpeedCoefficient":1.0}
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
        _encryptedMasters["TutorialKickerAi"] = EncryptMaster("[]");

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

    private SessionState GetOrCreateUserState(string userId)
    {
        var usersDir = Path.Combine(_contentRoot, "data", "users");
        Directory.CreateDirectory(usersDir);
        var userFile = Path.Combine(usersDir, $"{userId}.json");

        if (File.Exists(userFile))
        {
            try
            {
                var json = File.ReadAllText(userFile);
                var loaded = JsonSerializer.Deserialize<SessionState>(json);
                if (loaded != null)
                {
                    loaded.UserId = userId;
                    foreach (var discId in _discIdList)
                    {
                        if (!loaded.Discs.ContainsKey(discId))
                        {
                            loaded.Discs[discId] = new UserDiscState { DiscId = discId, Level = 10, Amount = 99 };
                        }
                    }
                    return loaded;
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning("Error loading user state for {UserId}: {Error}", userId, ex.Message);
            }
        }

        var state = new SessionState { UserId = userId };
        foreach (var discId in _discIdList)
        {
            state.Discs[discId] = new UserDiscState { DiscId = discId, Level = 10, Amount = 99 };
        }
        SaveUserState(state);
        return state;
    }

    private void SaveUserState(SessionState state)
    {
        try
        {
            var usersDir = Path.Combine(_contentRoot, "data", "users");
            Directory.CreateDirectory(usersDir);
            var userFile = Path.Combine(usersDir, $"{state.UserId}.json");
            var json = JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(userFile, json);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error saving user state for {UserId}: {Error}", state.UserId, ex.Message);
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

        if (!_keysByAccessToken.TryGetValue(accessToken, out var key))
        {
            if (_keysByAccessToken.Count > 0)
            {
                key = _keysByAccessToken.Values.Last();
            }
            else
            {
                key = Encoding.ASCII.GetBytes(CommonCode);
            }
        }

        var state = _sessionStateByToken.GetOrAdd(accessToken, _ => GetOrCreateUserState("default-user"));

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
            else if (_costumesByKicker.TryGetValue(state.KickerId, out var defaultCostumes) && defaultCostumes.Count > 0)
            {
                state.KickerCostumeId = defaultCostumes[0];
            }

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

    private string BuildStartupJson(SessionState state, HttpRequest request)
    {
        var userKickerList = _kickerList.Select(k =>
        {
            var costumes = _costumesByKicker.GetValueOrDefault(k.Id, [1]);
            var selectedCostume = k.Id == state.KickerId ? state.KickerCostumeId : costumes[0];
            return new
            {
                kickerId = k.Id,
                kickerCostumeId = selectedCostume,
                userKickerCostumeList = costumes.Select(c => new
                {
                    kickerCostumeId = c,
                    gearId1 = 0,
                    gearId2 = 0,
                    gearId3 = 0
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
            userItemList = new[]
            {
                new { itemId = 1, amount = state.ItemJetCoins },
                new { itemId = 2, amount = state.ItemPaidJetCoins },
                new { itemId = 3, amount = state.ItemDiscForce },
                new { itemId = 4, amount = state.ItemKickPoints }
            },
            userGear = new { kickerId = state.KickerId, gearId = 0 },
            userStampList = Array.Empty<object>(),
            userMissionProgressList = Array.Empty<object>(),
            userDailyRandomMissionTaskList = Array.Empty<object>(),
            kickerTrainingList,
            userPremium = new { premiumId = 0, startDatetime = "", endDatetime = "" },
            userSeasonPass = new { seasonPassId = 1, startDatetime = "2019-01-01 00:00:00", endDatetime = "2030-01-01 23:59:59" },
            userFestivalTeam = new { battleRuleId = 5, festivalTeamId = 1, festivalPoint = 0 },
            tutorialProgressStatus = 207,
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
        if (state.KickerCostumeId == 0 && _costumesByKicker.TryGetValue(state.KickerId, out var homeCostumes) && homeCostumes.Count > 0)
        {
            state.KickerCostumeId = homeCostumes[0];
        }

        var userPlayer = new
        {
            userId = state.UserId,
            displayUserId = int.TryParse(state.UserId, out var uid) ? uid : 1000001,
            name = string.IsNullOrEmpty(state.UserName) ? "Gixarde3" : state.UserName,
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
            discGachaGroupList = Array.Empty<object>(),
            kickerGachaGroupList = Array.Empty<object>(),
            userBattleRankList = new[]
            {
                new { battleRuleType = 1, battlePoint = 4877, rank = 13 },
                new { battleRuleType = 2, battlePoint = 4877, rank = 13 },
                new { battleRuleType = 3, battlePoint = 4877, rank = 13 }
            },
            userMissionProgressList = Array.Empty<object>(),
            shopProductList = Array.Empty<object>(),
            goodsShopProductList = Array.Empty<object>(),
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
            var userId = _userIdByUuid.GetOrAdd(uuid, _ =>
            {
                if (_userIdByUuid.IsEmpty && uuid == "default-user") return "1000001";
                return Interlocked.Increment(ref _userCounter).ToString();
            });

            var state = GetOrCreateUserState(uuid);
            state.UserId = userId;
            if (string.IsNullOrEmpty(state.UserName) || state.UserName == "Gixarde3")
            {
                state.UserName = userId == "1000001" ? "Gixarde3" : $"Player {userId[^4..]}";
            }

            var key = Encoding.ASCII.GetBytes(hash);
            var sessionToken = $"demo-token-{userId}-{Guid.NewGuid():N}";
            _keysByAccessToken[sessionToken] = key;
            _sessionStateByToken[sessionToken] = state;
            _keysByAccessToken[AccessToken] = key;
            _sessionStateByToken[AccessToken] = state;

            context.Response.Headers["x-app-status-code"] = "0";
            context.Response.Headers["x-app-user-id"] = userId;
            context.Response.Headers["x-app-access-token"] = sessionToken;
            context.Response.Headers["x-kickflight-fixture"] = "dynamic-demo-auth";
            context.Response.Headers["x-app-datetime"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ");
            _logger.LogInformation("Created session for user {UserId} ({UserName}) with token {Token}", userId, state.UserName, sessionToken);
            return BinaryJson("{}", key);
        }
        catch (Exception exception) when (exception is CryptographicException or JsonException or ArgumentException)
        {
            _logger.LogWarning("Could not decode local demo authentication request: {Error}", exception.Message);
            return null;
        }
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

    private Task<IResult?> HandleBattleStartAsync(HttpContext context, SessionState state, byte[] key)
    {
        var resp = new
        {
            fieldId = 101, // Arena 1 (FLD00101 Cristalmanía)
            guardianParameter = new
            {
                id = 1,
                rank = 1
            },
            lotteryFestivalPointId = 0
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-battle-start";
        _logger.LogInformation("Handled /battle/start for {UserId}", state.UserId);
        return Task.FromResult<IResult?>(BinaryJson(JsonSerializer.Serialize(resp), key));
    }

    // Colorful.Networking.BattleResultResponseData: every list must be present (empty is fine); the client
    // constructs BattleResultInfo from it unconditionally and NREs on a missing array, which leaves the
    // ResultScene stuck on the score board. Values mirror the static userBattleRankList served at startup.
    private Task<IResult?> HandleBattleResultAsync(HttpContext context, SessionState state, byte[] key)
    {
        var rank = new { battleRuleType = 1, battlePoint = 4877, rank = 13 };
        var resp = new
        {
            userExp = 38500 + 800, // the user's total exp (see the static exp served at startup) plus this battle's reward
            userBattleRank = rank,
            beforeUserBattleRank = rank,
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
            battlePoint = 150,
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
