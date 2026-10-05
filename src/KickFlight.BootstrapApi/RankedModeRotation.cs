using System.Text.Json;

namespace KickFlight.BootstrapApi;

/// <summary>
/// The ranked mode rotates in global UTC hour blocks. The daily client schedule is evaluated in JST, which is
/// UTC+9; because both the UTC day and this three-mode sequence are divisible by three, their hour slots align.
/// </summary>
public static class RankedModeRotation
{
    public const int CrystalRuleId = 7;
    public const int FlagRuleId = 8;
    public const int RapidBallRuleId = 4;
    private const int ModesPerCycle = 3;

    public static int RuleIdAt(DateTimeOffset utcNow)
    {
        var seconds = utcNow.ToUnixTimeSeconds();
        var hour = seconds >= 0 ? seconds / 3600 : (seconds - 3599) / 3600;
        // Normalize modulo into [0, ModesPerCycle), including instants before the Unix epoch.
        var index = (int)((hour % ModesPerCycle + ModesPerCycle) % ModesPerCycle);
        return RuleIdForMode(index);
    }

    public static bool IsRankedRule(int ruleId) =>
        ruleId is CrystalRuleId or FlagRuleId or RapidBallRuleId;

    /// <summary>
    /// The served RankerMatchBattleSchedule: one row per JST hour for each seasonMatchBattleRuleType group.
    /// </summary>
    /// <remarks>
    /// BattleScheduleUtil.GetBattleViewRuleInfo asks for the ranker schedule of the in-date season rule. With no
    /// season rule in date it passes -1, and RankerMatchBattleScheduleMaster.GetRankerMatchSchedule filters the
    /// rows down to <c>seasonMatchBattleRuleType == -1</c> (the predicate compares the raw value, -1 included).
    /// Those rows are therefore the rotation the client actually uses, so they must be present and cover every
    /// hour; the 1/2/3 rows are kept for the in-season path and are harmless otherwise.
    ///
    /// The window format matches the client: the start and end of each row are combined with today's JST date and
    /// TimeUtil.InRange keeps <c>start &lt;= now &lt; end</c> (end exclusive). When the end hour is earlier than the
    /// start hour GetRankerMatchSchedule adds one day to the end before the check, so the 23:00 row "23:00:00" ->
    /// "00:00:00" is really [23:00, 00:00 next day): the 24 hourly windows partition the day with no gap and no
    /// overlap. Using "23:59:59" there would leave the last second of the day uncovered.
    /// </remarks>
    public static string BuildScheduleJson()
    {
        var rows = new List<object>(48);
        var sortOrderByMode = new int[ModesPerCycle];
        for (var hour = 0; hour < 24; hour++)
        {
            var modeIndex = hour % ModesPerCycle;
            sortOrderByMode[modeIndex]++;
            var nextHour = (hour + 1) % 24;
            var startTime = $"{hour:00}:00:00";
            var endTime = $"{nextHour:00}:00:00";
            var battleRuleId = RuleIdForMode(modeIndex);
            // Ids order the client's list (GetRankerMatchSchedule sorts by MasterData.Id), so the -1 rows use a
            // second, disjoint id block and stay in hour order inside their own group.
            rows.Add(new
            {
                id = hour + 1,
                seasonMatchBattleRuleType = modeIndex + 1,
                groupId = 1,
                startTime,
                endTime,
                battleRuleId,
                sortOrder = sortOrderByMode[modeIndex]
            });
            rows.Add(new
            {
                id = hour + 25,
                seasonMatchBattleRuleType = -1,
                groupId = 1,
                startTime,
                endTime,
                battleRuleId,
                sortOrder = hour + 1
            });
        }

        return JsonSerializer.Serialize(rows);
    }

    private static int RuleIdForMode(int modeIndex) => modeIndex switch
    {
        0 => CrystalRuleId,
        1 => FlagRuleId,
        _ => RapidBallRuleId
    };
}
