using System.Text.Json;

namespace KickFlight.BootstrapApi;

// Round C, part 2: the two gachas the shop screen offers. There is no economy design here - the player owns a fixed
// stock of tickets (SessionState.ItemAmounts, 9999 by default) and a draw simply spends one of them, so the drop
// tables are uniform over the whole master (masters_lottery_drop_disc.json / masters_lottery_drop_kicker.json are
// generated with dropRate = 1/N per row) and no rarity weighting is applied.
//
// Retention point for the ShopDiscScroller crash (round C, item 4): the disc tab's scroller
// (Colorful.ShopDiscScroller) is driven by the HOME payload, not by these endpoints -
//   HomeResponseData.discGachaGroupList / kickerGachaGroupList (ResponseGachaGroup[])
//     -> GachaGroupListInfo..ctor(ResponseGachaGroup[]) and GachaGroupListInfo.UpdateData(ResponseGachaGroup[])
//     -> ShopDisplayView.Initialize(GachaGroupListInfo discGachaInfo, GachaGroupListInfo kickerGachaInfo, ...)
//     -> ShopDiscScroller.Initialize(GachaGroupListInfo info), which fills 'private List<GachaGroupInfo> _data'
//     -> EnhancedScroller delegate calls: GetNumberOfCells / GetCellViewSize / GetCellView, and
//        ShopDiscScroller.GetCellHeight(int dataIndex) does '_data[dataIndex]'.
// Both lists used to be served empty, so the scroller ended up with a data list shorter than the cell range
// EnhancedScroller._Resize() walks, and GetCellHeight threw ArgumentOutOfRangeException from List<T>.get_Item.
// BuildHomeJson now emits one group per list (see BuildHomeGachaGroupJson), which is what makes it consistent.
public sealed partial class DemoSessionApi
{
    // ResponseGachaGroup dates and the "unlimited" drawable count every gacha is served with.
    public const string GachaStartDatetime = "2019-01-01 00:00:00";
    public const string GachaEndDatetime = "2030-01-01 23:59:59";
    private const int GachaDrawableCount = 9999;

    // GachaGroup master row ids; they are also the ids the client sends back in GachaDiscDrawRequestData.gachaId
    // (through ResponseGacha.id) and in the *Information requests (as gachaGroupId).
    private const int DiscGachaGroupId = 1;
    private const int KickerGachaGroupId = 2;

    private sealed record GachaGroupRow(int Id, string Name, int GachaType, string BannerImageFilename,
        string StartDatetime, string EndDatetime, string InformationText, string NoticeText);

    private sealed record DiscGachaRow(int Id, int GachaGroupId, int LotteryId, int RarityGroupId,
        int DropAmountGroupId, int LotteryCostId, int LotteryCostAmount, int ModelId,
        string EffectTopImageFilename, string EffectBottomImageFilename);

    private sealed record KickerGachaRow(int Id, int GachaGroupId, int LotteryId, int LotteryCostId,
        int LotteryCostAmount, bool BoxFlag, bool SideBySideFlag, string EffectTopImageFilename,
        string EffectBottomImageFilename);

    private sealed record LotteryCostRow(int Id, int GoodsType, int GoodsId);

    private sealed record LotteryDiscRarityRow(int GroupId, int RarityType, double DropRate, bool PickupFlag);

    private sealed record LotteryDropDiscRow(int DiscId, int RarityType, double DropRate, int SortOrder);

    private sealed record LotteryDropKickerRow(int KickerCostumeId, double DropRate, int SortOrder);

    private readonly Dictionary<int, GachaGroupRow> _gachaGroupById = [];
    private readonly Dictionary<int, DiscGachaRow> _discGachaById = [];
    private readonly Dictionary<int, KickerGachaRow> _kickerGachaById = [];
    private readonly Dictionary<int, LotteryCostRow> _lotteryCostById = [];
    private readonly Dictionary<int, List<LotteryDiscRarityRow>> _lotteryDiscRarityByGroup = [];
    private readonly List<LotteryDropDiscRow> _lotteryDropDisc = [];
    private readonly List<LotteryDropKickerRow> _lotteryDropKicker = [];

