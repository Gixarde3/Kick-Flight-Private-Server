# Continuation — kicker weapons / skills / bot specials (2026-09-19, session 6) — READ FIRST

Supersedes `CONTINUATION_PROMPT_COMBAT_V5.md` (Rapid Ball / menus; still valid for the emulator + server
operating notes) and closes most of V4's "BREAKING ISSUES". Repo `Kick-Flight-Private-Server`, branch
`tanuki-discs`; RE material in `../Kick-Flight-Assets`.

## Rules from the user (unchanged)

* The user stages and commits — never `git add` / `git commit`. No subagents for the ADB loop.
* Plan → DeepSeek (`deepseek` skill) for large code → Claude vets and validates on the emulator / phone. Small,
  precise edits and data fixes are done by hand (everything in this session was).

## What changed this session (all uncommitted)

### Flag Flight plays (`docs/FLAG_FLIGHT_PLAN.md`)
`config/masters_battle_rule.json` row 2 `flagAmount 3 → 1` (+ inline fallback in `DemoSessionApi.cs`).
`ItemManager.ItemCountMax = flagAmount × 2`; with 6 expected and 2 flags in `ite00101_2`, `RegisteredItemAsync`
never set `IsRegistered` and `UpdateCheckOwnership` returned every frame — nobody could pick a flag, no exception.
Verified by the user on the phone.

### Weapon attachment (`DemoSessionApi.cs`, Weapon master builder)
`Weapon` rows = `kickerId, modelId, propId, boneName, rootName, attachType` — no offsets; `GetBone` is a
`Transform.FindRecursive(boneName)` on the body prefab and `Weapon.Initialize` renames the instantiated model to
`rootName`. New tools proved the right values:

* `scripts/re/bundle_tree.py <logical>` — transform hierarchy of any catalog bundle (repairs the Octo header via
  `../Kick-Flight-Assets/reconstruct_unity_bundles.py`).
* `scripts/re/anim_paths.py <kicker> --weapons 001_001,…` — the body animation clips bind transforms by CRC32
  of the full path; brute-forcing `<bone path>/<rootName>/<weapon node>` against the unexplained hashes gives the
  bone **and** rootName of animated weapons.
* `scripts/re/served_master.py <Table>` — fetch + decrypt a served master from the running server.

| kicker | prop | bone | rootName | why |
|---|---|---|---|---|
| Owlbert 5 (Drone) | 1 / 101 / 201 | `Root` | `wp_005_001_Root` / `wp_005_101_Root` / `wp_005_201_Root` | clips animate `Root/wp_005_001_Root/wp_005_001_Hip…` (hover); 201 = the four SS mini drones (48 nodes) |
| Yuyan 10 (Nunchaku) | 1 | `Prop_R` | `wp_010_001_Root` | clips animate root + both grips (swing, dangling panda head) |
| Yuyan 10 | 201 | `Root` | `wp_010_201_Root` | SS panda mount; `NunchakuPandaAction.Shot` detaches `wp_010_201_Hips` |
| Buzzy 12 (Shield), Sid 14 (Laser) | 1 / 2 | `Prop_R2` / `Prop_L2` | `wp_<k>_<p>_Root` | `ShieldPropTypeExtensions` / `LaserPropTypeTypeExtensions.AttachBoneName`; `LaserAttackAction` does `GetWeapon("Prop_R2")` |
| everyone else | 1 / 2 | `Prop_R` / `Prop_L` | `wp_<k>_<p>_Root` | rigid, no animated nodes |

