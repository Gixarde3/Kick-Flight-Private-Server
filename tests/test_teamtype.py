"""Verify BuildRoster sends 0-indexed teamType (0=Blue, 1=Red) for a 4v4 roster.

Mirrors the team-assignment loop in BattleMatchmakingService.BuildRoster:
humans alternate Blue/Red by canonical order, then bots fill Blue to MaxPerTeam
before Red, for MaxPerTeam * 2 players total. Alternating the humans is what
keeps the teams balanced (never more than one human apart) for any number of
humans from 1 to 8, which is the whole of the "balance humans and bots" rule.
Keep MAX_PER_TEAM in sync with `public const int MaxPerTeam` in
BattleMatchmakingService.cs.
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


# Guard against the simulation drifting from the C# it mirrors.
src = SERVICE.read_text(encoding="utf-8")
m = re.search(r"public const int MaxPerTeam = (\d+);", src)
assert m, f"MaxPerTeam constant not found in {SERVICE}"
assert int(m.group(1)) == MAX_PER_TEAM, f"C# MaxPerTeam={m.group(1)} but test expects {MAX_PER_TEAM}"
assert 'public int teamType { get; set; } = 0;' in src, "MatchingPlayerBattleInfo.teamType default must be 0 (Blue)"
assert "(i % 2 == 0) ? 0 : 1" in src, "humans must keep alternating Blue/Red: that is what balances the teams"
assert "const int maxPerTeam = 4;" not in src, "the bot fill must use the shared MaxPerTeam constant"
assert "MaxPerTeam * 2" in src, "the fill target must be MaxPerTeam * 2 (8 slots for 4v4)"

for humans in range(1, TOTAL_PLAYERS + 1):
    teams = build_roster_teams(humans)
    assert len(teams) == TOTAL_PLAYERS, f"{humans} humans: expected {TOTAL_PLAYERS} players, got {len(teams)}"
    assert all(t in (0, 1) for t in teams), f"{humans} humans: teamType must be 0 or 1, got {teams}"
    assert teams.count(0) == MAX_PER_TEAM and teams.count(1) == MAX_PER_TEAM, \
        f"{humans} humans: {MAX_PER_TEAM}v{MAX_PER_TEAM} split, got {teams}"
    assert abs(teams[:humans].count(0) - teams[:humans].count(1)) <= 1, \
        f"{humans} humans: humans must be balanced, got {teams[:humans]}"
    assert teams[0] == 0, f"{humans} humans: first human must be Blue(0), got {teams[0]}"

# The 2-human case the emulator traces pin: Blue then Red, even split.
teams2 = build_roster_teams(2)
assert teams2[0] == 0 and teams2[1] == 1, f"2 humans: Blue then Red, got {teams2}"

print(f"OK: 1-human roster teams={build_roster_teams(1)} (0=Blue,1=Red, {MAX_PER_TEAM}v{MAX_PER_TEAM})")
print(f"OK: 2-human roster teams={teams2}")
print(f"OK: 3-human roster teams={build_roster_teams(3)} (humans balanced, bots top both sides up)")
print(f"OK: all {TOTAL_PLAYERS} human counts split {MAX_PER_TEAM}v{MAX_PER_TEAM} with balanced humans")
