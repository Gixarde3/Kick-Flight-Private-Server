"""Verify BuildRoster sends 0-indexed teamType (0=Blue, 1=Red) for a 4v4 roster.

Mirrors the team-assignment loop in BattleMatchmakingService.BuildRoster:
humans alternate Blue/Red by entry order, then bots fill Blue to MAX_PER_TEAM
before Red, for MAX_PER_TEAM * 2 players total. Keep MAX_PER_TEAM in sync with
`const int maxPerTeam` in BattleMatchmakingService.cs.
"""
import re
from pathlib import Path

MAX_PER_TEAM = 4
TOTAL_PLAYERS = MAX_PER_TEAM * 2
SERVICE = Path(__file__).resolve().parent.parent / "src" / "KickFlight.BootstrapApi" / "BattleMatchmakingService.cs"


def build_roster_teams(human_count=1):
    teams = []
    t0 = t1 = 0
    for i in range(human_count):
        team = 0 if i % 2 == 0 else 1
        if team == 0: t0 += 1
        else: t1 += 1
        teams.append(team)
    while len(teams) < TOTAL_PLAYERS:
        team = 0 if t0 < MAX_PER_TEAM else 1
        if team == 0: t0 += 1
        else: t1 += 1
        teams.append(team)
    return teams


# Guard against the simulation drifting from the C# constant it mirrors.
src = SERVICE.read_text(encoding="utf-8")
m = re.search(r"const int maxPerTeam = (\d+);", src)
assert m, f"maxPerTeam constant not found in {SERVICE}"
assert int(m.group(1)) == MAX_PER_TEAM, f"C# maxPerTeam={m.group(1)} but test expects {MAX_PER_TEAM}"
assert 'public int teamType { get; set; } = 0;' in src, "MatchingPlayerBattleInfo.teamType default must be 0 (Blue)"

teams = build_roster_teams(1)
assert all(t in (0, 1) for t in teams), f"teamType must be 0 or 1, got {teams}"
assert len(teams) == TOTAL_PLAYERS, f"expected {TOTAL_PLAYERS} players, got {len(teams)}"
assert teams.count(0) == MAX_PER_TEAM and teams.count(1) == MAX_PER_TEAM, f"{MAX_PER_TEAM}v{MAX_PER_TEAM} split, got {teams}"
assert teams[0] == 0, f"first human must be Blue(0), got {teams[0]}"
print(f"OK: roster teams={teams} (0=Blue,1=Red, {MAX_PER_TEAM}v{MAX_PER_TEAM})")

teams2 = build_roster_teams(2)
assert teams2[0] == 0 and teams2[1] == 1, f"2 humans: Blue then Red, got {teams2}"
assert teams2.count(0) == MAX_PER_TEAM and teams2.count(1) == MAX_PER_TEAM, f"2-human split must stay even, got {teams2}"
print(f"OK: 2-human roster teams={teams2}")