Props ≥ 100 are hidden by `Weapon.Initialize` (`IsDefaultWeapon = propId < 100`) and shown by the skill code, so
serving them as Child rows is right. The old nunchaku 201 row on `wp_010_001_Grip_L` glued the SS mount to the
nunchaku; `Prop_L` for the shield put it on the wrong side of the arm (the `*2` bones sit on the forearm with the
opposite orientation); `Prop_Common` for the drone stood it on its nose at the chest. Verified in the kicker
viewer on the emulator: drone hovers above Owlbert's head, Yuyan holds the stick by its end with the panda head
hanging, Sid's lasers are wrist-mounted forward, Buzzy's shields on both forearms (left one to be eyeballed in the
phone's full-screen viewer). `pc_ma_*` clips are facial (Jaw), not weapon clips — V3's note was wrong.

### Buzzy Big kicker skill
`ShieldSkillAction.UpdateExecute` = `player.AcceptCondition(GetKickerSkillConditionInitInfo(Execute))` and skill
20012 had no condition rows. Added `SkillCondition` id 139: `conditionType 26 ShieldForward, duration 6,
effectValue 4000 (barrier HP pool), triggerType 3` (`config/masters_skill_condition.json` +
`KICKER_SKILL_EXTRAS[20012]` in `scripts/generate_combat_masters.py`). Tune `duration`/`effectValue` by feel.
The skill's name "Megamartillo" in `masters_skill.json` is a leftover (cosmetic).

### Bot roster (`BattleMatchmakingService.BotProfiles`)
Real names from `masters_kicker.json`; order Owlbert, Buzzy Big, Yuyan, Sid first so every solo match exercises
them (reorder freely).

### Bots cast their special skill (client patch, `scripts/patch-il2cpp-endpoints.py`)
Retail AI never uses the special: `PlayerCharacter.CollectSkillsForAI` only registers the kicker skill + deck
discs and the sole SS trigger is the button (`SpecialSkillPresenter.OnClick` → `SetState(13)` +
`ApplyForcedAction`). New keystone cave (`scripts/re/bot_special_skill_cave.py`, 376 bytes at `0x159D200` in the
dead body of entry-stubbed `HomeSummonModelController.SetModel`, hook `b` at `PlayerCharacter.UpdateAi`
`0x13BEAEC`, `_enableAi` only):
1. state Normal + `Param.SP >= GetMaxSP()` + `ConditionActionCtr.EnableSpecialSkill` → `SetState(13, null)` +
   `ApplyForcedAction`.
2. state SpecialSkill: every `XxxSpecialSkillAction` starts in `CutStaging` and only continues from
   `OnEndCutScene`, which only the main player's cut-in UI raises (other clients are network-synced in retail) —
   the first attempt froze every bot in its first special (0 kills). The cave calls
   `_skillAction.OnEndCutScene(false)` (vtable slot 11) itself, then `OnPressExecuteButton`/`OnReleaseExecuteButton`
   when the action reaches `AttackStaging`; a progress byte in the routine's padding (`+0x3C`) fires each step once
   per cast and is reset outside state 13.
Verified: full 3-minute match, all bots cast repeatedly (Panda Rush, Crew Protection, Cure Light, Formation Cloud…),
kills/deposits normal, no exceptions.

### ⚠ `scripts/patch-il2cpp-endpoints.py` — the 09-14 merge broke it
HEAD's version (merged from the collaborator) lost the `*([{` opener of the `KF_UNLOAD_BYPASS` block (did not
parse) and replaced the offline matchmaking patches (removed "bridge matchmaking completion to offline battle
room", "force IsRoomLocalPlayerMaster", "store battleRuleInfo … ChangeGameSceneSync"; added a
`ns.exitgames.com` Photon host mapping). Once parseable, that script builds an APK that never leaves the matching
lobby against this server. **The working tree now holds the pre-merge `a1e8170` script + the two bot-SS entries**
(139 patches verified against the pristine lib); the merged HEAD version is saved at
`.local/patch-il2cpp-endpoints.merged-HEAD.py` for the user to reconcile with the collaborator.
APKs rebuilt from it: `.local/KickFlight-2.11.0-current-patches.apk` (LAN, emulator) and
`.local/KickFlight-2.11.0-remote-kickflightsg.apk` (phone) — 12:29, needs installing on the phone.

### Round 2 (same day, after the user validated the weapons on the phone)

