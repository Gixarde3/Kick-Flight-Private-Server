using System.Text.Json;

namespace KickFlight.BootstrapApi;

public sealed partial class DemoSessionApi
{
    // ResponseBattleRanking: a row of any ranking list. No ranking data is served, so this only exists to give
    // RankingResponseData.battleRanking (the caller's own entry) a non-null, fully populated object.
    private const string NeutralBattleRanking =
        """{"userId":"","name":"","honorId":0,"kickerId":0,"kickerCostumeId":0,"languageCode":"","followStatus":0,"rank":0,"battlePoint":0,"number":0,"percentile":0.0}""";

    // ResponseAppSeasonMatchResult: the season result banner. Neutral dates, no rule attached.
    private const string NeutralSeasonMatchResult =
        """{"battleRuleId":0,"resultDatetime":"2026-01-01 00:00:00","rewardReceiptStartDatetime":"2026-01-01 00:00:00","rewardReceiptEndDatetime":"2026-01-01 00:00:00"}""";

    // ResponseUserDailyRandomMissionTask: mission/change hands one back, so it cannot be an empty list.
    private const string NeutralDailyRandomMissionTask =
        """{"missionTaskId":0,"number":0,"changeCount":0,"userMissionProgress":{"missionId":0,"loopCount":0,"value":0,"userMissionTaskStatusList":[]}}""";

    private static readonly string NeutralRankingList =
        $$"""{"battleRankingList":[],"battleRanking":{{NeutralBattleRanking}},"nextRewardRemainingBattlePoint":0,"appSeasonMatchResult":{{NeutralSeasonMatchResult}}}""";

    // Every field of every ResponseData class has to be present: the client deserializes the whole object
    // unconditionally and NullReferenceExceptions on an array that is missing, not merely empty. So the payloads
    // below are the DTO's full field list (../Kick-Flight-Assets/server_revival_analysis/il2cpp/dump.cs) filled with
    // neutral values - nothing here is real data.
    private async Task<IResult?> TryHandleStubAsync(string path, HttpContext context, SessionState state, byte[] key)
    {
        switch (path)
        {
            // Client telemetry; AnalysisResponseData carries no fields.
            case "/analysis/index":
                return OkJson(context, key, "{}");

            // FollowStatus in every row below is the neutral 0 (none).
            case "/follow/search":
                return OkJson(context, key, """{"followUserIdList":[]}""");
            case "/follow/add":
            case "/follow/remove":
                return OkJson(context, key, "{}");
            case "/follower/index":
                return OkJson(context, key, """{"userProfileList":[],"followerCount":0,"newFollowerCount":0}""");
            case "/follower/read":
                return OkJson(context, key, "{}");

            case "/user/search":
                return await HandleUserSearchStubAsync(context, state, key);
            case "/user/detail":
                return await HandleUserDetailStubAsync(context, state, key);
            case "/user/change":
                return await HandleUserChangeStubAsync(context, state, key);
            case "/user/birthday":
                return OkJson(context, key, """{"dataUsageAgreementConfirmFlag":false}""");
            case "/user/displayUserId":
                return OkJson(context, key, $$"""{"displayUserId":{{CurrentDisplayUserId(state)}}}""");

            case "/ranking/index":
            case "/ranking/user":
            case "/ranking/follow":
                return OkJson(context, key, NeutralRankingList);
            case "/ranking/region":
                // RankingRegionResponseData has no per-user entry, only the list and the season banner.
                return OkJson(context, key, $$"""{"battleRankingList":[],"appSeasonMatchResult":{{NeutralSeasonMatchResult}}}""");

            case "/sns/index":
                return OkJson(context, key, """{"userProfileList":[]}""");
            case "/sns/disconnection":
                return OkJson(context, key, "{}");

            case "/present/index":
                return OkJson(context, key, """{"unlimitedUserPresentList":[],"limitedUserPresentList":[],"userPresentHistoryList":[]}""");
            case "/present/receipt":
                return OkJson(context, key,
                    """{"receivedUserCapsuleList":[],"receivedUserDiscList":[],"receivedUserHonorList":[],"receivedUserItemList":[],"unreceivedUserPresentList":[],"userPresentHistoryList":[],"userMissionProgressList":[]}""");

            case "/mission/index":
            case "/mission/read":
            case "/mission/tweet":
                return OkJson(context, key, """{"userMissionProgressList":[],"userDailyRandomMissionTaskList":[]}""");
            case "/mission/receipt":
                return OkJson(context, key,
                    """{"receivedUserCapsuleList":[],"receivedUserDiscList":[],"receivedUserHonorList":[],"receivedUserItemList":[],"receivedUserStampList":[],"userPresentList":[],"userMissionProgressList":[],"receivedRewardList":[]}""");
            case "/mission/change":
                return OkJson(context, key, $$"""{"userDailyRandomMissionTask":{{NeutralDailyRandomMissionTask}}}""");

            case "/battleReplay/index":
                return OkJson(context, key, """{"battleReplayChannelList":[],"appMovieList":[]}""");
            case "/battleReplay/checkMovie":
                return OkJson(context, key, "{}");
            case "/battleReplay/play":
                return OkJson(context, key, """{"battleReplayUrl":"","encryptionKey":""}""");

            case "/battleReplayNotification/read":
            case "/interruptNotification/read":
            case "/agreement/read":
            case "/agreement/dataUsage":
                return OkJson(context, key, "{}");

            case "/battleSummary/index":
                return OkJson(context, key, """{"userBattleSummaryList":[]}""");
            case "/battleSummary/season":
                return OkJson(context, key, """{"userBattleSummarySeasonList":[]}""");
            case "/battleSummary/festival":
                return OkJson(context, key, """{"festivalMatchResultList":[]}""");

            case "/chatRoomComment/write":
                return OkJson(context, key, "{}");

            case "/capsule/immediateOpen":
                // Only this one repeats userItemList: the client refreshes the item counters from it without
                // re-fetching the startup payload.
                return OkJson(context, key,
                    $$"""{"dropDiscList":[],"receivedUserDiscList":[],"receivedUserItemList":[],"userItemList":{{BuildUserItemListJson(state)}},"capsuleEffectType":0,"userPresentList":[],"userMissionProgressList":[],"userDailyRandomMissionTaskList":[],"receivedRewardList":[],"premiumFlag":false}""");
            case "/capsule/open":
                return OkJson(context, key,
                    """{"dropDiscList":[],"receivedUserDiscList":[],"receivedUserItemList":[],"capsuleEffectType":0,"userPresentList":[],"userMissionProgressList":[],"userDailyRandomMissionTaskList":[],"receivedRewardList":[],"premiumFlag":false}""");

            default:
                return null;
        }
    }

