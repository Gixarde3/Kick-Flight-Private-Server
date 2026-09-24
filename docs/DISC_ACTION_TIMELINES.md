# Disc action timelines (`actioneditor/aed_*.unity3d`) and why discs froze some kickers

Investigated 2026-09-12 from the pristine `libil2cpp.so` (arm64) and the captured Octo bundles.

## What the client needs to cast a disc

`SkillActionBase..ctor` (0x141EFEC) builds two `SkillActionClipController`s from
`DiscSkillParameter.GetSkillActionDatas(0|1)` and stores
`_forcedMovementEventItem = SkillActionUtil.GetEventItemByClipType(actionItems, ClipType.ForcedMovement)`.
Those event lists come from `SkillActionDataManager.GetEventItemGroup(characterId, skillId)`, which is filled by
`SkillActionDataManager.LoadAssetData(characterId, deck)` from the asset
`ResourceUtil.GetActionAssetPath(kickerId)` = **`actioneditor/aed_{kickerId:D3}`** (`LoadManager.LoadActionAsset`,
requested for every row of `KickerMaster` in `MatchingScene.PreBeginAsync` and in `HomeScene`).

Each `aed_NNN` bundle is one `ActionEvent` MonoBehaviour: `_events[]` = `EventItemGroup { _id = skillId, _list[7] }`
indexed by `ClipType` (0 Animation, 1 Effect, 2 Sound, 3 Collider, 4 ForcedMovement, 5 DirectionUpdate,
6 SummonedAnimation). Every bundle carries the same 132 disc skills (10001-10138 minus 10099/10100/10121/10126/10130/10137)
plus the owner's kicker skill (2000N, empty). Only the **timing** (`_startTime`, `_compatibilityTime`) and
`_summonOffsetPosition` differ per kicker — the collider/bullet/hit master ids (`_intParameters[15]`, `[14]`, `[16]`)
and the forced-move parameters are identical in all captured bundles.

Hit boxes themselves live in `actioneditor/aed_master.unity3d` (`ActionMasterData skill_NNNNN`: `_bullet`, `_collision`, `_hit`
rows referenced by those ids).

## The bug

The capture only preserved **`aed_001` (Tsubame), `aed_004` (Kite), `aed_005` (Owlbert), `aed_008` (Anna),
`aed_011` (Diatrius)** and `aed_master`. For the other nine kickers `LoadManager.GetCacheActionAsset` returned null,
`LoadAssetData` registered nothing, and every disc ran with an empty timeline:

* discs typed `MoveAttack` (3) threw `NullReferenceException` in `MoveAttackSkillAction..ctor`
  (`ldr s8, [_forcedMovementEventItem + 0x28]`) → `PlayerStateSkill.BeginAction` never completed → the kicker froze
  (this is the "Leorex works on Tsubame, soft-locks Ruriha/Hitagi" report; bots produced the same stack every few
  seconds in `.local/logcat-*.txt`);
* every other disc "cast" but created no effect, collider or bullet.

Independently, eleven discs in `config/masters_skill.json` were typed 3 although their timeline has no
ForcedMovement event, which froze **every** kicker: 10002, 10008, 10019, 10020, 10021, 10030, 10034, 10042, 10051,
10134, 10135.

## The fix

1. `scripts/build-action-asset-bundles.py` builds the nine missing bundles from a donor bundle: same event data,
   internal names renamed `aed_DDD` → `aed_NNN`, and a **new serialized-file name** (`CAB-…`) — Unity refuses to load
   two bundles that share a CAB name and `MatchingScene` loads all 14 action assets at once, so plain Octo name
   aliases would have failed for every kicker after the first. Output: the nine runtime bundles under
   `content/resources/actioneditor/` (explicitly tracked exceptions to the broad `*.bundle` ignore; this keeps
   fresh clones usable without the external assets repo) + `action-asset-aed-NNN` entries in
   `config/resources/title-minimum.json` (octoId 5000+kicker, objectName `aed0NN`). Donor chosen by the smallest mean
   difference of the `skill_*_action` clip lengths in the kickers' `pc_NNN_001` animator controllers:

   | kicker | donor | kicker | donor | kicker | donor |
   | --- | --- | --- | --- | --- | --- |
   | 2 Ruriha | 005 | 7 Grenhawk | 004 | 12 Buzzy | 005 |
   | 3 Coco | 005 | 9 Jay | 005 | 13 Hitagi | 011 |
   | 6 Pitophy | 005 | 10 Yuyan | 005 | 14 Sid | 011 |

   Consequence: effects/colliders of those nine kickers fire at the donor's hand-tuned time (differences are a few
   tenths of a second) and the pet spawns at the donor's offset. Real per-kicker timings would need the original
   bundles; they are not in the capture. Changing a donor = edit `DONORS` in the script, rerun it, bump the revision,
   rerun `build-title-resource-catalog.py`.
