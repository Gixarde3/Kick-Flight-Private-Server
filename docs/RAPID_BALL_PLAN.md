# Rapid Ball (Bola rápida, `battleRuleType` 3) — feature plan (2026-09-19)

Goal: Bola rápida is selectable from the Home mode switch and a solo match vs bots plays end to end on the
client: GameScene renders the ball variant of the arena, balls spawn at the field's own spawn points, each goal
holds a revivable Guardian (6 HP steps) that must be destroyed before the team can score, bots play the mode,
the match ends normally and the result flow returns to Home.

## What the client does on its own (verified 2026-09-19 on the emulator, no server changes)

Rule logic is 100 % client side (`BallShootRuleController`, master client = the local player). With the current
server the mode already *runs*:

* Home → mode switch (native tap `972,800`) → `Bola rápida` cell (`540,1155`) → `Aceptar` (`540,1385`) → the
  panel shows "Bola rápida / Quedan" (blank time). First time, `Combate` opens a 5-page rules window (blank pages,
  next arrow `978,990` ×5, close `540,1790`), then `Combate` again.
* `/battle/entry` arrives with `battleRuleId 3`, matchmaking + `/battle/start` run unchanged, GameScene loads
  `field/fielddata/fld00101_3` + `field/itemdata/ite00101_3` (the rule-3 variants: `FieldManager.InitializeAsync`
  picks them by `BattleRuleType`; ball spawn points = `FieldManager.GetItemPositions()` from the itemdata bundle,
  `BallShootRuleController.GetItemCountMax` = their count, so "each map has its own spawn points" is client data),
  minimap shows both `G` goals, bots move and fight, timer runs (`.local`-style screenshots in the session).
* All assets are in `config/resources/catalog.json` and downloaded: `gimmick/gm_003` (ball goal), `gm_004` (move
  ball), `item/it_003/004/005` (low/middle/high ball), `npc/np_001` (+animator), all `fld/ite *_3` variants for
  fields 101/301/401/601/701/901. Prefab `NPC/GuardianRevivalable` is in the APK (`GuardianTypeExtensions`).

## Blockers found (server data only)

1. **`BattleRuleRapidBallScore` master is not served.** `BallShootRuleController.GetScore` reads
   `MasterManager.BattleRuleRapidBallScoreMaster[battleRuleId]` → NRE every frame from
   `PlayerParameterModel.UpdateParameter` (score HUD stuck at `0pt`, 2 573 NREs in one match) and at match end
   from `RuleControllerBase.CalcScore` ← `GameManager.BattleEnd` → the client loops on "Cargando…" forever and
   never sends `/battle/end`. Logcat: `.local/…/logcat-rb2.txt` pattern
   `at Colorful.BallShootRuleController.GetScore`. Same shape exists for flag mode (`BattleRuleFlagFlightScore`).
2. **No guardians in the goals.** `GameManager.CreateGuardian` spawns `BattleRule.guardianAmount` NPCs per team
   (type from `RuleCtr.GetUseGuardianType()` = `Revivalable`); rules 3/4 are served with `guardianAmount 0`.
   `FLD00101_3` has two guardian points (V3 doc), so `1` is right. Revivable guardian max HP =
   `MAX_HP_STEP_AMOUNT (6) × GuardianParameter.hp` (`NPCRevivalableGuardian.SetMaxHP`), dead time 15 s,
   auto-heal after 10 s idle. With row 1 (`hp 8000`) that is 48 000 ≈ 20 basic hits — too tanky for a goal
   guard, so serve a second `GuardianParameter` row for the ball rule and pick it in `/battle/start`
   (`BattleStartRequestData` carries `battleId` + `battleRuleId`; the client resolves the row with
   `GuardianParameterMaster.Find(id == response.guardianParameter.id)` in `CallbackBattleStartSuccess`).