    // user/search is a display-id lookup, so the reply always has to be a profile: searching yourself returns your
    // own, any other id gets a placeholder one instead of an empty list the UI would dereference.
    private async Task<IResult?> HandleUserSearchStubAsync(HttpContext context, SessionState state, byte[] key)
    {
        var displayUserId = CurrentDisplayUserId(state);
        var body = await ReadBodyAsync(context.Request);
        try
        {
            if (body.Length > 0)
            {
                var plaintext = D2CCodec.Decode(body, key);
                using var document = JsonDocument.Parse(plaintext);
                if (document.RootElement.TryGetProperty("displayUserId", out var idProp))
                {
                    displayUserId = idProp.GetInt64();
                }
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode user search request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        var profile = displayUserId == CurrentDisplayUserId(state)
            ? BuildUserProfileJson(state, state.UserId, displayUserId, CurrentUserName(state))
            : BuildUserProfileJson(state, displayUserId.ToString(), displayUserId, $"Player {displayUserId}");

        return OkJson(context, key, $$"""{"userProfile":{{profile}}}""");
    }

    private async Task<IResult?> HandleUserDetailStubAsync(HttpContext context, SessionState state, byte[] key)
    {
        // The request carries a searchUserId, but the only profile this server can describe is the caller's own, so
        // the body is decoded for logging and ignored.
        var body = await ReadBodyAsync(context.Request);
        try
        {
            if (body.Length > 0) D2CCodec.Decode(body, key);
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode user detail request: {Error}", ex.Message);
            return StatusError(context, key);
        }

        var profile = BuildUserProfileJson(state, state.UserId, CurrentDisplayUserId(state), CurrentUserName(state));
        return OkJson(context, key,
            $$"""{"userProfile":{{profile}},"userBattleParameter":{{BuildNeutralBattleParameterJson(state)}},"snsScreenName":""}""");
    }

    private async Task<IResult?> HandleUserChangeStubAsync(HttpContext context, SessionState state, byte[] key)
    {
        var body = await ReadBodyAsync(context.Request);
        try
        {
            var plaintext = D2CCodec.Decode(body, key);
            using var document = JsonDocument.Parse(plaintext);
            var root = document.RootElement;
            // The DTO names the field "name"; older captures renamed it, so both spellings are accepted.
            if (TryGetString(root, "userName", out var newName) || TryGetString(root, "name", out newName))
            {
                state.UserName = newName;
                SaveUserState(state);
                _logger.LogInformation("Renamed user {UserId} to {UserName}", state.UserId, newName);
            }
            return OkJson(context, key, "{}");
        }
        catch (Exception ex)
        {
            _logger.LogWarning("Could not decode user change request: {Error}", ex.Message);
            return StatusError(context, key);
        }
    }

    private static bool TryGetString(JsonElement root, string propertyName, out string value)
    {
        value = "";
        if (!root.TryGetProperty(propertyName, out var prop) || prop.ValueKind != JsonValueKind.String) return false;
        var text = prop.GetString();
        if (string.IsNullOrWhiteSpace(text)) return false;
        value = text;
        return true;
    }

    // A name is only ever set by the player, through /tutorial/end. Until then the profile screens still have to
    // render something, so they get "Player" plus the low four digits of the id. It is display only: the stored
    // name stays empty, which is what keeps tutorialProgressStatus at 206 and the player on the name window.
    private static string CurrentUserName(SessionState state) =>
        state.HasName ? state.UserName : $"Player {DefaultNameSuffix(state.UserId)}";

    private static string DefaultNameSuffix(string userId) =>
        userId.Length <= 4 ? userId : userId[^4..];

    private static long CurrentDisplayUserId(SessionState state) =>
        long.TryParse(state.UserId, out var parsed) ? parsed : 1000001;

    // ResponseUserProfile, field for field. Frames and battle ranks mirror what BuildHomeJson already serves for the
    // same user (an empty userFrameList leaves the profile card without a frame to draw).
    private string BuildUserProfileJson(SessionState state, string userId, long displayUserId, string name) =>
        JsonSerializer.Serialize(new
        {
            userId,
            displayUserId,
            name,
            honorId = 6010000,
            userFrameList = new[]
            {
                new { battleRuleType = 1, frameId = 1 },
                new { battleRuleType = 2, frameId = 1 },
                new { battleRuleType = 3, frameId = 1 }
            },
            kickerId = state.KickerId,
            kickerCostumeId = state.KickerCostumeId,
            onlineFlag = true,
            battleFlag = false,
            officialFlag = false,
            languageCode = "es",
            followStatus = 0,
            newFlag = false,
            userBattleRankList = BuildBattleRankList(state),
            snsUserName = "",
            snsScreenName = "",
            snsUserImageUrl = ""
        });

    // ResponseUserBattleParameter: the deck the opponent screen would show, empty (no discs, no rule).
    private static string BuildNeutralBattleParameterJson(SessionState state) =>
        JsonSerializer.Serialize(new
        {
            battleRuleId = 0,
            kickerId = state.KickerId,
            kickerCostumeId = state.KickerCostumeId,
            discId1 = 0, discLevel1 = 0,
            discId2 = 0, discLevel2 = 0,
            discId3 = 0, discLevel3 = 0,
            discId4 = 0, discLevel4 = 0
        });

    // Same four rows BuildStartupJson emits, built from the live counters.
    private static string BuildUserItemListJson(SessionState state) =>
        JsonSerializer.Serialize(new[]
        {
            new { itemId = 1, amount = state.ItemJetCoins },
            new { itemId = 2, amount = state.ItemPaidJetCoins },
            new { itemId = 3, amount = state.ItemDiscForce },
            new { itemId = 4, amount = state.ItemKickPoints }
        });

    private static IResult OkJson(HttpContext context, byte[] key, string json)
    {
        context.Response.Headers["x-app-status-code"] = "0";
        return BinaryJson(json, key);
    }
}