2. Octo `revision` 16 → 17 (`fromRevisions` now includes 17) and `python scripts/build-title-resource-catalog.py`
   regenerated `config/fixtures/resource-list-12345*.json` (+ new `-from-17`) and `config/resources/catalog.json`.
   The catalog/URL format now use the direct host from `config/apk-direct-server.local.json`
   (`http://192.168.68.55:18080/cdn/{o}`; the committed files used `10.0.2.2`, which StrictMode rejects for
   downloads). A client whose cached database is at revision 16 requests `/v1/list/12345/16`, receives the full list
   and upserts it (`DataManager.ConstructDictionary` uses `Dictionary.set_Item`), then downloads the nine new objects
   from `/cdn/aed0NN` on first use (or `scripts/seed-device-cache.py`, which now also packs `content/resources`).
3. `config/masters_skill.json`: the eleven skills above were retyped from the structure of their timeline
   (see the table below; siblings with the identical bullet/collider template kept their type):
   10002/10008/10019/10021/10134/10135 → 1 ShotAttack, 10020/10030 → 2 AroundAttack, 10034/10042/10051 → 4 FrontAttack.
4. `scripts/generate_combat_masters.py` now enforces the rule *`skillActionType 3` ⇒ skill in
   `DISC_SKILLS_WITH_FORCED_MOVE`* (falls back to 1 and prints the id).

## Per-kicker cast times (2026-09-20)

The real game had a different disc activation time per kicker *and* disc category (games.app-liv.jp/archives/431798,
seconds "from flick to effect", e.g. close-range: Yuyan 0.6 … Owlbert/Sid 1.25; rush: Diatrius/Hitagi 1.0 … Kite 1.8).
Those numbers line up with the captured bundles: the first Effect/Collider clip `_startTime` of a category's discs is
the Appliv time minus a per-category constant (close-range −0.05, rush −0.15, trap −0.9, warp −0.6, heal/buff
`_compatibilityTime` −0.65) and kickers differ by the same delta in `_compatibilityTime` and every clip start.
`build-action-asset-bundles.py` therefore shifts, per disc skill, the group's `_compatibilityTime` and all clip
`_startTime`s of the nine generated bundles by `CAST_TIMES[kicker][cat] − CAST_TIMES[donor][cat]` (floats patched in
place in the serialized `ActionEvent`, category from `docs/disc_cards.json`; never below 0; `--no-retime` keeps the
donor timing). Bundles built this way are described so in `title-minimum.json`; changing `CAST_TIMES` or a donor
still needs a revision bump + `build-title-resource-catalog.py` (revision 26 = first retimed set). A bump = raise `revision`
AND append the new number to `fromRevisions` (an up-to-date client asks `/v1/list/12345/<current>` and needs the empty
delta fixture; without it the game shows a communication error).

## Octo bundle container

Every captured bundle is a standard UnityFS 6 file with two deterministic tweaks (`build-action-asset-bundles.py`
implements both directions; the assets-repo `reconstruct_unity_bundles.py` accepts its output like a captured file):

* header: `XOR("UnityFS", 6F 0F FA 46 D3 28 3A)` (7 bytes) + standard header from byte 3 on (`"tyFS\0"`, version,
  unity versions, size, sizes, flags) — i.e. 4 bytes longer than stock, size field unchanged;
* byte 5 of the LZ4-compressed blocks-info is XOR 0xFF.

(`Kick-Flight-Assets/reconstruct_unity_bundles.py` undoes this; its "repairs" are all that single flipped byte.)

## Timeline index (from `aed_001`; identical structure in the other bundles)

Disc names in this table are the pre-`disc_cards.json` guesses and several are wrong (10038 is Red Mine, not Blox;
10001 is Leorex; 10013 Boarush; 10108 Dragarmr; 10102 Blox …) — trust the skill id column and `masters_disc.json`.

Legend: *effects* = Effect clips; *colliders* = Collider clips with their `ActionMaster` collision (bullet id when the
collider rides a bullet, shape, radius start->end, cylinder length, lifetime); *forced move* = ForcedMovement clip
(`_intParameters[2]` = TargetPositionType, `_speed`). Recurring templates:

