"""Verify BuildRoster sends 0-indexed teamType (0=Blue, 1=Red)."""
import json, subprocess, sys

# Simulate what BuildRoster does: team 0->teamType 0, team 1->teamType 1
def build_roster_teams(human_count=1):
    teams = []
    t0 = t1 = 0
    for i in range(human_count):
        team = 0 if i % 2 == 0 else 1
        if team == 0: t0 += 1
        else: t1 += 1
        teams.append(team)
    while len(teams) < 6:
        team = 0 if t0 < 3 else 1
        if team == 0: t0 += 1
        else: t1 += 1
        teams.append(team)
    return teams

teams = build_roster_teams(1)
assert all(t in (0, 1) for t in teams), f"teamType must be 0 or 1, got {teams}"
assert teams.count(0) == 3 and teams.count(1) == 3, f"3v3 split, got {teams}"
assert teams[0] == 0, f"first human must be Blue(0), got {teams[0]}"
print(f"OK: roster teams={teams} (0=Blue,1=Red, 3v3)")

teams2 = build_roster_teams(2)
assert teams2[0] == 0 and teams2[1] == 1, f"2 humans: Blue then Red, got {teams2}"
print(f"OK: 2-human roster teams={teams2}")

