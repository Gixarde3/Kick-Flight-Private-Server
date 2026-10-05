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
        return index switch
        {
            0 => CrystalRuleId,
            1 => FlagRuleId,
            _ => RapidBallRuleId
        };
    }

    public static bool IsRankedRule(int ruleId) =>
        ruleId is CrystalRuleId or FlagRuleId or RapidBallRuleId;

    public static string BuildScheduleJson()
    {
        var rows = new List<object>(24);
        var sortOrderByMode = new int[ModesPerCycle];
        for (var hour = 0; hour < 24; hour++)
        {
            var modeIndex = hour % ModesPerCycle;
            sortOrderByMode[modeIndex]++;
            var nextHour = (hour + 1) % 24;
            var endTime = $"{nextHour:00}:00:00";
            rows.Add(new
            {
                id = hour + 1,
                seasonMatchBattleRuleType = modeIndex + 1,
                groupId = 1,
                startTime = $"{hour:00}:00:00",
                endTime,
                battleRuleId = modeIndex switch
                {
                    0 => CrystalRuleId,
                    1 => FlagRuleId,
                    _ => RapidBallRuleId
                },
                sortOrder = sortOrderByMode[modeIndex]
            });
        }

        return JsonSerializer.Serialize(rows);
    }
}