3. **Schedule display — not a bug (resolved 2026-09-19).** "Faltan 19h" on a white cell with a `Reglas` button
   is the *remaining time of the open window* (`BattleRuleSelectCellView.UpdateTimeText`, `InSession` →
   `common.lastHour` = "Faltan {0}h"; our windows end 23:59:59 JST, and 04:45 JST + 19 h ≈ midnight). A really
   closed rule renders grey, no `Reglas`, with `common.nextOpenHour` = "En {0} h" (verified by giving Vuelo de
   banderas a `10:00:00`–`10:00:01` window: it showed "En 5 h" at 05:00 JST while Bola rápida kept
   "Faltan 19h"). Cristalmanía never shows a time because regular + `battleRuleType 1` is special-cased as
   always available. All three regular rules are open all day with the served rows; the Home panel's blank
   "Quedan" line is the only cosmetic leftover. For the record, `GetRegularMatchSchedule` (RVA `0x16CF934`):
   `_dic[(GetJstElapsedDay % maxGroupId[seasonRuleType]) + 1]` (keyed by `groupId`), rows filtered by
   `seasonMatchBattleRuleType == seasonRuleType` (the fallback `-1` FindAll result is discarded — client bug,
   harmless while `GetCurrentSeasonRuleMaster()` is null and `-1` is passed), open when
   `TimeUtil.InRange(today@startTime, today@endTime, jst) == 0`, `end < start` → end +1 day; times are
   `HH:mm:ss` or full datetimes (only H/M/S are used). Changing the table pops the "schedule changed" notice
   (`26 15:00:00-09` / Combate de clasificación / Combate normal) once on the next Home.

## Implementation (DeepSeek round; checklist = "Acceptance checklist" below)

Scope: `src/KickFlight.BootstrapApi/DemoSessionApi.cs`, new `config/masters_*.json`, one test in
`tests/KickFlight.BootstrapApi.Tests/HarnessTests.cs`. Nothing else (no matchmaking, no APK, no scripts).