* `sphere r1.25 0.5s` + forced move (75 u/s, target 2) — the dash attack (MoveAttack) template;
* `bullet -> sphere r0.75 0.67s` — single homing bullet; four of them at 2.17s — four-bullet volley;
* `bullet -> cylinder r1 L1->24 0.83s` — lance/beam that extends 24 u;
* `sphere r2->8 0.67s` (no bullet) — expanding burst in front;
* `box r1.25 0.33s` (origin centre, scale 2) — short frontal hit;
* `sphere r7 20s` + `sphere r7 0.83s` — 20 s field around a summon plus an instant hit;
* `sphere r10 15s` + `bullet -> sphere r0.5 4.33s` — a 15 s sentry that fires;
* no clips at all — the pet (`summon/sm_NNNN_0`) does everything itself (heals 10067-10078, several attacks).

| skill | disc | effects | colliders (bullet -> shape, radius, life) | forced move | current type |
| --- | --- | --- | --- | --- | --- |
| 10001 | Flamezaurer | 1 | sphere r1.25 0.5s | yes (target 2, 75 u/s) | 4 / cat 0 |
| 10002 | Gaimos | 2 | bullet 101 -> sphere r0.75 0.666667s |  | 1 / cat 0 |
| 10003 | Rage Kong | 2 | bullet 102 -> sphere r0.75 0.666667s |  | 2 / cat 0 |
| 10004 | Wolfang | 2 | bullet 128 -> sphere r0.75 0.666667s |  | 4 / cat 0 |
| 10005 | Hellzaurer | 2 | bullet 131 -> sphere r0.75 0.666667s |  | 5 / cat 0 |
| 10006 | Frost Sting | 2 | bullet 130 -> sphere r0.75 0.666667s |  | 1 / cat 0 |
| 10007 | Larx | 8 | bullet 113 -> sphere r0.5 2.16667s; bullet 114 -> sphere r0.5 2.16667s; bullet 115 -> sphere r0.5 2.16667s; bullet 116 -> sphere r0.5 2.16667s |  | 2 / cat 0 |
| 10008 | Inoshin | 1 | bullet 1 -> sphere r0.75 0.833333s |  | 1 / cat 0 |
| 10009 | Whaleria | 2 | bullet 74 -> cylinder r1 L1->24 0.833333s |  | 4 / cat 0 |
| 10010 | Gastor | 1 | sphere r1.25 0.5s | yes (target 2, 50 u/s) | 4 / cat 0 |
| 10011 | Fighter Turtle | 1 | bullet 84 -> sphere r1.25 0.5s | yes (target 2, 50 u/s) | 3 / cat 0 |
| 10012 | Bomb Star | 1 | bullet 133 -> sphere r1.25 0.5s | yes (target 2, 50 u/s) | 1 / cat 0 |
| 10013 | Fairy Lizard | 1 | bullet 134 -> sphere r1.25 0.5s | yes (target 1, 50 u/s) | 2 / cat 0 |
| 10014 | Uber Beaver | 1 | bullet 48 -> sphere r1.25 0.5s | yes (target 2, 50 u/s) | 2 / cat 0 |
| 10015 | Bubble Star | 1 | bullet 9 -> box r1.25 0.333333s |  | 1 / cat 0 |
| 10016 | Red Blaster | 1 | box r0 0.333333s |  | 1 / cat 0 |
| 10017 | Air Blaster | 1 | box r1.5 0.333333s |  | 1 / cat 0 |
| 10018 | Blue Blaster | 1 | box r1.5 0.333333s |  | 1 / cat 0 |
| 10019 | Jet Shark | 1 | box r0 0.333333s |  | 1 / cat 0 |
| 10020 | Rush Blade | 1 | sphere r2->8 0.666667s |  | 2 / cat 0 |
| 10021 | Propedile | 1 | bullet 70 -> sphere r2->8 0.666667s |  | 1 / cat 0 |
| 10022 | Volcatus | 1 | sphere r2->8 0.666667s |  | 2 / cat 0 |
| 10023 | Kazetachinu (Viento Alzado) | 1 | sphere r2->8 0.666667s |  | 2 / cat 0 |
| 10024 | Hanapoogon | 1 | sphere r2->8 0.666667s |  | 2 / cat 0 |
| 10025 | Lapibit | 1 | sphere r2->8 0.666667s |  | 4 / cat 0 |
| 10026 | Armed Calis | 3 | bullet 127 -> cylinder r0.5->5 L1 0.833333s | yes (target 0, 40 u/s) | 4 / cat 0 |
| 10027 | Leorex | 8 | bullet 97 -> sphere r0.75 2.16667s; bullet 98 -> sphere r0.75 2.16667s; bullet 99 -> sphere r0.75 2.16667s; bullet 100 -> sphere r0.75 2.16667s | yes (target 3, 25 u/s) | 3 / cat 0 |
| 10028 | Gekodarma | 2 | bullet 187 -> cylinder r1 L1->24 0.833333s |  | 1 / cat 0 |
| 10029 | Mantalion | 1 | sphere r2->8 0.666667s |  | 1 / cat 0 |
| 10030 | Assault Lance | 1 | sphere r2->8 0.666667s |  | 2 / cat 0 |
| 10031 | Bunny Burn | 1 | bullet 21 -> cylinder r2.25->9 L30 8s |  | 2 / cat 0 |
| 10032 | Todorock | 2 | bullet 118 -> cylinder r1 L1->24 0.833333s |  | 4 / cat 0 |
| 10033 | Birilit | 0 | - |  | 2 / cat 0 |
| 10034 | Jet Tamago | 2 | bullet 126 -> cylinder r1 L1->24 0.833333s |  | 4 / cat 0 |
| 10035 | Rhinot | 2 | bullet 120 -> cylinder r1 L1->24 0.833333s |  | 4 / cat 0 |
| 10036 | Hatakidora | 1 | sphere r7 20s; sphere r7 0.833333s |  | 4 / cat 0 |
| 10037 | Yanchara | 1 | sphere r7 20s; sphere r7 0.833333s |  | 4 / cat 0 |
| 10038 | Blox | 1 | sphere r7 20s; sphere r7 0.833333s |  | 4 / cat 0 |
| 10039 | Jack Upper | 1 | sphere r7 20s; sphere r7 0.833333s |  | 4 / cat 0 |
| 10040 | Kabandos | 1 | sphere r7 20s; sphere r7 0.833333s |  | 4 / cat 0 |
| 10041 | Jet Hammer | 1 | sphere r7 20s; sphere r7 0.833333s |  | 1 / cat 0 |
| 10042 | Hellmuck | 1 | sphere r10 15s; bullet 80 -> sphere r0.5 4.33333s |  | 4 / cat 0 |
| 10043 | Tidalion | 1 | sphere r10 15s; bullet 81 -> sphere r0.5 4.33333s |  | 2 / cat 0 |
| 10044 | Hakaijuki (Excavadora) | 1 | sphere r10 15s; bullet 82 -> sphere r0.5 4.33333s |  | 4 / cat 0 |
| 10045 | - | 8 | bullet 192 -> sphere r0.5 2.16667s; bullet 193 -> sphere r0.5 2.16667s; bullet 194 -> sphere r0.5 2.16667s; bullet 195 -> sphere r0.5 2.16667s |  | (no Skill row) |
| 10046 | Majimajin | 1 | sphere r10 15s; bullet 79 -> sphere r0.5 4.33333s |  | 4 / cat 0 |
| 10047 | Celestia | 2 | bullet 123 -> sphere r0.75 0.666667s |  | 2 / cat 0 |
| 10048 | Octoverse | 1 | sphere r2->8 0.666667s |  | 4 / cat 0 |
| 10049 | Gagagatling | 1 | sphere r7 20s; sphere r7 0.833333s |  | 5 / cat 0 |
| 10050 | Gatling Ultra | 1 | sphere r2.5->10 10s |  | 5 / cat 0 |
| 10051 | Dragarum | 2 | bullet 124 -> cylinder r1 L1->24 0.833333s |  | 4 / cat 0 |
| 10052 | Foxy | 2 | bullet 125 -> cylinder r1 L1->24 0.833333s |  | 2 / cat 0 |
| 10053 | Roseme | 0 | - |  | 2 / cat 0 |
| 10054 | - | 1 | cylinder r7 L15 14s |  | (no Skill row) |
| 10055 | Avasalam | 0 | - |  | 4 / cat 0 |
| 10056 | Nutautsubon | 0 | - |  | 4 / cat 0 |
| 10057 | Sibilydra | 0 | - |  | 5 / cat 0 |
| 10058 | Wizard Biloco | 0 | - |  | 1 / cat 0 |
| 10059 | Bakuryu (Dragón Explosivo) | 0 | - |  | 4 / cat 0 |
| 10060 | Junk Bullet | 0 | - |  | 1 / cat 0 |
| 10061 | Bala Venenosa | 0 | - |  | 1 / cat 0 |
| 10062 | Bomb Snake | 0 | - |  | 4 / cat 0 |
| 10063 | Melaki Launcher | 1 | - | yes (target 1, 25 u/s) | 1 / cat 0 |
| 10064 | Through Majin | 0 | - |  | 4 / cat 0 |
| 10065 | Box Shooter | 0 | - |  | 1 / cat 0 |
| 10066 | Vampkin | 0 | - |  | 1 / cat 0 |
| 10067 | Phenilora | 0 | - |  | 6 / cat 1 |
| 10068 | Pegasia | 0 | - | yes (target 1, 0 u/s) | 6 / cat 1 |
| 10069 | Kyujack | 0 | - |  | 6 / cat 1 |
| 10070 | Healmyan | 0 | - |  | 6 / cat 1 |
| 10071 | Cupalooper | 0 | - |  | 6 / cat 1 |
| 10072 | Pico Leaf | 0 | - |  | 6 / cat 1 |
| 10073 | Umigami (Dios Marino) | 0 | - | yes (target 4, 0 u/s) | 6 / cat 1 |
| 10074 | Cure Wee | 0 | - | yes (target 4, 0 u/s) | 6 / cat 1 |
| 10075 | Botiquín Médico | 0 | - |  | 6 / cat 1 |
| 10076 | Nursdroid | 0 | - | yes (target 1, 0 u/s) | 6 / cat 1 |
| 10077 | Enegaeru | 0 | - | yes (target 1, 0 u/s) | 6 / cat 1 |
| 10078 | Airgaeru | 0 | - |  | 6 / cat 1 |
| 10079 | Powerwanwa | 8 | bullet 88 -> sphere r0.75 2.16667s; bullet 89 -> sphere r0.75 2.16667s; bullet 90 -> sphere r0.75 2.16667s; bullet 91 -> sphere r0.75 2.16667s | yes (target 3, 25 u/s) | 6 / cat 1 |
| 10080 | Botella Boost | 2 | bullet 107 -> sphere r0.5 2s |  | 6 / cat 1 |
| 10081 | Ganko Bulld | 2 | bullet 106 -> sphere r0.5 2s |  | 6 / cat 1 |
| 10082 | Cheer Louder | 1 | sphere r7 20s; sphere r7 0.833333s |  | 6 / cat 2 |
| 10083 | Flash Barrier | 1 | - | yes (target 1, 25 u/s) | 6 / cat 2 |
| 10084 | Spoodle | 2 | bullet 184 -> sphere r0.75 0.666667s |  | 6 / cat 2 |
| 10085 | Fightgaroo | 0 | - |  | 6 / cat 2 |
| 10086 | Shell Kabuto | 1 | bullet 186 -> cylinder r2.25->9 L30 8s |  | 6 / cat 2 |
| 10087 | Tetra Shield | 0 | - |  | 6 / cat 2 |
| 10088 | Mamorigani (Cangrejo Guardián) | 1 | box r0 0.333333s |  | 6 / cat 2 |
| 10089 | Encouragio | 1 | bullet 135 -> sphere r1.25 0.5s | yes (target 2, 50 u/s) | 6 / cat 2 |
| 10090 | Pompokonushi | 2 | bullet 136 -> sphere r0.75 0.666667s |  | 6 / cat 2 |
| 10091 | Starlion | 1 | - | yes (target 1, 25 u/s) | 6 / cat 2 |
| 10092 | Galaxyshield | 0 | - |  | 6 / cat 2 |
| 10093 | Antraise | 3 | bullet 147 -> sphere r0.75 0.666667s; bullet 148 -> sphere r0.75->7 0.833333s |  | 6 / cat 2 |
| 10094 | Tenkutei (Emperador Celeste) | 0 | - |  | 6 / cat 2 |
| 10095 | Ilda Ruma | 2 | bullet 137 -> sphere r0.5 2s |  | 6 / cat 2 |
| 10096 | - | 1 | sphere r1.25 0.5s | yes (target 2, 75 u/s) | (no Skill row) |
| 10097 | Wildia | 1 | sphere r7 20s; sphere r7 0.833333s |  | 6 / cat 2 |
| 10098 | Pop Candy | 8 | bullet 142 -> sphere r0.5 2.16667s; bullet 143 -> sphere r0.5 2.16667s; bullet 144 -> sphere r0.5 2.16667s; bullet 145 -> sphere r0.5 2.16667s |  | 6 / cat 2 |
| 10101 | Izanahime | 0 | - |  | 7 / cat 3 |
| 10102 | Booby Bomber | 1 | box r1.25 0.333333s |  | 7 / cat 3 |
| 10103 | Mina Roja | 1 | sphere r2->10 0.666667s |  | 7 / cat 3 |
| 10104 | Mina Verde | 0 | - | yes (target 1, 0 u/s) | 7 / cat 3 |
| 10105 | Mina Azul | 1 | sphere r10 8s; bullet 146 -> sphere r0.5 4.33333s |  | 7 / cat 3 |
| 10106 | Híper Bomba | 1 | sphere r2->8 0.666667s |  | 7 / cat 3 |
| 10107 | Stun Nova | 1 | box r0 0.333333s |  | 7 / cat 3 |
| 10108 | Septacopter | 1 | sphere r1.25 0.5s | yes (target 2, 75 u/s) | 7 / cat 3 |
| 10109 | Rage Bulld | 2 | bullet 149 -> sphere r0.5 2.16667s |  | 7 / cat 3 |
| 10110 | Torreta Act | 0 | - |  | 7 / cat 3 |
| 10111 | Killer Billet | 2 | bullet 153 -> sphere r0.75 0.666667s |  | 7 / cat 3 |
| 10112 | Noromaimai | 8 | bullet 154 -> sphere r0.75 2.16667s; bullet 155 -> sphere r0.75 2.16667s; bullet 156 -> sphere r0.75 2.16667s; bullet 157 -> sphere r0.75 2.16667s | yes (target 3, 25 u/s) | 7 / cat 3 |
| 10113 | Kamo Gangan | 0 | - | yes (target 1, 0 u/s) | 7 / cat 3 |
| 10114 | Mina Furtiva | 1 | sphere r7 30s; sphere r7 0.833333s |  | 7 / cat 3 |
| 10115 | Evil Crow | 3 | bullet 163 -> sphere r0.75 0.666667s; bullet 164 -> sphere r0.75->7 0.833333s |  | 7 / cat 3 |
| 10116 | Aero Jammer | 2 | bullet 165 -> cylinder r1 L1->24 0.833333s |  | 7 / cat 3 |
| 10117 | Rebelio Wolf | 0 | - |  | 7 / cat 3 |
| 10118 | Harimanbo | 1 | bullet 161 -> sphere r1.25 0.5s | yes (target 2, 50 u/s) | 7 / cat 3 |
| 10119 | Hell Pumpkin | 0 | - |  | 7 / cat 3 |
| 10120 | War Lantern | 1 | sphere r2->10 0.666667s |  | 7 / cat 3 |
| 10122 | Arc Orphin | 1 | - | yes (target 1, 25 u/s) | 8 / cat 4 |
| 10123 | Portal de Inicio | 2 | bullet 191 -> sphere r0.5 2s |  | 8 / cat 4 |
| 10124 | Portal Asesino | 0 | - | yes (target 1, 0 u/s) | 8 / cat 4 |
| 10125 | Supportdroid | 1 | box r0 0.333333s |  | 8 / cat 4 |
| 10127 | Killer Secta | 2 | bullet 167 -> cylinder r1 L1->24 0.833333s |  | 8 / cat 4 |
| 10128 | Neo Illumi | 1 | sphere r10 15s; bullet 174 -> sphere r0.5 4.33333s |  | 8 / cat 4 |
| 10129 | Princia | 8 | bullet 175 -> sphere r0.5 2.16667s; bullet 176 -> sphere r0.5 2.16667s; bullet 177 -> sphere r0.5 2.16667s; bullet 178 -> sphere r0.5 2.16667s |  | 8 / cat 4 |
| 10131 | Portal Vínculo | 0 | - |  | 8 / cat 4 |
| 10132 | Momondra | 1 | bullet 173 -> sphere r1.25 0.5s | yes (target 2, 50 u/s) | 3 / cat 5 |
| 10133 | - | 0 | - |  | (no Skill row) |
| 10134 | Momonbon | 1 | sphere r60 15s; bullet 189 -> sphere r1->7 1.5s |  | 1 / cat 5 |
| 10135 | Later | 1 | box r1.25 0.333333s |  | 1 / cat 5 |
| 10136 | - | 0 | - |  | (no Skill row) |
| 10138 | - | 1 | sphere r2->10 0.666667s |  | (no Skill row) |