* **Owlbert SS smog** (`config/masters_special_skill_condition.json` id 5, `masters_special_skill_trap.json` id 5,
  generator `WT_DRONE`): `DroneSpecialSkillAction.ExecuteSkillEffect` applies the trigger-3 condition to every ally.
  The condition that spawns the escort drone and lays the clouds is **Smog (18)** (`SmogConditionAction`: cloud
  radius = the special's `TrapInfo.Radius`, a new cloud every radius+1 units of ally movement, `SendAddTrap` type 6,
  escort drone = local `NonPhotonViewNPCInitializeInfo` type 3); SmogProtection (20) / SmogDisturb (19) are what
  players *inside* a cloud get (triggers 6 / 5) and were wrongly served on trigger 3 since 09-14. Trap radius
  100 → 5. Verified on the emulator playing Owlbert: burst, escort drone, translucent spheres along the path.
* **Bot specials had no effect / boost pose in the banner / no pause**: `UpdateAi` kept running
  `AIPlayerEngine.ManagedUpdate` during state 13, so the engine flew the bot through its special and the
  animation-event effects never fired (Coco's code-spawned pull worked, her slam did not). The cave now returns from
  `UpdateAi` without the engine while in the SpecialSkill state (`scripts/re/bot_special_skill_cave.py`). Verified:
  banners show the real SS poses, specials hit (damage numbers), no exceptions.
  `SpecialSkillActionBase.AcceptCondition`'s `IsSynchronized` gate (the collaborator's "apply locally" patch) already
  passes offline (`IsMine` patched, `ReplayMode` 0) — not needed.
* **Kite SS shuriken** (`masters_special_skill_bullet.json` id 4, generator `WT_THROWING_STAR`): `distance 60 → 300`
  and `endType 1 FadeOut` so the star leaves the arena instead of stopping mid-air at 60 u with a lingering effect
  (bullets only stop on geometry when the Field layer is in `hitLayer`, already removed). Generator now honours a
  per-weapon `endType`.
* **Bot specials had no effect at all (rounds 3-4)** — what the DIAG probes actually showed (`KFDIAG` 7xxx values
  logged from the cave + entry hooks on `SendCondition`/`ReceiveCondition`/`GetSpecialSkillConditionInitInfo`):
  the special's effect is not an animation event. `SpecialSkillActionBase.SetEvents` registers `ExecuteSkillEffect`
  (vtable slot 18 = `+0x248`; `SetEvents` reads `+0x250` because it wants the slot's *MethodInfo* for its delegate)
  as an event on the **cut-in scene's timeline** (`SpecialSkillCutActionBase.AddSpecialSkillEvent`), which only the
  main player plays, and retail fires it right *before* `OnEndCutScene`. Classes overriding it: Bat, Bowgun, Drone,
  Gun, JapaneseSword, Nunchaku, PunchGlove, Shield, Sword, TwoGuns; Hammer/Laser/RocketLauncher/ThrowingStar keep the
  empty base and act from press/release + the in-world animation instead. Two wrong attempts before the fix: calling
  `+0x250` jumped into a MethodInfo (silent whole-game hang), and calling the effect "one frame after" the cut end
  never ran for the overriding classes because their `OnEndCutScene` leaves state 13 in the same frame.
  Final cave (`scripts/re/bot_special_skill_cave.py`): in `CutStaging` count frames in the routine's padding byte
  `+0x3D`, after 120 frames call `ExecuteSkillEffect()` then `OnEndCutScene(false)` in the same frame, then press/
  release execute in `AttackStaging`; no AI engine while in state 13. Evidence: DIAG trace
  `Nunchaku: 7200 7406 7401 7402 7410 7411 7201 7100` (effect -> condition sent and received) and, in the production
  build, Buzzy Bot's Crew Protection sphere on the human, 1034 damage from Yuyan Bot's Panda Rush, Coco Bot's slam
  VFX and Owlbert Bot's escort drone on the human. Bots hold the pose ~2 s (120 frames) before the effect - tune
  `CUT_FRAMES` in the cave source if the retail cut length feels different.
* DIAG builds (`KF_DIAG=1`) currently hang on the loading screen about 2 of 3 times at `RouteJunctionTable.InitTable`
  (probe 952, before any player exists) - the known loader race, unrelated to the cave; retry the launch.
* APKs rebuilt 16:27 from the a1e8170 script + the updated cave (139 patches): `.local/KickFlight-2.11.0-current-patches.apk`
  (emulator) and `.local/KickFlight-2.11.0-remote-kickflightsg.apk` (phone — install it).

### Round 5 (evening)

* **Kicker model height** (`config/masters_kicker_parameter.json`, generator `BODY_HEIGHTS`): `footHeight` was 0.0 for
  every kicker. `PlayerModelControllerBase.SetHeight` puts the model at `localPosition.y = -footHeight`, so the
  character root (colliders, condition effects like Crew Protection, lock-on) sat at the feet and every kicker stood
  on top of its own effects. Now `footHeight` = hips height and `height` = head top, measured per body prefab with
  `scripts/re/bundle_tree.py` (Pitophy 0.52/1.30 … Diatrius 1.16/2.23). Server data only. Not yet eyeballed in play.
* **Pitophy SS (Missile Party)**: `RocketLauncherSpecialSkillAction.PlayMuzzleEffect` instantiates
  `BulletInfo.Path` (= `SpecialSkillBullet.resourcePath`) for the muzzle flash and `BulletActionBase.CreateEffect` uses
  the same path for the missile in flight; with `""` every shot NRE'd in `EffectManager.InstantiateEffect` (40 per
  cast) before `CreateBullet`, so nothing was ever fired. Row 6 now has `effect/ss/ef_ss_006_001/ef_ss_006_001`
  (generator `WT_ROCKET.bullet.resourcePath`). Proof from DIAG entry probes, human cast: 12× `SendAddBullet` →
  12× `CreateEffect` → 12× `HitCallback` → 12× `OnEndBullet` (TARGET_COUNT = 12), zero exceptions; muzzle bursts
  visible. Whether the in-flight missile VFX looks right is for the phone (the SS bundle holds one prefab that
  serves as both flash and projectile; if the projectile is invisible, the alternative is `effect/wp/ef_wp_006_001`).
