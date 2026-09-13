# Continuation — combat / discs (2026-09-12)

Working tree only; nothing staged (the user stages). Emulator `KickFlight_A15`, server on the LAN host
`192.168.68.55:18080`. Everyday loop: `start-server.bat` (kills old, incremental build, runs),
`start-client.bat` / `start-client-remoteplay.bat` (software renderer for Steam Remote Play),
`start-client-diag.bat` (KF_DIAG trace APK, no disc pets), `capture-logcat.bat` (writes
`.local\logcat-<date>.txt` + `-kfdiag.txt`), `screenshot.bat`. Config edits need a server restart; the
client re-downloads changed tables on the next launch (`x-app-master-hash` is now a content hash).
**The user often runs `start-server.bat` themselves** — after editing C# ask them to re-run it.

## State of play

Works: matchmaking → 4v4 battle → results → home; bots fly, fight, deposit; basic attacks and dash
attacks deal damage; kicker skills cast, resolve and cool down; most discs cast; pets spawn; all 14
kicker models load in Home; Remote Play via swiftshader.

Open:
* **Discs** — root cause of "disc X works on Tsubame but freezes Ruriha/Hitagi" found and fixed (server side
  verified with curl; the user tests in the emulator): disc timelines are per-kicker bundles `actioneditor/aed_NNN`
  and only 001/004/005/008/011 were captured; the other nine kickers had no timeline, so
  `MoveAttackSkillAction..ctor` NRE'd on its forced-move event and every other disc fired nothing. Fix =
  `scripts/build-action-asset-bundles.py` (nine donor copies with unique CAB names → `content/resources/actioneditor/`,
  git-ignored, + `title-minimum.json` entries), Octo revision 16→17, `build-title-resource-catalog.py` rerun
  (fixtures + catalog now use the direct host 192.168.68.55 instead of 10.0.2.2 — that is the big catalog.json
  diff), `seed-device-cache.py` also packs `content/resources`. Also retyped 11 discs that were `MoveAttack`
  without a forced-move clip (froze every kicker) and taught `generate_combat_masters.py` the rule. Write-up +
  per-disc timeline table: `docs/DISC_ACTION_TIMELINES.md`.
  **To test**: restart the server (`masters_skill.json` is read at startup; fixtures/catalog hot-reload), launch
  the client — it must fetch `/v1/list/12345/16` (server log: `... -> accepted-octo-title-minimum-12345-from-16`)
  and then `GET /cdn/aed0NN` for the kickers in the match (or run `seed-device-cache.py` first); then cast Leorex
  (3010027) with Ruriha/Hitagi. If it still freezes: logcat for `MoveAttackSkillAction..ctor`; if nothing fires:
  no `/cdn/aed0NN` request reached the server → the client did not merge revision 17.
  Disc identities: DONE - `docs/disc_cards.json` (131 discs: 104 cards matched to ids by art incl. 27 pulled from the
  Discord #resources image cache, 5 placed by deduction, 22 N discs from the user's descriptions with extrapolated
  stats; attribute from card frame colour), cross-checked against the Appliv disc table (icons matched by art, stats + JP effects agree on all 131, N discs now have real names/stats) and applied to the masters with `scripts/apply_disc_cards.py`
  (masters_disc/skill/summon + skill sub-table templates; rerun after editing the JSON). `masters_summon.middleModelFlag`
  now selects the `_2` bundle for the 26 pets that only ship it (`SummonMasterData.LowModelId`). Trap sub-rows are still
  the Slow template (trapType 1) for every trap disc - turret/bomb/area types are the next data task (BombTrapAction
  needs bullet rows, so check `DISC_ACTION_TIMELINES.md` before switching a disc to trapType 7).
  Five discs (3010045/096/133/136/138) have no thumbnail in the capture (3010054/3010121 are not real discs - pets exist, no card); `scripts/build-disc-thumbnail-bundles.py`
  builds placeholder `ui/disc/thumbnail_*` bundles from the card screenshots in `../Disc_data/thumbnail_source/`
  (Octo revision 19). Real art would need the original bundles.
  Visual index: `docs/img/disc-index.png` (disc 3010NNN → skill 10NNN → pet sm_0NNN).
  Everything about the tables: `docs/COMBAT_MASTERS_FILL_IN.md`.
