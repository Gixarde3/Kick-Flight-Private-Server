# Combat masters — what to fill in

The client freezes a kicker mid-animation when the data behind an attack, disc, kicker
skill or special skill is missing: the animation event handler throws
`NullReferenceException` (`PlayerParameter.GetWeaponAttackDamageInitInfo`,
`DamageCollisionData..ctor`, `CollisionManager.AddCollision` … all under
`CharacterAnimatorBase.AnimationEvent`) and the action never finishes. Every table
below is a `config/masters_*.json` file served by `DemoSessionApi`; the client
re-downloads a table whenever its content hash changes (restart the server after
editing). `scripts/generate_combat_masters.py` writes structurally valid templates
(right ids/keys, neutral numbers) — this document says what each column means so
the real effects can be typed in.

Field names in the JSON are exactly the C# field names of the `*MasterData` classes
(Il2CppDumper `dump.cs`); every row also has `id` (any unique int per table).

Write **real** numbers in the files. A few integer columns are anti-tamper obfuscated in the client
(the getter subtracts a constant: `Skill.coolTime` −230, `Disc.minHp/maxHp/minAttack/maxAttack`
−928/−715/−167/−685, `KickerAbility.overlapCount` −203, `SpecialSkillHit.fixedDamage` −454); the server
adds those offsets when serving (`DemoSessionApi.ApplyObscuredOffsets`), so never add them by hand.

## Id conventions (must match assets shipped in the APK)

| thing | id | why |
| --- | --- | --- |
| kicker | 1..14 | `KickerParameter.kickerId` |
| kicker skill (the skill button) | **20000 + kickerId** (20001..20014) | `KickerParameter.skillId` → `Skill.id`; the APK `ActionMaster` entries `skill_20001..20014` carry the kicker-skill hit boxes and `Effect/ks/…` VFX (`skill_1..14` exist but are empty placeholders) |
| disc | 3010001..3010126 | `Disc.id`, thumbnails `ui/disc/thumbnail_3010NNN` |
| disc skill | **10000 + NNN** (10001..10138) | `Disc.skillId` → `Skill.id`; `ActionMaster` has `skill_10001..skill_10138` (hit boxes, bullets, timing live there, inside the APK) |
| disc pet (summon) | **NNN** (1..138) | `Skill.summonId` → `Summon.id`; model bundles `summon/sm_NNNN_0` / `_1` exist for every NNN except 99, 100, 126, 130, 137 |
| special skill | kickerId (1..14) | `SpecialSkill.id` is only used to join its own `SpecialSkill*` sub-tables (`specialSkillId`); the row is found by `kickerId` |
| wind (stage gimmick) skill | 40001 | `ActionMaster` `skill_40001` |

`generate_combat_masters.py` already remapped `masters_skill.json` / `masters_disc.json`
to these ids (disc skills used to be 3010NNN, which `SkillActionDataManager.GetActionMasterData`
could not resolve — that alone froze every disc).

## Resource paths you can reference

Effects are ResourceManager paths without extension; these bundles exist:

* weapon hit effects `effect/wp/ef_wp_KKK_001/ef_wp_KKK_001` for kickers 001-007, 009-011, 013, 014
* kicker skill effects `effect/ks/ef_ks_KKK_001/ef_ks_KKK_001` for all 14 kickers
* special skill effects `effect/ss/ef_ss_KKK_001/ef_ss_KKK_001` for all 14 kickers
* disc effects `effect/ds/ef_ds_NNNN/ef_ds_NNNN` for discs 2-9, 13, 15, 16, 20, 22-27, 29-32, 34, 35, 37, 41, 45, 47-51, 79-82, 84, 86, 90, 93, 95, 97, 103, 106, 107, 109, 112, 115, 116, 123, 125, 127, 129, 134, 138
* common hit effects `effect/cm/ef_cm_001..036/ef_cm_NNN` (what `commonHitEffectType` picks from)
* summon models `summon/sm_NNNN_0` (in-game) and `summon/sm_NNNN_1` (gacha/detail)