    // Every table is announced to the client like Gear/Capsule: one encrypted blob per name plus a row in the
    // /download/master list, which BuildDownloadMasterJson derives from _encryptedMasters.
    private void InitializeGachaMasters(string contentRoot)
    {
        var groupJson = LoadJson(contentRoot, "config/masters_gacha_group.json", "[]");
        var discGachaJson = LoadJson(contentRoot, "config/masters_disc_gacha.json", "[]");
        var kickerGachaJson = LoadJson(contentRoot, "config/masters_kicker_gacha.json", "[]");
        var lotteryCostJson = LoadJson(contentRoot, "config/masters_lottery_cost.json", "[]");
        var lotteryDiscRarityJson = LoadJson(contentRoot, "config/masters_lottery_disc_rarity.json", "[]");
        var lotteryDropDiscJson = LoadJson(contentRoot, "config/masters_lottery_drop_disc.json", "[]");
        var lotteryDropKickerJson = LoadJson(contentRoot, "config/masters_lottery_drop_kicker.json", "[]");
        var lotteryDiscDropAmountJson = LoadJson(contentRoot, "config/masters_lottery_disc_drop_amount.json", "[]");
        var lotteryDropCountRewardJson = LoadJson(contentRoot, "config/masters_lottery_drop_count_reward.json", "[]");
        var lotteryGearRarityJson = LoadJson(contentRoot, "config/masters_lottery_gear_rarity.json", "[]");

        _encryptedMasters["GachaGroup"] = EncryptMaster(groupJson);
        _encryptedMasters["DiscGacha"] = EncryptMaster(discGachaJson);
        _encryptedMasters["KickerGacha"] = EncryptMaster(kickerGachaJson);
        _encryptedMasters["LotteryCost"] = EncryptMaster(lotteryCostJson);
        _encryptedMasters["LotteryDiscRarity"] = EncryptMaster(lotteryDiscRarityJson);
        _encryptedMasters["LotteryDropDisc"] = EncryptMaster(lotteryDropDiscJson);
        _encryptedMasters["LotteryDropKicker"] = EncryptMaster(lotteryDropKickerJson);
        _encryptedMasters["LotteryDiscDropAmount"] = EncryptMaster(lotteryDiscDropAmountJson);
        _encryptedMasters["LotteryDropCountReward"] = EncryptMaster(lotteryDropCountRewardJson);
        _encryptedMasters["LotteryGearRarity"] = EncryptMaster(lotteryGearRarityJson);

        try
        {
            foreach (var el in JsonDocument.Parse(groupJson).RootElement.EnumerateArray())
            {
                var row = new GachaGroupRow(IntOf(el, "id"), StrOf(el, "name"), IntOf(el, "gachaType"),
                    StrOf(el, "bannerImageFilename"), StrOf(el, "startDatetime"), StrOf(el, "endDatetime"),
                    StrOf(el, "informationText"), StrOf(el, "noticeText"));
                _gachaGroupById[row.Id] = row;
            }

            foreach (var el in JsonDocument.Parse(discGachaJson).RootElement.EnumerateArray())
            {
                var row = new DiscGachaRow(IntOf(el, "id"), IntOf(el, "gachaGroupId"), IntOf(el, "lotteryId"),
                    IntOf(el, "lotteryDiscRarityGroupId"), IntOf(el, "lotteryDiscDropAmountGroupId"),
                    IntOf(el, "lotteryCostId"), IntOf(el, "lotteryCostAmount"), IntOf(el, "modelId"),
                    StrOf(el, "effectTopImageFilename"), StrOf(el, "effectBottomImageFilename"));
                _discGachaById[row.Id] = row;
            }

            foreach (var el in JsonDocument.Parse(kickerGachaJson).RootElement.EnumerateArray())
            {
                var row = new KickerGachaRow(IntOf(el, "id"), IntOf(el, "gachaGroupId"), IntOf(el, "lotteryId"),
                    IntOf(el, "lotteryCostId"), IntOf(el, "lotteryCostAmount"), BoolOf(el, "boxFlag"),
                    BoolOf(el, "sideBySideFlag"), StrOf(el, "effectTopImageFilename"), StrOf(el, "effectBottomImageFilename"));
                _kickerGachaById[row.Id] = row;
            }

            foreach (var el in JsonDocument.Parse(lotteryCostJson).RootElement.EnumerateArray())
            {
                var row = new LotteryCostRow(IntOf(el, "id"), IntOf(el, "goodsType"), IntOf(el, "goodsId"));
                _lotteryCostById[row.Id] = row;
            }

            foreach (var el in JsonDocument.Parse(lotteryDiscRarityJson).RootElement.EnumerateArray())
            {
                var row = new LotteryDiscRarityRow(IntOf(el, "groupId"), IntOf(el, "rarityType"),
                    DoubleOf(el, "dropRate"), BoolOf(el, "pickupFlag"));
                if (!_lotteryDiscRarityByGroup.TryGetValue(row.GroupId, out var list))
                {
                    list = [];
                    _lotteryDiscRarityByGroup[row.GroupId] = list;
                }
                list.Add(row);
            }

            foreach (var el in JsonDocument.Parse(lotteryDropDiscJson).RootElement.EnumerateArray())
            {
                _lotteryDropDisc.Add(new LotteryDropDiscRow(IntOf(el, "discId"), IntOf(el, "rarityType"),
                    DoubleOf(el, "dropRate"), IntOf(el, "sortOrder")));
            }

            foreach (var el in JsonDocument.Parse(lotteryDropKickerJson).RootElement.EnumerateArray())
            {
                _lotteryDropKicker.Add(new LotteryDropKickerRow(IntOf(el, "kickerCostumeId"),
                    DoubleOf(el, "dropRate"), IntOf(el, "sortOrder")));
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error parsing gacha master json: {Error}", ex.Message);
        }

        if (_lotteryDropDisc.Count == 0 || _lotteryDropKicker.Count == 0 || _discGachaById.Count == 0 || _kickerGachaById.Count == 0)
        {
            _logger.LogWarning("Gacha masters are incomplete ({DiscDrops} disc drops, {KickerDrops} kicker drops, {DiscGachas} disc gachas, {KickerGachas} kicker gachas) - draws will be rejected",
                _lotteryDropDisc.Count, _lotteryDropKicker.Count, _discGachaById.Count, _kickerGachaById.Count);
        }
    }

    private async Task<IResult?> TryHandleGachaAsync(string path, HttpContext context, SessionState state, byte[] key)
    {
        switch (path)
        {
            case "/gacha/read":
                // GachaReadResponseData declares no fields at all, so the neutral payload is the empty object.
                context.Response.Headers["x-app-status-code"] = "0";
                context.Response.Headers["x-kickflight-fixture"] = "dynamic-gacha-read";
                return BinaryJson("{}", key);

            case "/gacha/discInformation":
                return await HandleGachaDiscInformationAsync(context, key);

            case "/gacha/kickerInformation":
                return await HandleGachaKickerInformationAsync(context, key);

            case "/gacha/discDraw":
                return await HandleGachaDiscDrawAsync(context, state, key);

            case "/gacha/kickerDraw":
                return await HandleGachaKickerDrawAsync(context, state, key);

            default:
                return null;
        }
    }

    private async Task<IResult?> HandleGachaDiscInformationAsync(HttpContext context, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        var gachaGroupId = DiscGachaGroupId;
        try
        {
            if (body.Length > 0)
            {
                var plaintext = D2CCodec.Decode(body, key);
                using var document = JsonDocument.Parse(plaintext);
                gachaGroupId = IntOf(document.RootElement, "gachaGroupId", DiscGachaGroupId);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode gacha disc information request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        // ResponseDiscGachaGroupInformation: one entry per DiscGacha row of the requested group.
        var groups = new List<object>();
        foreach (var gacha in _discGachaById.Values.Where(g => g.GachaGroupId == gachaGroupId).OrderBy(g => g.Id))
        {
            var rarities = _lotteryDiscRarityByGroup.TryGetValue(gacha.RarityGroupId, out var rList)
                ? rList.Select(r => new { rarityType = r.RarityType, pickupFlag = r.PickupFlag, dropRate = r.DropRate }).ToArray()
                : [];
            var drops = _lotteryDropDisc
                .OrderBy(d => d.SortOrder)
                .Select(d => new { discId = d.DiscId, pickupFlag = false, newFlag = false, dropRate = d.DropRate })
                .ToArray();
            groups.Add(new
            {
                lotteryId = gacha.LotteryId,
                name = _gachaGroupById.TryGetValue(gachaGroupId, out var group) ? group.Name : "",
                lotteryDiscRarityList = rarities,
                lotteryDropDiscList = drops
            });
        }

        var response = new
        {
            informationText = GachaGroupText(gachaGroupId, information: true),
            noticeText = GachaGroupText(gachaGroupId, information: false),
            discGachaGroupInformationList = groups.ToArray(),
            dropDiscForceList = Array.Empty<object>(),
            lotteryDropDiscForceList = Array.Empty<object>()
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-gacha-information";
        return BinaryJson(JsonSerializer.Serialize(response), key);
    }

    private async Task<IResult?> HandleGachaKickerInformationAsync(HttpContext context, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        var gachaGroupId = KickerGachaGroupId;
        try
        {
            if (body.Length > 0)
            {
                var plaintext = D2CCodec.Decode(body, key);
                using var document = JsonDocument.Parse(plaintext);
                gachaGroupId = IntOf(document.RootElement, "gachaGroupId", KickerGachaGroupId);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode gacha kicker information request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        var gacha = _kickerGachaById.Values.FirstOrDefault(g => g.GachaGroupId == gachaGroupId);
        var response = new
        {
            informationText = GachaGroupText(gachaGroupId, information: true),
            noticeText = GachaGroupText(gachaGroupId, information: false),
            boxFlag = gacha?.BoxFlag ?? false,
            sideBySideFlag = gacha?.SideBySideFlag ?? false,
            pickupFlag = false,
            lotteryDropKickerList = _lotteryDropKicker
                .OrderBy(k => k.SortOrder)
                .Select(k => new { kickerCostumeId = k.KickerCostumeId, pickupFlag = false, newFlag = false, dropRate = k.DropRate })
                .ToArray()
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-gacha-information";
        return BinaryJson(JsonSerializer.Serialize(response), key);
    }

    private async Task<IResult?> HandleGachaDiscDrawAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        var gachaId = _discGachaById.Keys.OrderBy(id => id).FirstOrDefault();
        // GachaDiscDrawRequestData declares only gachaId; a "count" is read when the caller sends one anyway.
        var count = 1;
        try
        {
            if (body.Length > 0)
            {
                var plaintext = D2CCodec.Decode(body, key);
                using var document = JsonDocument.Parse(plaintext);
                gachaId = IntOf(document.RootElement, "gachaId", gachaId);
                count = IntOf(document.RootElement, "count", 1);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode gacha disc draw request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        if (!_discGachaById.TryGetValue(gachaId, out var gacha) || _lotteryDropDisc.Count == 0 || count < 1)
        {
            _logger.LogWarning("Rejected gacha/discDraw for gacha {GachaId} x{Count} ({Drops} disc drops in master)", gachaId, count, _lotteryDropDisc.Count);
            return StatusError(context, key);
        }
        count = Math.Min(count, 10);

        var drawn = new List<LotteryDropDiscRow>();
        for (var i = 0; i < count; i++) drawn.Add(_lotteryDropDisc[Random.Shared.Next(_lotteryDropDisc.Count)]);

        var receivedDiscs = new List<object>();
        foreach (var discId in drawn.Select(d => d.DiscId).Distinct())
        {
            if (!state.Discs.TryGetValue(discId, out var discState))
            {
                // A disc the save has never held: level 1 with a single copy.
                discState = new UserDiscState { DiscId = discId, Level = 1, Amount = 0 };
                state.Discs[discId] = discState;
            }
            discState.Amount += drawn.Count(d => d.DiscId == discId);
            receivedDiscs.Add(new
            {
                discId = discState.DiscId,
                amount = discState.Amount,
                level = discState.Level,
                registerDatetime = "2026-09-01 00:00:00"
            });
        }

        // A draw is paid with the ticket LotteryCost names for the gacha's cost id; running out is not refused,
        // the counter just stops at zero (there is no economy design).
        var ticketItemId = TicketItemId(gacha.LotteryCostId, fallback: 8);
        SpendItem(state, ticketItemId, count * Math.Max(gacha.LotteryCostAmount, 1));

        SaveUserState(state);

        var groupName = _gachaGroupById.TryGetValue(gacha.GachaGroupId, out var groupRow) ? groupRow.Name : "";
        var response = new
        {
            dropDiscList = drawn.Select(d => new { discId = d.DiscId, amount = 1, discForceAmount = 0 }).ToArray(),
            receivedUserDiscList = receivedDiscs.ToArray(),
            receivedUserItemList = Array.Empty<object>(),
            userItemList = BuildUserItemList(state),
            gachaDropCountRewardList = Array.Empty<object>(),
            modelId = gacha.ModelId,
            effectTopImageFilename = gacha.EffectTopImageFilename,
            effectBottomImageFilename = gacha.EffectBottomImageFilename,
            capsuleEffectType = 1,
            drawableCount = GachaDrawableCount,
            drawableDatetime = GachaGroupEnd(gacha.GachaGroupId),
            completedDisplayFlag = false,
            userPresentList = Array.Empty<object>(),
            userMissionProgressList = Array.Empty<object>(),
            userDailyRandomMissionTaskList = Array.Empty<object>(),
            receivedRewardList = Array.Empty<object>(),
            premiumFlag = false
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-gacha-disc-draw";
        _logger.LogInformation("Disc gacha {GachaId} ({Group}) drew {Count} disc(s) for user {UserId}: {Discs}; item {Ticket} is now {Left}",
            gachaId, groupName, count, state.UserId, string.Join(",", drawn.Select(d => d.DiscId)), ticketItemId, StockAmount(state, ticketItemId));
        return BinaryJson(JsonSerializer.Serialize(response), key);
    }

    private async Task<IResult?> HandleGachaKickerDrawAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        var gachaId = _kickerGachaById.Keys.OrderBy(id => id).FirstOrDefault();
        var count = 1;
        try
        {
            if (body.Length > 0)
            {
                var plaintext = D2CCodec.Decode(body, key);
                using var document = JsonDocument.Parse(plaintext);
                gachaId = IntOf(document.RootElement, "gachaId", gachaId);
                count = IntOf(document.RootElement, "count", 1);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode gacha kicker draw request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        if (!_kickerGachaById.TryGetValue(gachaId, out var gacha) || _lotteryDropKicker.Count == 0 || count < 1)
        {
            _logger.LogWarning("Rejected gacha/kickerDraw for gacha {GachaId} x{Count} ({Drops} costume drops in master)", gachaId, count, _lotteryDropKicker.Count);
            return StatusError(context, key);
        }
        count = Math.Min(count, 10);

        var drawn = new List<LotteryDropKickerRow>();
        for (var i = 0; i < count; i++) drawn.Add(_lotteryDropKicker[Random.Shared.Next(_lotteryDropKicker.Count)]);

        var ticketItemId = TicketItemId(gacha.LotteryCostId, fallback: 7);
        SpendItem(state, ticketItemId, count * Math.Max(gacha.LotteryCostAmount, 1));
        SaveUserState(state);

        // Every costume is already owned (the startup payload hands the whole master out), so the "received" list
        // repeats the costume that was drawn - the client uses it to replay the reveal animation.
        var receivedKickers = drawn
            .Select(k => _costumeKicker.TryGetValue(k.KickerCostumeId, out var owner) ? owner : 0)
            .Where(kickerId => kickerId != 0)
            .Distinct()
            .Select(kickerId => BuildUserKicker(state, kickerId))
            .ToArray();

        var response = new
        {
            dropKickerCostumeList = drawn.Select(k => new
            {
                kickerId = _costumeKicker.TryGetValue(k.KickerCostumeId, out var owner) ? owner : 0,
                kickerCostumeId = k.KickerCostumeId
            }).ToArray(),
            receivedUserKickerList = receivedKickers,
            userItemList = BuildUserItemList(state),
            effectTopImageFilename = gacha.EffectTopImageFilename,
            effectBottomImageFilename = gacha.EffectBottomImageFilename,
            userPresentList = Array.Empty<object>(),
            userMissionProgressList = Array.Empty<object>(),
            userDailyRandomMissionTaskList = Array.Empty<object>(),
            receivedRewardList = Array.Empty<object>(),
            gachaBoxStatus = new { acquiredAmount = 0, totalAmount = 0 }
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-gacha-kicker-draw";
        _logger.LogInformation("Kicker gacha {GachaId} drew {Count} costume(s) for user {UserId}: {Costumes}; item {Ticket} is now {Left}",
            gachaId, count, state.UserId, string.Join(",", drawn.Select(k => k.KickerCostumeId)), ticketItemId, StockAmount(state, ticketItemId));
        return BinaryJson(JsonSerializer.Serialize(response), key);
    }

    // ResponseUserKicker, the same shape BuildStartupJson serves: the costume list carries the gear slots so the
    // reveal card can draw them.
    private object BuildUserKicker(SessionState state, int kickerId)
    {
        var costumes = _costumesByKicker.GetValueOrDefault(kickerId, []);
        return new
        {
            kickerId,
            kickerCostumeId = costumes.Count > 0 ? costumes[0] : 0,
            userKickerCostumeList = costumes.Select(c =>
            {
                var slots = GearSlots(state, c);
                return new { kickerCostumeId = c, gearId1 = slots[0], gearId2 = slots[1], gearId3 = slots[2] };
            }).ToArray()
        };
    }

    // ResponseGachaGroup for the home payload. ShopDiscScroller/ShopKickerScroller are fed from exactly this list,
    // so it must not be empty while the shop screen is open (see the note at the top of this file).
    private object[] BuildHomeGachaGroupList(int gachaGroupId)
    {
        if (!_gachaGroupById.TryGetValue(gachaGroupId, out var group)) return [];

        var gachaList = new List<object>();
        if (gachaGroupId == DiscGachaGroupId)
        {
            foreach (var gacha in _discGachaById.Values.Where(g => g.GachaGroupId == gachaGroupId).OrderBy(g => g.Id))
            {
                gachaList.Add(BuildResponseGacha(gacha.Id, gacha.LotteryCostId, gacha.LotteryCostAmount,
                    gacha.EffectTopImageFilename, gacha.EffectBottomImageFilename));
            }
        }
        else
        {
            foreach (var gacha in _kickerGachaById.Values.Where(g => g.GachaGroupId == gachaGroupId).OrderBy(g => g.Id))
            {
                gachaList.Add(BuildResponseGacha(gacha.Id, gacha.LotteryCostId, gacha.LotteryCostAmount,
                    gacha.EffectTopImageFilename, gacha.EffectBottomImageFilename));
            }
        }

        return
        [
            new
            {
                gachaGroupId = group.Id,
                name = group.Name,
                gachaType = group.GachaType,
                bannerImageFilename = group.BannerImageFilename,
                startDatetime = group.StartDatetime,
                endDatetime = group.EndDatetime,
                boxFlag = false,
                stepFlag = false,
                newFlag = false,
                completedDisplayFlag = false,
                remainingTimeDisplayFlag = false,
                gachaList = gachaList.ToArray(),
                gachaDropCountRewardList = Array.Empty<object>()
            }
        ];
    }

    private object BuildResponseGacha(int gachaId, int lotteryCostId, int lotteryCostAmount, string effectTop, string effectBottom)
    {
        _lotteryCostById.TryGetValue(lotteryCostId, out var cost);
        return new
        {
            id = gachaId,
            dropAmount = 1,
            drawableCount = GachaDrawableCount,
            drawableDatetime = GachaEndDatetime,
            costGoodsType = cost?.GoodsType ?? 0,
            costGoodsId = cost?.GoodsId ?? 0,
            costAmount = lotteryCostAmount,
            gachaBoxStatus = new { acquiredAmount = 0, totalAmount = 0 },
            stepNumber = 0,
            effectTopImageFilename = effectTop,
            effectBottomImageFilename = effectBottom
        };
    }

    private string GachaGroupText(int gachaGroupId, bool information) =>
        _gachaGroupById.TryGetValue(gachaGroupId, out var group)
            ? information ? group.InformationText : group.NoticeText
            : "";

    private string GachaGroupEnd(int gachaGroupId) =>
        _gachaGroupById.TryGetValue(gachaGroupId, out var group) && !string.IsNullOrEmpty(group.EndDatetime)
            ? group.EndDatetime
            : GachaEndDatetime;

    // LotteryCost rows name the ticket in goodsType/goodsId; the Item master maps that goodsType to the item id the
    // client counts (402 disc ticket -> item 8, 401 kicker ticket -> item 7).
    private int TicketItemId(int lotteryCostId, int fallback)
    {
        if (!_lotteryCostById.TryGetValue(lotteryCostId, out var cost)) return fallback;
        return _itemIdByGoodsType.TryGetValue(cost.GoodsType, out var itemId) ? itemId : fallback;
    }

    private static int IntOf(JsonElement element, string name, int fallback = 0) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.Number
            ? p.GetInt32()
            : fallback;

    private static double DoubleOf(JsonElement element, string name, double fallback = 0.0) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.Number
            ? p.GetDouble()
            : fallback;

    private static bool BoolOf(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.True;

    private static string StrOf(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String
            ? p.GetString() ?? ""
            : "";
}