* **APK download on the LAN**: `http://192.168.68.55:18080/apk/KickFlight-2.11.0-remote-kickflightsg.apk` (catalog
  entry `apk-remote-kickflightsg`, single entry — `MatchDirect` needs exactly one resource per path, so no per-host
  duplicates). Serves at 80 MB/s locally; the ddns route goes through the 250 KB/s uplink. Rebuilt 17:5x from the
  clean production script (139 patches). DIAG probes (7xxx) were removed from the script after use.
* **Match-end hang seen once on the DIAG build** (timer 0:00, no `/battle/end`): 9 042 NREs/frame in
  `PlayerStateSkill.End → ForceFinishSummon → SummonCharacter.UpdateState` (`_state` routine null at `+0x118`) — a
  player still in a summon-disc skill when the match ended. Pre-existing, unrelated to the caves; needs a null guard
  patch at `SummonCharacter.UpdateState` (`0x16510D0`) or in `ForceFinishSummon` (`0x17F8758`) if it recurs.

* **`targetSdkVersion` 29 → 30** (`.local/build.sh` manifest step, also `requestLegacyExternalStorage`): Android 14+
  refuses to install (not just run) APKs targeting an SDK below its floor; the Honor phone on Android 16 showed a bare
  "package invalid" for the retail target 29, while `adb install` had always been exempt. 30 is the lowest accepted
  value. Verified on the emulator with a clean install: full 954 MB cache download, Home, a complete match with
  `/battle/end` + `/battle/result`, no new exceptions. Both APKs rebuilt (remote 21:0x, sha in the catalog entry).

### Round 6 (2026-09-20, night) — Jay KS, TRAP and MOVE discs, balance WebUI

Server-data only (no APK change). Server restarted 00:29 on the new tables; the served rows were checked with
`scripts/re/served_master.py SkillCondition|Summon|SkillTrap`.

* **Jay kicker skill** (`Bat`, skill 20009): `BatSkillAction.OnBeginAction` is only `player.AcceptCondition(trigger 3
  rows)` and there was no row. `KICKER_SKILL_EXTRAS[20009]` = Stealth (24) 8 s → model fade, condition VFX and
  `EnableLockedOn=false` (untargetable) until the duration ends or he attacks / is hit.
