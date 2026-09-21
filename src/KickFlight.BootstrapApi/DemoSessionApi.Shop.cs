using System.Text.Json;

namespace KickFlight.BootstrapApi;

// Round C, part 1 and 3: the item stocks the gear screen counts stamps from, and the goods shop that trades JetCoin
// for them. As with the gacha there is no economy design - a fresh save reads every stock item as
// DefaultStockAmount (9999) and a purchase only has to stay above zero, so nothing here models scarcity.
public sealed partial class DemoSessionApi
{
    // ids 5-8 of the Item master: gear stamps, disc fragments and the two gacha tickets. A save written before
    // round C has no entry for them and reads as this default.
    public const int DefaultStockAmount = 9999;
    private const int GoodsShopPurchasableCount = 9999;

    private sealed record GoodsShopProductRow(int Id, int GoodsShopType, string Name, int CostGoodsType, int CostGoodsId,
        int CostAmount, int GoodsType, int GoodsId, int GoodsAmount);

    // goodsShopType follows GoodsShopType in the dump (1 = DiscForce, 2 = Exchange). The Disc Force product is the
    // DiscForce tab; the three JetCoin exchanges live in the Exchange tab.
    private static readonly GoodsShopProductRow[] GoodsShopProducts =
    [
        new(1, 2, "Ticket de gacha de discos", 101, 1, 100, 402, 8, 1),
        new(2, 2, "Ticket de gacha de Kickers", 101, 1, 300, 401, 7, 1),
        new(3, 2, "Sellos de engranaje x10", 101, 1, 100, 202, 5, 10),
        new(4, 1, "Disc Force x1000", 101, 1, 100, 302, 3, 1000),
    ];

    // goodsType -> Item master id, so a GoodsType the shop or a lottery rewards is turned into the itemId the client
    // counts without a second table.
    private readonly Dictionary<int, int> _itemIdByGoodsType = [];