1. Move the inline `BattleRule`, `RegularMatchBattleSchedule` and `GuardianParameter` tables to
   `config/masters_battle_rule.json`, `config/masters_regular_match_battle_schedule.json`,
   `config/masters_guardian_parameter.json`, loaded with the existing `LoadJson(contentRoot, path, fallback)`
   helper (fallback = today's inline JSON). Content changes:
   * `masters_battle_rule.json`: rows 3 and 4 get `"guardianAmount": 1`; everything else byte-identical.
   * `masters_guardian_parameter.json`: `[{"id":1,"matchType":1,"rank":1,"hp":8000,"attack":6000},
     {"id":2,"matchType":1,"rank":1,"hp":3000,"attack":6000}]` (row 2 = ball goal guard, 6 × 3000 = 18 000 HP ≈
     7 basic hits; tuning is the user's).
   * `masters_regular_match_battle_schedule.json`: the six current rows unchanged.
2. Serve two new tables from JSON: `BattleRuleRapidBallScore` (`config/masters_battle_rule_rapid_ball_score.json`,
   rows for `battleRuleId` 3 and 4) and `BattleRuleFlagFlightScore`
   (`config/masters_battle_rule_flag_flight_score.json`, row for `battleRuleId` 2). Columns per il2cpp dump:
   * RapidBall: `id, battleRuleId, baseScore, pointScore, getBallScore, getHighBallScore, dropBallScore,
     dropHighBallScore, goalOpenContributionScore, goalPointContributionScore, killCountScore,
     killAssistCountScore, assistCountScore, specialSkillCountScore, winScoreCorrection`
     → `100, 100, 10, 30, 5, 15, 50, 50, 50, 25, 25, 30, 1.5`.
   * FlagFlight: `id, battleRuleId, baseScore, goalCountScore, flagMoveScore, dropCountScore, flagMoveBackScore,
     killCountScore, killAssistCountScore, assistCountScore, specialSkillCountScore, winScoreCorrection`
     → `100, 100, 10, 5, 10, 50, 25, 25, 30, 1.5`.
3. `HandleBattleStartAsync`: decode the body the way `HandleBattleEntryAsync` does, read `battleRuleId`, look up
   its `battleRuleType` in the loaded battle-rule JSON, answer `guardianParameter.id = 2` for `battleRuleType 3`
   and `1` otherwise (rank 1, fieldId 101 unchanged); log the rule id/type. Undecodable body → rule 1 behaviour.
4. Test: `/download/master` lists `BattleRuleRapidBallScore` and `BattleRuleFlagFlightScore`; decrypting
   `/demo-master/BattleRule` gives `guardianAmount 1` for ids 3 and 4; `/demo-master/GuardianParameter` has id 2.

## Acceptance checklist

- [ ] `dotnet build -c Release` clean; `dotnet test tests/KickFlight.BootstrapApi.Tests` passes (22 + new).
- [ ] `config/masters_battle_rule.json`, `masters_regular_match_battle_schedule.json`,
      `masters_guardian_parameter.json`, `masters_battle_rule_rapid_ball_score.json`,
      `masters_battle_rule_flag_flight_score.json` exist, parse, have the columns above; battle-rule rows 3/4
      `guardianAmount 1`, all other battle-rule values identical to the previous inline table.
- [ ] `DemoSessionApi` serves `BattleRuleRapidBallScore` and `BattleRuleFlagFlightScore`; `BattleRule`,
      `RegularMatchBattleSchedule`, `GuardianParameter` come from the JSON files with the old inline JSON as
      fallback (`LoadJson`).
- [ ] `/battle/start` returns `guardianParameter.id 2` for a rule whose `battleRuleType` is 3, `1` otherwise.
- [ ] No edits outside the scope list; no new dependencies; no TODO/stub code.

## Result (2026-09-19, emulator `KickFlight_A15`, server rebuilt from this tree)

DeepSeek round 1 delivered everything in scope (`handoff/round-1/report.md`); two data corrections were made
by hand afterwards:

* **Score rows are looked up by row id, not by the `battleRuleId` column**: `BallShootRuleController.GetScore`
  calls `TMasterBase.get_Item(BattleRuleInfo.BattleRuleId)` and falls back to `get_Item(3)`; with rows id 1/2
  the NRE stayed (2 217 per match). `masters_battle_rule_rapid_ball_score.json` now has ids 3 and 4 and
  `masters_battle_rule_flag_flight_score.json` id 2 (same convention as `BattleRuleScrambleScore` id 1).
* The schedule table is unchanged (see blocker 3 — it was never broken).

Verified in one full solo match (`Bola rápida`, rule 3): `/battle/start … rule=3 type=3 guardianParameter=2`;
GameScene on `fld00101_3`; "守護者被打敗了！" (goal guardian defeated) notification; bots carry balls (ball count
badges on the roster) and score — final **0–9**; score HUD no longer NREs (`adb logcat` after the match: only
the benign `Unable to find libc`); result board shows the Rapid Ball columns (goals / kills / balls) with points
from the new table (idle human = `baseScore` 100); `/battle/end` and `/battle/result` handled; level-bonus popup
→ `Volver a Inicio` → Home. Tests: 25/25.

Not yet tuned/checked by feel: goal-guardian HP (row 2, 6 × 3000), the score-table values, and whether the ball
guardian's laser hits players (same `Guardian`/`Skill` rows as the crystal turret).

## Validation procedure on the emulator

1. Restart the server (`start-server.bat` or the manual command in `CONTINUATION_PROMPT_COMBAT_V4.md`).
2. `adb shell am force-stop jp.grenge.kickflight` → launch → START (`780,858`) → mode switch (`972,800`) →
   Bola rápida (`540,1155`) → Aceptar (`540,1385`) → Combate (`818,1239`) (+ rules window the first time).
3. Expect: GameScene, guardian in each goal with a 6-step HP bar, balls visible on the field / minimap, score HUD
   shows points (no `GetScore` NREs in `adb logcat -d | grep "E Unity"`), a goal after the guardian dies,
   match end → result screen → `/battle/end` + `/battle/result` in the server log → Home.
4. Table tuning needs only a server restart (`start-server.bat`); the client re-downloads the changed tables
   on the next launch (the "Download Update" prompt, a few KB) and shows the schedule-changed notice once if
   `masters_regular_match_battle_schedule.json` changed.

## Out of scope / later

* Other fields for the ball rule (`BattleRuleField` maps everything to 101; 301/401/601/701/901 have `_3` data).
* Team (`Equipo`) matchmaking, ranked (`rule 4`) rewards, `/battle/result` echoing the played rule type.
* Rules-window images (blank pages — missing UI bundle, cosmetic).