* **Battle-load freezes (intermittent)**: logcat 13Sun 1340/1341 show `GameScene` and then nothing (no
  `lightmaps mode` line = the field never finished loading, no exception) until the app was killed; a good run
  reaches the lightmaps line ~5 s after `GameScene`. Something in GameScene.PreBeginAsync's load queue never
  completes. Not diagnosable from the production APK: reproduce with `start-client-diag.bat` + `capture-logcat.bat`
  (KFDIAG 3xx = BeginAsync coroutine step) and compare with the server console, which `start-server.bat` now tees
  into `.local/session-logs/server-<timestamp>.log` (look for `/cdn/` downloads and deck warnings).
* **Special skills**: they are data-driven per weapon (`docs/COMBAT_MASTERS_FILL_IN.md` §4): Sword/Nunchaku/
  JapaneseSword apply `SpecialSkillCondition` rows to self, TwoGuns/Drone/Bowgun/Shield to allies, Gun/Bat to
  enemies, PunchGlove sets a `SpecialSkillTrap`, ThrowingStar/RocketLauncher fire a `SpecialSkillBullet`,
  Hammer/Laser hit through Collision+Hit. Those sub-tables were empty (only the templates for Collision/Hit
  existed) so nothing happened after the cutscene. `SPECIAL_SKILL_DATA` in `generate_combat_masters.py` now fills
  them per the user's descriptions (Owlbert = smog: allies hidden/untargetable; Buzzy = unbreakable shield for allies 5 s; Coco = inhale tornado then slam down = blow-off Down; Sid = beam with tick damage + paralysis on hit; Grenhawk = allies move speed + attack speed 12 s). `--only special_skill` rewrites just these tables; numbers are first guesses.
* **Guardians (crystal-mode turrets)**: `GameManager.CreateGuardian` spawns `BattleRule.guardianAmount` NPCs
  **per team** at the field's guardian points (`FieldManager.GetGuardianInitialPosition`; FLD00101_1/_3 have two
  points, the flag variant _2 none - amount 2 threw ArgumentOutOfRange), hp/attack from `GuardianParameter` (id
  from `/battle/start`), laser from `Guardian.skillId` -> `Skill` row 1 (skillType 3, kept out of the kicker
  remap; range = `Guardian.laserLength`). `NPCSkillParameter` takes the beam's collider/hit from the served
  `SkillCollision` / `SkillHit` masters (not from aed_master), so `generate_combat_masters.py` now emits
  `masters_skill_collision.json` / `masters_skill_hit.json` for skillType-3 rows and the server serves them;
  without the collision row `NPCGuardianParameter.InitializeBulletInfo` NREs and the battle sticks on Cargando.
  Crystal rules 1/5/6 have `guardianAmount 1`; model `npc/np_001` (+ animator) is captured. Tested 2026-09-13:
  turrets spawn and crystal deposit works. Turret HP = deposited crystals x `GuardianParameter.hp` (StepHpValue;
  now 8000 - kickers with four lv10 discs hit for ~2500, so ~3 hits per crystal; beam attack 6000 ~= 2000 per shot after scaling); hits deal their normal attack x coefficient to it. `fixedDamage`
  is NOT guardian damage: when >= 1 it replaces the player damage (`PlayerCharacter.AcceptDamageInfo`) - a 3 there
  made every special deal 3 - so it is 0 everywhere except Kite's one-shot shuriken (99999), whose guardian effect
  is the APK `_guardianDropCrystalCount`. No HP bar: `GuardianHpGaugePresenter.Initialize`
  only builds gauges for NPCs already in `ObjectManager.GetNpcs()` when `GameManager.InitializeUI` runs, and the
  `<BeginAsync>b__6` wait before it was stubbed to false; the patch now waits on `IsCreatedGuardian` (NPC count >=
  field guardian points). Turret beam damage (GuardianParameter.attack 1000, SkillCollision sphere r1.5) is
  unverified - the user reports little or no damage.
* **Intermittent SIGSEGV on the UnityPreload thread ~12 s into GameScene** (logcats 13Sun 15:18-15:29: Coco 2 of 3,
  Yuyan 2/2, Hitagi 1/1, Tsubame 0/4; also seen 09-12). Not caused by the disc/guardian data: the server answered
  `/battle/start` normally and no CDN download was requested. Unity's Android crash reporter is useless under
  ndk_translation: every report shows `pc libunity+0x34426c` (the reporter's own register capture; `x30`/frames are
  its own) so the real fault site is unknown; only `fault addr` (0 here, 0x7b0 in the 09-11 missing-asset crash) is
  real. Leading suspect: the `LoadManager.Enqueue` `_isUnloading` bypass (patch 0x16E2AD8) lets loads run during
  `UnloadAsync` state 1 (`ResourceManager.UnloadAssetBundleAllAsync`), i.e. async loads racing bundle unloads. Test
  build without the bypass: `start-client-unloadgate.bat` (built with `KF_KEEP_UNLOAD_GATE=1`). If it stops the crash
  but drops loads (missing models / hang), the proper fix is to defer Enqueue'd actions until state 2 instead of
  dropping or racing them.