    private void ParseItemMaster(string itemJson)
    {
        try
        {
            foreach (var el in JsonDocument.Parse(itemJson).RootElement.EnumerateArray())
            {
                _itemIdByGoodsType[IntOf(el, "goodsType")] = IntOf(el, "id");
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Error parsing item master json: {Error}", ex.Message);
        }
    }

    // ResponseUserItem for the whole Item master: ids 1-4 are the legacy counters, 5-8 the round C stocks.
    public static object[] BuildUserItemList(SessionState state) =>
    [
        new { itemId = 1, amount = StockAmount(state, 1) },
        new { itemId = 2, amount = StockAmount(state, 2) },
        new { itemId = 3, amount = StockAmount(state, 3) },
        new { itemId = 4, amount = StockAmount(state, 4) },
        new { itemId = 5, amount = StockAmount(state, 5) },
        new { itemId = 6, amount = StockAmount(state, 6) },
        new { itemId = 7, amount = StockAmount(state, 7) },
        new { itemId = 8, amount = StockAmount(state, 8) },
    ];

    public static int StockAmount(SessionState state, int itemId) => itemId switch
    {
        1 => state.ItemJetCoins,
        2 => state.ItemPaidJetCoins,
        3 => state.ItemDiscForce,
        4 => state.ItemKickPoints,
        >= 5 and <= 8 => state.ItemAmounts.TryGetValue(itemId, out var amount) ? amount : DefaultStockAmount,
        _ => 0
    };

    private static void SetStockAmount(SessionState state, int itemId, int amount)
    {
        amount = Math.Max(0, amount);
        switch (itemId)
        {
            case 1: state.ItemJetCoins = amount; break;
            case 2: state.ItemPaidJetCoins = amount; break;
            case 3: state.ItemDiscForce = amount; break;
            case 4: state.ItemKickPoints = amount; break;
            case >= 5 and <= 8: state.ItemAmounts[itemId] = amount; break;
        }
    }

    // Drawing or buying never drives a counter below zero: there is no "not enough" state to model for the gacha,
    // and the goods shop refuses the purchase before it gets here.
    private static void SpendItem(SessionState state, int itemId, int amount) =>
        SetStockAmount(state, itemId, StockAmount(state, itemId) - amount);

    private static void GrantItem(SessionState state, int itemId, int amount) =>
        SetStockAmount(state, itemId, StockAmount(state, itemId) + amount);

    // ResponseGoodsShopProduct, field for field (goodsShopProductGoodsList carries exactly one grant here).
    private object[] BuildGoodsShopProducts() => GoodsShopProducts.Select(p => (object)new
    {
        id = p.Id,
        goodsShopType = p.GoodsShopType,
        name = p.Name,
        costGoodsType = p.CostGoodsType,
        costGoodsId = p.CostGoodsId,
        costAmount = p.CostAmount,
        resetType = 0,
        startDatetime = GachaStartDatetime,
        endDatetime = GachaEndDatetime,
        resetDatetime = "",
        limitedCount = 0,
        purchasableCount = GoodsShopPurchasableCount,
        newFlag = false,
        goodsShopProductGoodsList = new[]
        {
            new { goodsType = p.GoodsType, goodsId = p.GoodsId, amount = p.GoodsAmount }
        }
    }).ToArray();

    private async Task<IResult?> TryHandleShopAsync(string path, HttpContext context, SessionState state, byte[] key)
    {
        switch (path)
        {
            // GoodsShopReadResponseData / ShopOptionResponseData / ShopBirthdayResponseData declare no fields.
            case "/goodsShop/read":
                context.Response.Headers["x-app-status-code"] = "0";
                context.Response.Headers["x-kickflight-fixture"] = "dynamic-goods-shop-read";
                return BinaryJson("{}", key);

            case "/goodsShop/buy":
                return await HandleGoodsShopBuyAsync(context, state, key);

            case "/goodsShop/reset":
                context.Response.Headers["x-app-status-code"] = "0";
                context.Response.Headers["x-kickflight-fixture"] = "dynamic-goods-shop-reset";
                return BinaryJson(JsonSerializer.Serialize(new
                {
                    userItemList = BuildUserItemList(state),
                    goodsShopProductList = BuildGoodsShopProducts()
                }), key);

            case "/shop/option":
            case "/shop/birthday":
                context.Response.Headers["x-app-status-code"] = "0";
                context.Response.Headers["x-kickflight-fixture"] = "dynamic-shop-neutral";
                return BinaryJson("{}", key);

            // Real-money IAP. Nothing is purchasable, so every reply is the neutral shape of its DTO: the shop
            // screen opens and the purchase buttons stay dead.
            case "/shop/prepare":
                context.Response.Headers["x-app-status-code"] = "0";
                context.Response.Headers["x-kickflight-fixture"] = "dynamic-shop-neutral";
                return BinaryJson("""{"monthlyPurchaseLimitFlag":false,"monthlyPurchaseAlertFlag":false,"monthlyPurchaseAlertStorePrice":0.0}""", key);

            case "/shop/verify":
                context.Response.Headers["x-app-status-code"] = "0";
                context.Response.Headers["x-kickflight-fixture"] = "dynamic-shop-neutral";
                return BinaryJson("""
                    {"receivedUserCapsuleList":[],"receivedUserDiscList":[],"receivedUserHonorList":[],"receivedUserItemList":[],
                     "receivedUserStampList":[],"userPresentList":[],
                     "userPremium":{"premiumId":0,"startDatetime":"","endDatetime":""},
                     "userSeasonPass":{"seasonPassId":0,"startDatetime":"","endDatetime":""},
                     "receivedRewardList":[],"shopTypePurchaseCountList":[],"userMissionProgressList":[]}
                    """, key);

            default:
                return null;
        }
    }

    private async Task<IResult?> HandleGoodsShopBuyAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        var productId = 0;
        // GoodsShopBuyRequestData declares only goodsShopProductId; a "count" is honoured when one is sent anyway.
        var count = 1;
        try
        {
            var plaintext = D2CCodec.Decode(body, key);
            using var document = JsonDocument.Parse(plaintext);
            productId = IntOf(document.RootElement, "goodsShopProductId");
            count = IntOf(document.RootElement, "count", 1);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode goods shop buy request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        var product = GoodsShopProducts.FirstOrDefault(p => p.Id == productId);
        if (product is null || count < 1)
        {
            _logger.LogWarning("Rejected goodsShop/buy for unknown product {ProductId} x{Count}", productId, count);
            return StatusError(context, key);
        }
        count = Math.Min(count, GoodsShopPurchasableCount);

        var costItemId = _itemIdByGoodsType.GetValueOrDefault(product.CostGoodsType, 0);
        var cost = product.CostAmount * count;
        var owned = costItemId == 0 ? 0 : StockAmount(state, costItemId);
        if (costItemId == 0 || owned < cost)
        {
            _logger.LogWarning("goodsShop/buy of product {ProductId} x{Count} needs {Cost} of item {CostItem} but the user has {Owned}",
                productId, count, cost, costItemId, owned);
            return StatusError(context, key);
        }

        SpendItem(state, costItemId, cost);

        var grantedItemId = _itemIdByGoodsType.GetValueOrDefault(product.GoodsType, 0);
        if (grantedItemId != 0) GrantItem(state, grantedItemId, product.GoodsAmount * count);
        SaveUserState(state);

        var response = new
        {
            dropKickerCostumeList = Array.Empty<object>(),
            receivedUserKickerList = Array.Empty<object>(),
            receivedUserCapsuleList = Array.Empty<object>(),
            receivedUserDiscList = Array.Empty<object>(),
            receivedUserHonorList = Array.Empty<object>(),
            receivedUserItemList = grantedItemId == 0
                ? Array.Empty<object>()
                : new object[] { new { itemId = grantedItemId, amount = StockAmount(state, grantedItemId) } },
            receivedUserStampList = Array.Empty<object>(),
            userItemList = BuildUserItemList(state),
            userPresentList = Array.Empty<object>(),
            receivedRewardList = Array.Empty<object>()
        };

        context.Response.Headers["x-app-status-code"] = "0";
        context.Response.Headers["x-kickflight-fixture"] = "dynamic-goods-shop-buy";
        _logger.LogInformation("goodsShop/buy product {ProductId} x{Count} for user {UserId}: -{Cost} of item {CostItem}, +{Granted} of item {GrantedItem}",
            productId, count, state.UserId, cost, costItemId, product.GoodsAmount * count, grantedItemId);
        return BinaryJson(JsonSerializer.Serialize(response), key);
    }
}
