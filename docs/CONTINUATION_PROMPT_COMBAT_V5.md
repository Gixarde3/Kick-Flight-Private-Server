# Continuation — Rapid Ball / menus / learnings (2026-09-19, session 5) — READ FIRST

Read this, then `docs/RAPID_BALL_PLAN.md` (full RE notes for the ball rule), then
`docs/CONTINUATION_PROMPT_COMBAT_V4.md` (still-open combat issues: Owlbert, Buzzy Big, …) and
`docs/COMBAT_MASTERS_FILL_IN.md`. Repo: `Kick-Flight-Private-Server` (.NET 8, branch `tanuki-discs`); RE material in
`../Kick-Flight-Assets` (`server_revival_analysis/il2cpp/dump.cs`, `stringliteral.json`, `base.apk`).

## Rules from the user (unchanged)

* The user stages and commits on GitHub themselves — never `git add` / `git commit` / stash / revert.
* No subagents for the ADB loop. Tuning numbers come from the user's in-game feedback.
* Feature workflow used this session and to be kept: Claude plans (`docs/<FEATURE>_PLAN.md` with an acceptance
  checklist) → DeepSeek implements via the `deepseek` skill (`~/.claude/skills/deepseek/run.ps1`, launch from
  PowerShell, `-Ping` first; rounds land in `handoff/round-<n>/`, gitignored) → Claude vets the diff file by
  file and validates on the emulator over ADB. Data mistakes in the spec are fixed by hand, not by a new round.

## What happened this session

Rapid Ball (Bola rápida, `battleRuleType 3`) plays end to end vs bots: goal guardians spawn and die, bots carry
and score balls (a 0–9 loss while idle), the score HUD and result board work, `/battle/end` + `/battle/result`
are sent, back to Home. Everything is in the working tree, uncommitted:

* `src/KickFlight.BootstrapApi/DemoSessionApi.cs`: `BattleRule`, `RegularMatchBattleSchedule`,
  `GuardianParameter` now come from `config/masters_battle_rule.json`, `masters_regular_match_battle_schedule.json`,
  `masters_guardian_parameter.json` (inline JSON kept only as fallback); new tables `BattleRuleRapidBallScore`
  (`masters_battle_rule_rapid_ball_score.json`) and `BattleRuleFlagFlightScore`
  (`masters_battle_rule_flag_flight_score.json`); `/battle/start` decodes the body's `battleRuleId` and returns
  `guardianParameter.id 2` for rule type 3 (log line `Handled /battle/start … rule= type= guardianParameter=`).
* `tests/KickFlight.BootstrapApi.Tests/HarnessTests.cs`: `Rapid_ball_masters_are_served_with_goal_guardians`
  (25 tests pass). `.gitignore`: `handoff/`.
* Data: battle-rule rows 3/4 `guardianAmount 1`; `GuardianParameter` row 2 = `hp 3000` (goal guard = 6 × hp =
  18 000 HP); score rows ids 3/4 (rapid) and 2 (flag).
* Saves `data/users/1000001.json` / `1000002.json` show small coin/KP deltas from the test battles and the live
  server — keep or restore as you prefer (they are live data; the phone plays as 1000001).

## Learnings (must-know, cost hours)

1. **Per-rule master rows are keyed by row `id`, not by a column.** `BallShootRuleController.GetScore` does
   `MasterManager.BattleRuleRapidBallScoreMaster.get_Item(BattleRuleInfo.BattleRuleId)` (dictionary by
   `MasterData.Id`) with a hard-coded fallback to id 3; a missing row → NRE every frame
   (`PlayerParameterModel.UpdateParameter`) and, at match end, `RuleControllerBase.CalcScore` NREs forever:
   the client sits on "Cargando…" and never sends `/battle/end`. Same for `BattleRuleScrambleScore` (id 1) and
   `BattleRuleFlagFlightScore` (id 2). Before adding any table, disassemble the getter that reads it
   (`python scripts/re/a64dis.py <rva> <n>`) and check whether it is `get_Item(key)` (by id) or
   `Find(predicate)` (by column).
2. **Master table names are `ClassName` minus "Master"** (`MasterManager.CreateAll` instantiates all 100+ masters
   unconditionally; `LoadAll` reads each by name). A served table only reaches the client when the master hash
   changes: the client then shows "Download Update … Data size: 4.73KB" on the title screen and fetches only the
   changed tables (`GET /demo-master/<Name>` in the server log). `DemoSessionApi` is constructed lazily, so
   "Master version … (68 tables)" appears in the log on the first request, not at startup.
3. **Guardians.** `GameManager.CreateGuardian` spawns `BattleRule.guardianAmount` per team at the field's guardian
   points (`fld00101_1` and `_3` have two, `_2` none). Type from `RuleCtr.GetUseGuardianType()`: crystal =
   `CrystalStock` (HP = deposited crystals × `GuardianParameter.hp`), ball = `Revivalable` (prefab
   `NPC/GuardianRevivalable`, HP = 6 × hp, dead 15 s, auto-heal after 10 s idle). The row is chosen by the id in
   `/battle/start`'s `guardianParameter` (`GuardianParameterMaster.Find(id)`); `BattleStartRequestData` carries
   `battleId` + `battleRuleId`, so the server can pick per rule. Model/laser come from `Guardian` row 1 for both.