* Nunchaku (Yuyan) does not dangle: both parts attach and `NunchakuAction` ticks; the swing is
  animation data (`pc_ma_010_01_*` clips bind 7 weapon transforms by CRC32 path hash) that resolves
  through `Weapon` master `rootName` (model root is renamed to it in `Weapon.Initialize`); ours is `""`.
  Parked. Likely affects other weapon animations (drone hatches...).
* Kite (ThrowingStar) and Diatrius (PunchGlove) have no weapon bundles — by design.
* Speed calibration: `KickerParameter.speed` ×4 of wiki ratings (3.4–5.2 u/s); melee
  `attackTargetSearchDistance 1.0`, `dashAttackRange 8`, `dashAttackTime 1.0`.

## Client patches added this session (`scripts/patch-il2cpp-endpoints.py`, all arm64, keystone caves)

* AI: `CanTakeOff` true for EnableAI; `Acceleration()` skips dash branch for EnableAI (fixes bots stuck
  at spawn). Caves in dead body of `HomeChatNotificationView.OnCompleteChatSetup`.
* `CharacterRPCControllerBase.SendRPC`: null ReplayManager → `photonView.RPC` directly (damage RPCs).
* Animator guards replacing old `return false/true` stubs: `IsCurrentState`, `IsInTransition`
  (`TitleView`/chat bodies), `PlayerAnimator.IsBindMotionCondition` (`TitleView.SetAllButtonActive` body)
  — the last one was why no kicker ever returned to idle after a skill.
* `PlayerStateSkill.UpdateSubStateTime` watchdog: Execute/Finish advance after 4 s when time < 0.
* `PlayerStateSkill.End` tail → `PlayerAnimator.PlayIdle(false, 0.1)` (cave in `UnloadModel` body).
* `LoadDeckSummonModel` un-stubbed in production (DIAG keeps the stub; region D/E caves live there).
* DIAG: safe LOG helper (preserves x8-x18; old caves clobbered the metadata-init flag → random
  SIGSEGV 0x127), regions E/F/G probes (PerformMove, skill sub-states, PlayIdle, weapon attach).
  Generators: `scripts/re/mkcave.py`, `scripts/re/gen_diag_regionE.py`. Free dead bodies listed by the
  snippet in the session (stubbed functions: `HomeSummonModelController.SetModel` 0x8f0 bytes, etc.).

## Server changes (`src/KickFlight.BootstrapApi`)

* `DemoSessionApi`: 19 combat masters served from `config/masters_*.json`; `MasterVersion` = SHA-256
  of all tables; `ApplyObscuredOffsets` (Skill.coolTime +230, Disc hp/attack, KickerAbility.overlapCount,
  SpecialSkillHit.fixedDamage); Weapon master from `config/resources/catalog.json` (path fixed — it had
  silently fallen back to a hard-coded table): only props 1 (`Prop_R`, Drone → `Prop_Common`) and 2
  (`Prop_L`), TwoGuns get a `Prop_L` copy, Nunchaku prop 201 on `wp_010_001_Grip_L`.
* `scripts/generate_combat_masters.py --force`: remaps ids (disc skill 10000+n, kicker skill 20000+k,
  Jay's bat bomb 40001 wired via `KickerAbility.value`), sets kicker skill action type from
  `weaponType`, clamps disc types, regenerates the template tables. `masters_kicker_parameter.json`:
  weapon types/roles per the user, `skillId` 20000+k.
* `/battle/result` handler; bot rank 13; tests pass (22).

## Diagnosis recipes

* Exceptions: run the stack-aggregation snippet over `.local/logcat-*.txt` (E Unity + "  at " frames).
* KFDIAG values: 6200 skill End, 6210 Normal.BeginAction, 6220 SetStateNormal, 6250/6251 PlayIdle,
  6300/6301 CrossFade, 6410/6411 Nunchaku init/update, 6420/6421 weapon attach, 940+state SetState,
  1001/1132/13xx/2xxx/3xxx PerformMove trace, 38xx SubState, 39xx auto-move flags, 7xxx speeds.
