# Continuation prompt — combat round 8+ (written 2026-09-20 evening, after round 7)

Read this first, then `docs/CONTINUATION_PROMPT_COMBAT_V6.md` (rounds 1–7 detail), `AGENTS.md` (rules, DIAG builds,
round-7 learnings) and `scripts/re/README.md` (RE tools, cave rules, dead-body map). Everything below is uncommitted;
the user stages and commits on GitHub themselves — **never** `git add` / `git commit` / stash / checkout / revert.

## Working rules (unchanged, do not relearn them)

* The user runs `start-server.bat` and the emulator/phone; processes Claude starts get reaped. Claude may `adb install`,
  `adb logcat -d`, read logs, build APKs, edit code/config. Don't test gameplay yourself unless told; don't start the
  shell/emulator when told not to.
* Verify with the game's own evidence (logcat, KFDIAG probes, disassembly), not with assumptions. Say when something is
  inferred and not observed.
* Config-tunable things → point the user at the balance WebUI (`start-balance.bat [lan]`, `tools/balance/`); gameplay
  code / asm → do it yourself. DeepSeek implements plan docs when the user asks (`/deepseek`), Claude vets.
* No subagents for the ADB loop.

## State at hand-off

Builds (all in `.local/`, gitignored, built from the working-copy `scripts/patch-il2cpp-endpoints.py` — the
memory note about a1e8170's script is about the *merged* HEAD version being broken; the working copy is the good one):

| APK | Built | Notes |
| --- | --- | --- |
| `KickFlight-2.11.0-current-patches.apk` (LAN) | 12:08 | production, IsCrouch nop included |
| remote (kickflightsg) | 12:08 | catalog sha `baf87d9a…`; rebuild + update `config/resources/catalog.json` sha if the production list changes |
| `KickFlight-2.11.0-DIAG.apk` | ~13:2x | installed on the emulator; `KF_DIAG=1 KF_NRE_LR=1`; 248 patches |

Server: `src/KickFlight.BootstrapApi` builds clean (`dotnet build`); restart `start-server.bat` after any config/code
change (masters are read at startup).

Emulator user: `data/users/db267e7f-…json` is the file that loads; saves land in `1000001.json` (uuid-load /
userId-save mismatch, pre-existing). Currently Hitagi (13) / costume row 110 / deck 1 = `[3010083, 3010027, 3010037,
3010042]`; the user switched to Tsubame at some point via the client, then back to Hitagi.

## What round 7 changed (details in V6 "Round 7" and AGENTS.md)

1. DIAG regions D/E relocated out of `LoadDeckSummonModel` → summons load in DIAG again (`scripts/re/relocate_diag_region.py`).
2. Costume ids: server serves KickerCostume **row ids** + `NormalizeCostume` (`DemoSessionApi.cs`); Hitagi user files → 110.
3. `Field` master row 801 (Trial arena) added to the inline string in `DemoSessionApi.InitializeMasters` — the Trial
   button loads now (it never had before).
4. Attack probes: `8790+state` (current PlayerStateType on every `IsUpdateAction` false), `8800+type` / `8810+hits`
   (every `CollisionBase.OnDestroy`). `KF_NRE_LR=1` gate for the NRE-origin hook. Reader updated (`attack_diag_read.py`).
5. **Melee combo root cause found (observed) and fix applied (NOT yet verified):** every swing connected (user confirms
   damage) but the collider expired by lifetime; `WeaponAttackActionBase.CallbackAttackCollisionDestroy(type == 2
   LifeTime)` sets `_isAttackMiss`, nulls the target, and `JapaneseSwordAttackAction.UpdateAction` (same shape in every
   weapon's UpdateAction) then hits `IsReset (target null)` → `ResetComboCount()` — KFDIAG `8210` 0.46 s after every
   swing, next swing always #1. `CollisionBase.ManagedUpdate` picks the destroy type per `HitType` (jump table at
   0x31E274C); our generated `config/masters_weapon_attack_collision.json` had `collisionHitType = 1 (All)` on all 42
   rows → switched to `0 (One)` in the JSON and in `scripts/generate_combat_masters.py` (comment explains). Expected
   after a server restart: collider destroyed with `Hit` on first contact (`collision destroyed: HIT` in the timeline),
   no `8210`, chain 1→2→3.

## Next steps, in order

1. User restarts the server, plays the Trial (or `/gym/on` + Combate) with a melee kicker, says "check logs":
   `adb logcat -d -v time > .local/run/logcat-attackN.txt && python scripts/re/attack_diag_read.py .local/run/logcat-attackN.txt`.
   Success = `ATTACK combo #1, #2, #3` in sequence with `collision destroyed: HIT`. If a swing still shows
   `LifeTime (miss)` with `hits>0`, look at the per-HitType handler behind 0x31E274C (`CollisionBase` vtable, index from
   `HitType`); if `hits=0`, the collider isn't overlapping (weapon bone / `FollowTarget` / `hitLayer 4864`).
2. Ranged kickers: the same change applies to their basic-shot colliders (bullets now stop at the first hit). Check a
   gun kicker's 1-2-3 too and that penetrating basic shots were not a feature anyone wanted.
3. If combos work, drop the now-redundant candidate patches only if the user asks (IsCrouch nop at 0x181ACEC stays —
   it was a real blocker while crouched; GetDisplayAngles null-safe cave stays).
4. Then the untouched list from V6 "Still open": kicker passives (placeholder ability rows), disc compatibilities, SS
   charge rates, KS cooldowns (WebUI), Hitagi KS warp on the phone, donor `aed` bundles' kicker-skill group ids.
5. Intermittent `UnityPreload` SIGSEGV (fault 0, 6–12 s after `GameScene`) still happens sometimes (04:54 today). Known
   loader race; not worth chasing unless it becomes frequent.

## Gotchas discovered today (short)

* `xref.py` misses virtual calls (`blr`) and delegate invocations (`set_TrialSetting`, `CallbackDestroy`): an empty xref
  list is not proof of dead code — for cave bodies use the whole-.so branch scan (numpy snippet in
  `relocate_diag_region.py`'s spirit; AGENTS.md rules).
* The 8300/8301 range probe never fires for the human (0 lines in every log): its hook/guard is wrong or the path is
  skipped for locked-on targets. Low priority; remove or fix if it confuses a reading.
* `attack_diag_read.py` collapses repeats; use raw `adb logcat -d -s KFDIAG` when timing matters.
* Emulator clock is 8 h behind the PC (log `04:46` = PC `12:46`).
* Tracked `__pycache__` folders were deleted as artifacts (they show as `D` in git status); add `__pycache__/` to
  `.gitignore` when committing.