* **TRAP discs.** Every disc trap was `trapType 1` (Slow). `Trap.Initialize` picks the action from `trapType` (1 Slow,
  3 Turret, 5 Inhale, 6 Smog, 7 Bomb, 8 Condition, 9 Empty, 10 BatBomb); `DISC_TRAPS` in the generator now types the
  20 trap discs from their card text (bombs 7, turrets 3 with `interval`, damage/regen areas 8 with `SkillCondition`
  rows trigger 5 EnterEnemyTrap / 6 EnterMyTeamTrap, Snazzy Snail slow). Radius/colliders/explosion still come from the
  APK ActionMaster; the served `radius` is ignored.
  ⚠ A wrong "fix" made in the same round (`Summon.modelId` → 0 for all rows) **froze the phone on every MOVE/TRAP disc**
  and was reverted after an emulator run with logcat: `LoadManager.LoadDeckSummonModel` preloads
  `summon/sm_{Skill.summonId:D4}_{LowModelId}` while `PlayerStateSkill.CreateSummon` instantiates
  `summon/sm_{Summon.modelId:D4}_{LowModelId}` — `Summon.modelId` is the id of the summon whose model to use (= its own
  id), and `LowModelId` = 2 if `middleModelFlag` else 0. With modelId 0 the instantiate path was `sm_0000_0`, the cache
  missed, `SummonCharacter.InitializeAsync` NRE'd (logcat: `SummonCharacter+<InitializeAsync>d__69.MoveNext` under
  `PhotonNetwork.Instantiate`, then `SummonCharacter.Action < PlayerStateSkill.BeginActionExecute` and a
  `ForceFinishSummon` storm) and the skill state never finished. `summon_table` now emits `modelId = id` and derives
  `middleModelFlag` from which `sm_XXXX_{0,2}` bundles exist in `config/resources/catalog.json` (27 ids only ship the
  middle model: 82-86, 94, 96, 114-138). Verified on the emulator (production LAN APK): Booby Bomb, Killer Billet,
  Stray Phantom and Pyronkey all cast and release, summon bodies spawn, a full match with bots using pets/traps ended
  with zero summon exceptions.
* **MOVE discs** (skillActionType 22 `AutoMoveSkillAction`; 21 `VerticalLoopSkillAction` for Cycrane):
  `OnBeginForceMove` only does `player.AcceptCondition(GetSkillConditionInitInfo(deckIndex, trigger 3))` and
  `OnUpdateAction` leaves the skill as soon as `ConditionActionController.HasConditionActionSkill` is false — with no
  row the kicker posed and stopped. The mover is `AutoMoveConditionAction` (ConditionType **30**):
  `OverrideSpeed = Param.GetSpeed(1) × effectValue`, acceleration 7.5, runs for `duration`, ends early on a wall hit
  (`IsFinishedByInterrupt`). `DISC_MOVES` in the generator: Pyronkey/Spunkle/Tigre 4 s ×2.0 (their four rear shots are
  bullets in the APK timeline, fired while the dash runs), Leeta 5 s ×2.0, Stray Phantom 5 s ×3.0, Great/Gusty Glidears
  4 s ×2.0. Cycrane's loop is hard-coded (420°/s, radius 2.5, bullet 127 from the timeline) and needs no move row.