Leave `effectPath`/`resourcePath` as `""` to use only the `commonHitEffectType` / default bullet.
`seId`, `hitSeId`, `loopSeId`, `executeSeId` are CRI ADX cue ids; `0` = silent (unknown ids just play nothing).

## Enums

| enum | values |
| --- | --- |
| `HitEffectType` (`commonHitEffectType`) | 0 None, 1 CommonS, 2 CommonM, 3 CommonL, 4 SlashS, 5 SlashM, 6 SlashL, 7 BlowS, 8 BlowM, 9 BlowL, 10 GunS, 11 GunM, 12 GunL |
| `CollisionType` | 0 Box, 1 Sphere, 2 Capsule, 3 Cylinder |
| `CollisionHitType` | 0 One (first target only), 1 All, 2 AllAndRehit, 3 AllCount, 4 AllAndRehitCount |
| `hitLayer` | Unity layer mask; `4864` (0x1300) is what the shipped disc collisions use = players + guardians |
| `PlayerBoneType` (`parentBone`) | -1 None, 0 RightHand, 1 LeftHand, 2 Hip, 3 Neck, 4 RightHeel, 5 LeftHeel, 6 Head, 7 Spine, 8 Front, 9 Common |
| `BulletEndType` | 0 Normal, 1 FadeOut |
| `BulletActionType` | 0 Normal, 1 RocketLauncherSkill |
| `ConditionType` | 1 AttackRate, 2 SpeedRate, 3 DefenseRate, 4 DamageRate, 5 Poison, 6 Paralysis, 7 Burn, 8 Stun, 9 Silent, 10 Drain, 11 Regeneration, 12 Inhale, 13 BlowoffCollider, 14 Restrainted, 15 Restraint, 16 Prison, 17 Dot, 18 Smog, 19 SmogDisturb, 20 SmogProtection, 21 Gravity, 22 Confusion, 23 PullIn, 24 Stealth, 25 Panda, 26 ShieldForward, 27 ShieldAll, 28 AttackSpeedRate, 29 RocketLauncherTarget, 30 AutoMove, 31 BoostHealSpeedRate, 32 SpecialSkillGaugeRate, 34 OneShotKiller |
| `ConditionTriggerType` | 0 None, 1 ReceiveDamage, 2 AddDamage, 3 Execute (on use), 4 EnterTrap, 5 EnterEnemyTeamTrap, 6 EnterMyTeamTrap, 7 All |
| `SkillType` | 1 Disc, 2 Kicker, 3 Wind |
| `SkillActionType` | 1 ShotAttack, 2 AroundAttack, 3 MoveAttack, 4 FrontAttack, 5 BeamAttack, 6 Support, 7 Trap, 8 Warp, 9 Sword, 10 TwoGuns, 11 Hammer, 12 ThrowingStar, 13 Drone, 14 RocketLauncher, 15 Gun, 16 PunchGlove, 17 Bowgun, 18 Shield, 19 Bat, 20 Nunchaku, 21 VerticalLoop, 22 AutoMove, 23 JapaneseSword, 24 Laser |
| `SkillCategoryType` | 0 Attack, 1 Heal, 2 Buff, 3 Trap, 4 Warp, 5 Move |
| `TargetAreaType` (the aim preview) | 0 None, 2 Cube, 5 Cylinder, 8 Sphere, 11 CylinderLong, 14 Plane, 17 Cone |
| `AttributeType` | 0 None, 1 Fire, 2 Water, 3 Wind |
| `SummonCharacterType` | 0 Normal (pet stays with you), 1 Bullet (the pet *is* the projectile), 2 OneBullet, 3 AttackTrap |
| `TrapType` | 0 None, 1 Slow, 2 Silent, 3 Turret, 4 Decoy, 5 Inhale, 6 Smog, 7 Bomb, 8 Condition, 9 Empty, 10 BatBomb |
| `SkillHealType` | 1 Hp, 2 BoostGauge, 3 HpDrain, 4 SpDrain, 5 Condition |
| `BlowOffDirectionType` | 0 None, 1 Up, 2 Down, 3 Press, 4 AttackDirection |
| `WeaponType` (`KickerParameter.weaponType`) | 0 Sword, 1 TwoGuns, 2 Hammer, 3 ThrowingStar, 4 Drone, 5 RocketLauncher, 6 Gun, 7 PunchGlove, 8 Bowgun, 9 Shield, 10 Bat, 11 Nunchaku, 12 JapaneseSword, 13 Laser |

