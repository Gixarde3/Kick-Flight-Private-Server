# Flag Flight (Vuelo de banderas, `battleRuleType` 2) — RE notes and fix (2026-09-19)

Goal: Vuelo de banderas plays end to end vs bots: each team's flag spawns at the far side of the arena, players
pick it up by flying through it and score by carrying it to their own base; bots do the same.

## Symptom

Match loads on `fld00101_2`, both flags show on the minimap, the score HUD shows `3 2 1 | 1 2 3`, the timer runs,
but nobody (human or bot) can pick up a flag. Bots hover around their flag, never fight, and the match ends 0–0
(`DRAW`, everyone 100 pt / 0 0 0). **No exception in logcat** — only the benign
`Look rotation viewing vector is zero` from `FlagPositionIconPresenter.Bind`.

## Root cause (server data)

`config/masters_battle_rule.json` row 2 was served with `flagAmount: 3`. The client uses that column in exactly one
place (`xref.py 0x18955d0`): `FlagFlightRuleController.GetItemCountMax` (RVA `0x15F5544`) returns
`BattleRule.flagAmount * 2` — it is *flags per team*, not goals-to-win. `ItemManager.get_ItemCountMax`
(`0x15133A0`) reads the row by `BattleRuleInfo.BattleRuleId` and the value drives:

* `ItemManager.RegisterItem` (`0x1518010`): `for (i = 0; i < ItemCountMax && i < PropertyItemKeys.Count; i++)` builds an
  `ItemInfo` per index from the room properties → 6 infos, while `FlagFlightRuleController.GetItemInitializeProperties`
  (`0x15F5164`) only writes properties for `positions.Length` = 2 flags (itemdata `ite00101_2`; flag *i* gets
  `TeamType = i % 2`, Visible = true).
* `ItemManager.RegisteredItemAsync` (`0x15192D4`): `maxCount = _itemInfos.Count` (6), then
  `WaitUntil(ObjectManager.GetItems().Count >= maxCount)` → never true with 2 `Flag` objects → `IsRegistered` stays
  false.
* `ItemManager.UpdateCheckOwnership` (`0x151675C`, the per-frame pickup loop) starts with
  `if (IsPlaybackSession || !IsRegistered) return;` → no pickup, ever, for anyone, silently.

Fix: `flagAmount: 1` in `config/masters_battle_rule.json` row 2 (and the inline fallback in
`src/KickFlight.BootstrapApi/DemoSessionApi.cs`). Verified by the user on the phone: flags can be picked up and the
mode plays. `FLAG_COUNT_MAX = 2` in `FlagFlightRuleController` confirms two flags per match.

## Pickup rules as implemented by the client (for reference — all client side, nothing for the server to do)

`UpdateCheckOwnership` for each player with `IsMine` (patched true offline), `DisenableItemGetTime <= 0`,
`!IsDead()`, and `RuleCtr.CanGettingItem(player)`; for each item with `!IsMove && IsVisible`; a player may take an
item when `player.TeamType == info.TeamType` or `info.TeamType == Invalid`, or (enemy-team item) only if it has
already left its initial position; nearest item within `sqrt(GetItemSqrDistance())` = 6.5 u wins, then
`SetOwnerToPlayer` → room properties → `RefreshItem`.

`FlagFlightRuleController.CanGettingItem` (`0x15F5588`): `GetCrystalCount == 0` (holds nothing), not in
`BlowOff`/`PullIn`/`Dead`/`Revival`, no `ConditionType.Panda`, and not in `PlayerStateFlagStand` (the flag-planting
state at the base). Drops on blow-off/knockback come from `ExecuteDropItemActionForBlowOffPlayer` (slot 32) and on
death from `ExecuteDropItemActionForDeadPlayer`; the WARP-disc drop and the auto-score near the base are also
client logic (`GameUpdate` tracks `_isRelease*TeamFlag` = flag just returned to its pedestal, for notifications).

Enemy flag pickup semantics: your own team's flag (`TeamType == yours`) spawns at the far side; the enemy can only
grab it after it has been moved off the pedestal (to push it back — `flagMoveBackScore`).

## Other tables the mode reads

* `BattleRuleFlagFlightScore` row **id 2** (`config/masters_battle_rule_flag_flight_score.json`) — looked up by row
  id like the other `BattleRule*Score` tables (see `RAPID_BALL_PLAN.md`); already served.
* `BattleRule` row 2: `guardianAmount 0` (no guardians in this mode), `flagAmount 1`.
* `/battle/start` answers `guardianParameter.id 1` for rule type 2 (unused, no guardians).

## Open items

* Bots did not attack each other in the broken state; re-check that they fight/defend now that they carry flags.
* Score values in `masters_battle_rule_flag_flight_score.json` untuned (`baseScore 100, goalCountScore 100,
  flagMoveScore 10, dropCountScore 5, flagMoveBackScore 10, kill 50, killAssist 25, assist 25, specialSkill 30,
  winScoreCorrection 1.5`).
* Overtime (`EX_TME = 90`, `IsExtensionCheck`) not observed yet.
* `FlagPositionIconPresenter` "Look rotation viewing vector is zero" warning at UI init (cosmetic, spams once per
  player at match start).

## Diagnostics notes

* The HONOR phone (MTN-NX1) ships with `persist.log.tag = S`, so third-party app lines never reach logcat.
  `adb shell setprop log.tag.Unity V` (also `persist.log.tag.Unity`, `KFDIAG`, `AndroidRuntime`, `DEBUG`, `CRASH`)
  is settable from the shell and re-enables them per tag; `persist.log.tag` itself is not writable.
* Wireless ADB on the phone: the pairing port (`192.168.68.50:42419`) can refuse connections while the mDNS entry
  `adb-AUYF6R5A24002889-…._adb-tls-connect._tcp` still works — use it as `-s`.
* Emulator repro: mode switch `972,800` → Vuelo de banderas `540,945` → Aceptar `540,1385` → Combate `818,1239`
  (first time: 4-page rules window, next `978,990` ×3, close `540,1790`, Combate again).