* **Round 6b (01:30, after the phone reported "MOVE discs don't shoot backwards, traps vanish after placement")**:
  * Pyronkey / Spunkle / Tigre are **not AutoMove**. Their timeline (`aed_*` group 10027/10079/10112) is four Collider
    bullet clips with `_intParameters[8]` (`EventItem.MissTargetDirection`) == 2 plus a 0.47 s ForcedMovement.
    `AutoMoveSkillAction` has no `OnCreateCollider`, so nothing ever fired; `ShotAttackSkillAction` creates timeline
    bullets *and* honours the forced move, and its ctor sets `IsBackShot` from that MissTargetDirection == 2. Served
    `skillActionType` 1 for the three (`DISC_ACTION_TYPE_OVERRIDES` in the generator; their AutoMove rows dropped,
    Tigre keeps Paralysis on hit). Dash length/speed = `masters_skill` `range`/`speed` (16 / 28 for Pyronkey).
  * Bomb / turret trap bodies despawned because `Summon.summonCharacterType` was 0 (Normal): `SummonCharacter.Finish`
    sends an **AttackTrap (3)** body to `SummonStateType.NativeAction` (it *is* the trap — `BombTrapAction` /
    `TurretTrapAction` are `SummonTrapActionBase`), anything else to Finish → despawn when the placement ends.
    `summon_table` now emits type 3 for the summons of `DISC_TRAPS` entries with trapType 3/7 (12 rows).
  * Verified on the emulator: Pyronkey dash scores hits (0 → 10 → 40 pt with no other action), Booby Bomb mine and
    Killer Billet turret bodies stay put (11 s+), full match, no exceptions besides the known TitleView one.
  * `SummonCharacterType` 1/2 (Bullet/OneBullet, `SummonBulletAction`) only drive muzzle effects on the pet — the
    bullets themselves always come from the skill action's timeline colliders.
* **Knock-up (01:45)**: bomb traps and Princess Izana had no `masters_skill_blow_off` row (the table was empty for
  discs). `SkillBlowOffMaster.GetDataFromSkillId` is read in `DiscSkillParameter..ctor` and rides on the skill's
  damage; `DISC_TRAPS` entries now carry `blow_off` (`_KNOCK_UP`: distance 6, speed 20, rigor 0.5, directionType 1 Up;
  2 Down / 3 Press / 4 AttackDirection) → 11 rows served. Not tested (user asked for a quick fix).
* **On-hit status effects are a served table* **Balance WebUI** — `tools/balance/` (DeepSeek round 1, vetted): `python tools/balance/server.py` →
  http://127.0.0.1:8765 (`--port`). Stdlib only, binds loopback, edits `config/masters_*.json` in place with a backup
  in `tools/balance/backups/` per save, type-checked (ints stay ints, keys fixed, 400 on anything else). Kicker panel:
  Stats / Passive / Kicker Skill (+extras) / Special Skill (+extras) / Basic Attack by `attackCount`; disc panel: disc
  row, skill row, extras, card text from `docs/disc_cards.json`, icons from `tools/balance/icons/`
  (`scripts/re/extract_thumbnails.py`). Save = POST per dirty table; the game server must be restarted after saving.
  Adding/removing rows is out of scope (edit the generator tables instead). `tools/balance/backups/` holds the
  round-1 test backups — deletable.
* `scripts/patch-il2cpp-endpoints.py`: the four rocket DIAG probes (caves 0x159D420/0x159D4A0) were removed; dry-run
  139 production / 205 with `KF_DIAG=1`.

### Round 7 (2026-09-20, afternoon) — DIAG summon regression, kicker-select blank screen

* **DIAG build: Leorex / any summon disc froze the kicker and it never respawned.** Cause: the DIAG build stubbed
  `LoadManager.LoadDeckSummonModel` because DIAG regions D/E (incl. the safe LOG helper) lived in its body, so no
  summon model was preloaded → `SummonCharacter.InitializeAsync → ModelManager.InstantiateSummonModel` NRE, then
  every forced state change (`ApplyForcedAction → PlayerStateSkill.End → ForceFinishSummon → SummonCharacter.UpdateState`)
  NRE'd — the kicker stayed in the skill pose (logcat-attack3: 116 × that stack). Fix: `scripts/re/relocate_diag_region.py`
  moved the whole block to the dead `PlayerCharacter.UpdateLookTarget` body (0x13CD990) and re-linked the 16 hooks
  + region A trampoline; the stub is gone (DIAG dry-run 245 patches; production unchanged, 141).