## 1. Basic attacks — `masters_weapon_attack*.json`

`PlayerWeaponAttackParameter(kickerId)` takes every `WeaponAttack` row of the kicker
(`attackCount` = combo step **0, 1, 2 …** — zero-based, `WeaponAttackActionBase.get_ComboCount` is `_totalComboCount % MaxAttackComboCount`; the number of rows is the combo length) and
joins, by `kickerId` + `attackCount`, **one `WeaponAttackHit` and one
`WeaponAttackCollision` row (both mandatory)**, an optional `WeaponAttackBullet`
row (ranged weapons) and any `WeaponAttackCondition` rows.

| file | columns |
| --- | --- |
| `masters_weapon_attack.json` | `kickerId`, `attackCount`, `coefficient` (× kicker attack → damage), `seId` |
| `masters_weapon_attack_hit.json` | `kickerId`, `attackCount`, `commonHitEffectType`, `hitSeId`, `effectPath`, `parentBone`, `offsetX/Y/Z`, `transformType` (0 = world), `shakeVolume` (camera shake 0..1), `knockBackFlag`, `fixedDamage` (0 = use coefficient) |
| `masters_weapon_attack_collision.json` | `kickerId`, `attackCount`, `collisionType`, `collisionHitType`, `hitLayer`, `radius`, `length` (capsule/cylinder), `originCenterFlag` (false = box/sphere starts at the kicker's front), `scaleX/Y/Z`, `moveRadius` (sweep radius while the kicker moves during the swing) |
| `masters_weapon_attack_bullet.json` | `kickerId`, `attackCount`, `distance` (despawn range), `speed`, `resourcePath` (bullet prefab, `""` = default), `loopSeId`, `homingAngle` (deg, 0 = straight), `endType`, `actionType`, `removeOnOwnerDeadFlag` |
| `masters_weapon_attack_condition.json` | `kickerId`, `attackCount`, `conditionType`, `duration`, `interval`, `effectValue`, `triggerType` — status applied on hit (e.g. Burn for 3 s) |

Template: 3-hit combos for all 14 kickers; slash effects for sword-likes, blow for
hammer/glove/shield, gun for ranged; sphere radius 2.5/2.5/3.0 (melee) or a 0.8 sphere
riding a 40 u/s bullet with 15° homing (ranged, `weaponType` in TwoGuns/ThrowingStar/
Drone/RocketLauncher/Gun/Bowgun/Laser).

## 2. Discs and kicker skills — `masters_skill.json` + sub-tables

`SkillParameterBase.InitializeData(characterId, skillId)` reads `Skill[skillId]`,
`ActionMaster[skillId]` (APK) and then *optionally* every `SkillHeal`, `SkillCondition`,
`SkillBlowOff`, `SkillPullIn`, `SkillTrap` row whose `skillId` matches (a skill may have
several). Hit boxes / bullets / hit effects of discs come from the APK ActionMaster,
not from the server.

| file | columns |
| --- | --- |
| `masters_skill.json` | `description`, `skillType`, `skillActionType`, `skillCategoryType`, `targetAreaType`, `coolTime` (s), `range` (u), `speed` (u/s, bullets/moves), `summonId`, `attributeType`, `seId`, `coefficient` (× attack) |

`skillActionType` is not free-form — it selects the C# action class, and an unknown value makes
`GetSkillAction` return null, which soft-locks the kicker in the skill state:

* disc skills (`skillType` 1): only **1 ShotAttack, 2 AroundAttack, 3 MoveAttack, 4 FrontAttack, 5 BeamAttack,
  6 Support, 7 Trap, 8 Warp, 21 VerticalLoop, 22 AutoMove**. A Trap action also needs a `masters_skill_trap.json` row.
* kicker skills (`skillType` 2, ids 20001-20014): only the weapon action of that kicker — **`weaponType` + 9**
  (Sword 9 … Nunchaku 20), JapaneseSword 23, Laser 24. The generator sets this from `masters_kicker_parameter.json`.
| `masters_skill_heal.json` | `skillId`, `skillHealType`, `coefficient` (× attack → HP, or gauge amount) |
| `masters_skill_condition.json` | `skillId`, `conditionType`, `duration` (s), `interval` (s, 0 = one shot; for Dot/Poison ticks), `effectValue` (rate: 1.2 = +20 %, or amount), `triggerType` (3 Execute = buff on cast, 1 ReceiveDamage / 2 AddDamage = on hit) |
| `masters_skill_blow_off.json` | `skillId`, `distance`, `speed`, `rigorTime` (stun after landing), `directionType` |
| `masters_skill_pull_in.json` | `skillId`, `distance`, `speed` |
| `masters_skill_trap.json` | `skillId`, `trapType`, `duration`, `radius`, `effectValue` (e.g. 0.5 = half speed for Slow), `interval`, `executeSeId`, `effectPath`, `screenEffectPath` (fullscreen effect for whoever steps in) |

Template: one `SkillHeal` row per `skillCategoryType` 1 skill, one `AttackRate ×1.2 for 10 s`
condition per Buff (2) skill, one `Slow` trap per Trap (3) skill. Attack discs need nothing
here unless they inflict a status or blow-off.

## 3. Pets — `masters_summon.json`

Needed for every `Skill.summonId != 0` (`SummonParameter..ctor`, `PlayerStateSkill.CreateSummon`).

| column | meaning |
| --- | --- |
| `id` | = `summonId` = disc number NNN |
| `modelId` | loads `summon/sm_{modelId:04d}_0`; keep = id |
| `summonCharacterType` | 0 pet, 1 the pet is the projectile, 2 one-shot projectile, 3 stationary attack trap |
| `positionX/Y/Z` | spawn offset from the kicker (u) |
| `seId` | spawn cue |
| `gachaPosition*/Rotation*`, `discDetailPosition*/Rotation*` | where the `_1` model sits in the gacha / disc-detail screens |
| `middleModelFlag` | true = use the mid-size model in UI |

## 4. Special skills — `masters_special_skill*.json`

`PlayerSpecialSkilParameter(kickerId)` finds the `SpecialSkill` row by `kickerId` and joins
`SpecialSkillHit` + `SpecialSkillCollision` (mandatory), `SpecialSkillBullet`,
`SpecialSkillBlowOff`, `SpecialSkillTrap`, `SpecialSkillCondition` by `specialSkillId`.

| file | columns |
| --- | --- |
| `masters_special_skill.json` | `kickerId`, `duration` (s the skill state lasts), `coefficient`, `range`, `finishTime` (recovery s) |
| `_hit` / `_collision` / `_bullet` / `_blow_off` / `_trap` / `_condition` | same columns as the weapon / skill tables, keyed by `specialSkillId` |

## 5. Status-effect hit effects — `masters_common_condition_hit.json`

One row per `conditionType` that should show a hit effect when applied
(`commonHitEffectType`, `hitSeId`, `effectPath`, `parentBone`, offsets, `shakeVolume`,
`knockBackFlag`, `fixedDamage`, `conditionType`). Optional; template covers Poison,
Paralysis, Burn, Stun, Silent.

## Still open (not data)

* `KickerParameter.speed` is used directly as flight speed in units/s (`PlayerParameter.GetSpeed`);
  the wiki ratings 0.85-1.30 currently in `masters_kicker_parameter.json` make everyone crawl.
  Multiply the column by ~12 (or whatever feels right — nothing in the client fixes the scale).
* The 180° turn stuck in the reverse-decelerate pose needs a logcat from the moment it happens.