4. **Field variants are client data.** `FieldManager.InitializeAsync(fieldId)` loads
   `field/fielddata/fld<id>_<ruleType>` and `field/itemdata/ite<id>_<ruleType>`; ball spawn points =
   `GetItemPositions()` from the itemdata bundle (count = `GetItemCountMax`). Fields with all three variants:
   101, 301, 401, 601, 701, 901 (`BattleRuleField` still maps everything to 101).
5. **Mode-select window semantics** (`BattleRuleSelectCellView.UpdateTimeText`): white cell + `Reglas` +
   "Faltan Xh" = OPEN, X h *remaining* in the window; grey cell, no `Reglas`, "En X h" = closed, opens in X h;
   Cristalmanía (regular + rule type 1) never shows a time. The Home panel's "Quedan" line stays blank —
   cosmetic. `RegularMatchBattleScheduleMaster.GetRegularMatchSchedule` (RVA `0x16CF934`): group =
   `GetJstElapsedDay % maxGroupId[seasonRuleType] + 1`, rows filtered by `seasonMatchBattleRuleType`
   (the `-1` fallback result is discarded — client bug, harmless while `GetCurrentSeasonRuleMaster()` is null),
   open when `TimeUtil.InRange(today@start, today@end, JST) == 0`; `end < start` → +1 day; `HH:mm:ss` or full
   datetimes both parse (only H/M/S used). Changing the table pops a one-time "schedule changed" notice on
   Home (`26 15:00:00-09` / Combate de clasificación / Combate normal → `Aceptar` 540,1455).
6. **Closed rules are still playable**: the client sends whatever `battleRuleId` is selected.
7. **After a server restart the client's old access token maps to `default-user`**, so the emulator showed
   `Gixarde3` (1000001) instead of `Player 0002` (1000002) — pre-existing behaviour, harmless for testing.
8. RE workflow that paid off: `scripts/re/a64dis.py <rva> <n>` (filter `\[sp`, `12141ec`, `11f7160`, `1223ed8`
   noise), `scripts/re/xref.py <rva>` for callers, `stringliteral.json` for table/localize keys, and scanning a
   class's method RVAs for `bl MasterManager$$get_*` to list the tables a feature reads (snippet in the session:
   capstone over each method until `ret`). `0x12141ec` = il2cpp null-check throw, so `cbnz xN → ok / bl 0x12141ec`
   tells you exactly which object was null.

## Operating the client (emulator `KickFlight_A15`, taps in 1080×1920)

Boot: `%LOCALAPPDATA%\Android\Sdk\emulator\emulator.exe -avd KickFlight_A15 -memory 6144 -no-snapshot-load
-no-boot-anim` (or `start-client.bat`); package `jp.grenge.kickflight`, cache already seeded (5188 files).
Launch: `adb shell am force-stop jp.grenge.kickflight; adb shell monkey -p jp.grenge.kickflight -c
android.intent.category.LAUNCHER 1`. Screenshots at 720 px: `RUN=<dir> bash .local/shot.sh <name>`.
Logcat: `adb logcat -c` before, `adb logcat -d > file` after; aggregate with
`grep "E Unity" file | sed 's/.*E Unity *: //' | grep "Exception\|  at " | sort | uniq -c | sort -rn`
("Unable to find libc" once per launch is benign).

| Screen | Action | Tap | Wait |
|---|---|---|---|
| Title | TAP START | `780 858` | ~20 s after launch |
| "Download Update" (masters changed) | Download | `765 1140` | ~20 s |
| Schedule-changed notice / modal | Aceptar | `540 1455` | |
| Home | Combate (start match) | `818 1239` | |
| Home | mode switch (arrows icon on the rule card) | `972 800` | |
| Mode select | Cristalmanía / Vuelo de banderas / Bola rápida | `540 728` / `540 945` / `540 1155` | |
| Mode select | Aceptar | `540 1385` | |
| Rules window (first Combate on a new rule, 5 blank pages) | next ▸ ×5, then ✕ | `978 990` ×5, `540 1790` | then Combate again |
| Matching | (automatic) 25 s bot fill + 2 s hold | | GameScene ~30 s after Combate |
| Result board | Aceptar | `540 1810` | |
| Level-bonus popup | Aceptar → Volver a Inicio | `540 1265` → `430 1810` | |

Server: `start-server.bat` kills the old dotnet on :18080, rebuilds Release, runs with the log teed to
`.local/session-logs/server-<stamp>.log`. From a tool, run it detached:
`Start-Process cmd -ArgumentList '/c','"<repo>\start-server.bat"'` and poll `http://127.0.0.1:18080/health/ready`
(~50 s). A table edit in `config/masters_*.json` needs only this restart (the client re-downloads on next launch).
The user's phone reaches the same server over `kickflightsg.ddns.net`, so restarts interrupt it.

## Open items

* Rapid Ball tuning by feel: goal-guardian HP (`masters_guardian_parameter.json` row 2), score values
  (`masters_battle_rule_rapid_ball_score.json`), whether the goal guardian's laser hurts players (same
  `Guardian`/`Skill`/`SkillCollision` rows as the crystal turret), whether the human can score (only bots were
  observed scoring — the emulator player stood still).
* Vuelo de banderas: the score table is now served (id 2) but the mode was not played this session.
* Ranked "Combate de clasificación" = rule 4 (Bola rápida, matchType 2) — untested; `/battle/result` still
  echoes `battleRuleType 1`.
* Home panel blank "Quedan" time (cosmetic); rules-window pages are blank (missing UI bundle).
* Everything in V4's "BREAKING ISSUES" (Owlbert drones/smog, Buzzy Big hammer) and "Open / lower priority".