* **Kicker selection screen blank after setting the emulator user to Hitagi.** `kickerCostumeId` is the KickerCostume
  master *row id* (the client saves 110 for Hitagi standard, 64 for Owlbert), but the server served the per-kicker
  `costumeId` column (1..7) in `userKickerCostumeList` and I had written `KickerCostumeId 1` (= Tsubame's row) into the
  Hitagi user files. `DemoSessionApi` now maps kickers to costume row ids, `NormalizeCostume` swaps in the kicker's
  first row whenever the stored costume belongs to another kicker (startup, home, /kicker/change, battle entry), and
  the three Hitagi user files say 110. Not verified on the emulator (no logcat of the blank screen exists) — if it is
  still blank, pull `adb logcat -d | grep -A12 Exception` right after opening the screen.

* **Trial (Discs-page test button) never loaded** — every attempt (03:44, 04:58, 05:06 logcats) NRE'd in
  `PlayerCharacter.Initialize` and hung on "Cargando". The NRE-origin hook (cave H, now opt-in with `KF_NRE_LR=1`;
  convert the logged low-32-bit LR with the libil2cpp base from `/proc/<pid>/maps` via `run-as`) pointed at RVA
  0x13C74CC = the `FieldManager.FieldInfo == null` check. Cause: the served `Field` master is a hard-coded two-row
  string in `DemoSessionApi.cs` (99999, 101) and `FieldManager.InitializeAsync` bails out without setting FieldInfo
  when `FieldMaster[801]` (the Trial arena `CreateTrialBattleInfo` hard-codes) is missing. Row 801 added. The 04:54
  attempt died differently (UnityPreload SIGSEGV, fault 0 — the known intermittent loader race).

## Still open

* Kicker height / Crew Protection sphere placement: verify by feel on the phone (V6 round 5).
* Pitophy missile visuals / homing on the phone (V6 round 5).
* Round 6 on the phone: Jay KS (fade + no lock-on for 8 s), traps behave per type (bomb / turret / area), MOVE discs
  dash for their duration (verified on the emulator 01:00 after the modelId revert; the phone freeze was that revert).
* User's outstanding list still untouched: basic-attack combos broken for some kickers (`masters_weapon_attack.json`
  rows per `attackCount`, `scripts/generate_combat_masters.py weapon_tables`), kicker passives (`masters_kicker_ability` +
  `masters_kicker_ability_condition`: all 14 rows are the same placeholder — trigger 1, 5 s, ×1.2 — so no kicker has
  its real passive; `PlayerParameter.GetAbilityConditionInitInfo` reads the condition rows by trigger), disc
  compatibilities (`DiscSkillParameter` `_compatibilityTime` in the APK timeline is per kicker; the served side is
  `masters_disc` `discType`), SS charge (`addMoveSpecialSkillPoint` / `addWeaponAttackSpecialSkillPoint` in
  `masters_kicker_parameter`), KS cooldowns (`masters_skill.coolTime` for 2000N) — all editable in the WebUI.

* Owlbert KS drone trap (silence on approach) — rows fixed, not verified by eye. If dead: `NPCDrone` states /
  `NPCDroneStateAttack` with a logcat.
* Buzzy KS barrier: condition row served, not yet seen in play — check the "Barrera Frontal" spawns.
* Smog cloud VFX: the trap row's `effectPath` is empty — if the clouds look like plain spheres, find the smog
  effect path (`effect/…`) in the catalog and serve it.
* Kite's shuriken passing through guardians/gimmicks: only Player/NPC hit layers are set; if it still stops on an
  objective, log which collider ends it (`BulletActionBase.HitCallback`, `IsFieldHit` needs the Field layer).
* Bot SS timing is "as soon as the gauge is full"; no delay/targeting smarts. Human SS unaffected.
* Result screen `ResultUIManager.PlayRandomStamp` ArgumentOutOfRange (pre-existing, cosmetic).
* Everything from V5's open items (Rapid Ball tuning, ranked, rules-window pages) and V4's lower-priority list.

## Phone logcat
HONOR `persist.log.tag=S` hides all app logs; `adb shell setprop log.tag.Unity V` (+ `persist.log.tag.Unity`,
`KFDIAG`, …) was set on 2026-09-19 — verify it sticks; the pairing port may refuse while the mDNS serial
`adb-AUYF6R5A24002889-…_adb-tls-connect._tcp` still works.
