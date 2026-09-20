#!/usr/bin/env python3
"""
generate_combat_masters.py

Creates the combat master tables the client needs for basic attacks, discs, kicker
skills and special skills to run without NullReferenceExceptions, and fixes the
skill-id linkage so disc skills resolve against the ActionMaster that ships inside
the APK (actioneditor/aed_master.unity3d: disc skills 10001-10138, kicker skills 20001-20014).

Everything written here is a structurally valid *template*: ids and keys are right,
the tuning numbers are neutral defaults. Edit the JSON files under config/ to fill in
the real effects (see docs/COMBAT_MASTERS_FILL_IN.md for the meaning of every column).

Existing files are never overwritten unless --force is given; masters_skill.json and
masters_disc.json are rewritten in place (id remap only) and a .bak copy is kept.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config"

# enums (from Il2CppDumper dump.cs) ------------------------------------------------
HIT_NONE, HIT_COMMON_S, HIT_COMMON_M, HIT_COMMON_L = 0, 1, 2, 3
HIT_SLASH_S, HIT_SLASH_M, HIT_SLASH_L = 4, 5, 6
HIT_BLOW_S, HIT_BLOW_M, HIT_BLOW_L = 7, 8, 9
HIT_GUN_S, HIT_GUN_M, HIT_GUN_L = 10, 11, 12
COL_BOX, COL_SPHERE, COL_CAPSULE, COL_CYLINDER = 0, 1, 2, 3
COLHIT_ONE, COLHIT_ALL = 0, 1
BONE_RIGHT_HAND, BONE_COMMON = 0, 9
# WeaponType
WT_SWORD, WT_TWO_GUNS, WT_HAMMER, WT_THROWING_STAR, WT_DRONE, WT_ROCKET, WT_GUN, WT_PUNCH_GLOVE = range(8)
WT_BOWGUN, WT_SHIELD, WT_BAT, WT_NUNCHAKU, WT_JAPANESE_SWORD, WT_LASER = range(8, 14)
RANGED = {WT_TWO_GUNS, WT_DRONE, WT_ROCKET, WT_GUN, WT_BOWGUN, WT_LASER, WT_THROWING_STAR}
SLASH = {WT_SWORD, WT_JAPANESE_SWORD, WT_NUNCHAKU, WT_BAT}
# SkillCategoryType
CAT_ATTACK, CAT_HEAL, CAT_BUFF, CAT_TRAP, CAT_WARP, CAT_MOVE = range(6)
# ConditionType (subset)
COND_ATTACK_RATE, COND_SPEED_RATE, COND_DEFENSE_RATE = 1, 2, 3
COND_POISON, COND_PARALYSIS, COND_BURN, COND_STUN, COND_SILENT = 5, 6, 7, 8, 9
COND_REGENERATION, COND_SLOWISH = 11, 2
TRIGGER_EXECUTE = 3
TRIGGER_ENTER_TRAP, TRIGGER_ENTER_ENEMY_TRAP, TRIGGER_ENTER_ALLY_TRAP = 4, 5, 6
COND_INHALE, COND_DOT, COND_GRAVITY = 12, 17, 21
# hitLayer used by the shipped ActionMaster collisions (players + guardians)
HIT_LAYER_CHARACTERS = 4864
# fixedDamage (WeaponAttackHit / SpecialSkillHit): when >= 1 the hit does exactly that much damage to PLAYERS instead
# of attack x coefficient (PlayerCharacter.AcceptDamageInfo), so it is 0 for everything except one-shot hits.
# Guardian turrets (NPCGuardian.AcceptDamageInfo) take the raw attack x coefficient damage against their HP, which is
# GuardianParameter.hp per deposited crystal; only when fixedDamage >= 1 does a special case kick in (Kite's special
# drops KickerSpecialSkillMaster.ThrowingStar._guardianDropCrystalCount crystals instead of one-shotting the turret).
# Kickers carry 30-45k HP once four lv10 discs (up to 12044 HP each) are added, so 9999 only left them low. This
# is the value Hitagi's OneShotKiller branch in PlayerCharacter.AcceptDamageInfo hard-codes (0xF423F).
ONE_SHOT_FIXED_DAMAGE = 999999

DISC_ID_BASE = 3010000     # disc ids are 3010001..; skill id = 10000 + n; summon/model id = n
DISC_SKILL_BASE = 10000
BAT_BOMB_SKILL_ID = 40001
KICKER_SKILL_BASE = 20000  # Skill.id of kicker skills; SpecialSkill ids are the plain kickerId

# Disc skills whose APK action-editor timeline (actioneditor/aed_NNN.unity3d, EventItemGroup._list[ClipType.ForcedMovement])
# contains a forced-movement event. MoveAttackSkillAction..ctor dereferences that event unconditionally, so
# skillActionType 3 on any other disc is a guaranteed NullReferenceException that soft-locks the kicker.
# Identical in all five captured bundles (kickers 1, 4, 5, 8, 11).
DISC_SKILLS_WITH_FORCED_MOVE = {
    10001, 10010, 10011, 10012, 10013, 10014, 10026, 10027, 10063, 10068, 10073, 10074, 10076, 10077, 10079,
    10083, 10089, 10091, 10096, 10104, 10108, 10112, 10113, 10118, 10122, 10124, 10132,
}
# Non-trap disc skills whose timeline nevertheless contains a "sensor" collider (Collider clip with
# AttachToType 2 and no damage flag). DiscSkillParameter..ctor then reads SkillTrapMaster.GetDataFromSkillId
# unconditionally, so such a skill needs a masters_skill_trap.json row or every battle with it in a deck NREs
# while loading. 10054 Scorpius: its 14 s continuous cylinder is built as a sensor.
DISC_SKILLS_WITH_SENSOR_COLLIDER = {10054}
# Disc skills whose card type ("MOVE") maps to AutoMove (22) but whose APK timeline is a ShotAttack: four Collider
# clips with MissTargetDirection (intParameters[8]) == 2 plus a 0.47 s ForcedMovement. Only ShotAttackSkillAction
# creates timeline bullets (OnCreateCollider) *and* honours the forced move; its ctor sets IsBackShot from that
# MissTargetDirection, which is the "shoots backwards while dashing" of Pyronkey / Spunkle / Tigre. AutoMoveSkillAction
# has no OnCreateCollider, so as type 22 they dashed and never fired (phone report 2026-09-20).
DISC_ACTION_TYPE_OVERRIDES = {10027: 1, 10079: 1, 10112: 1}


def load(name: str):
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def write(name: str, rows, force: bool) -> None:
    path = CONFIG / name
    if path.exists() and not force:
        print(f"keep    {name} (exists, {len(load(name))} rows) -- use --force to regenerate")
        return
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote   {name} ({len(rows)} rows)")


def remap_skill_ids(force: bool) -> tuple[list, list]:
    """Disc skill ids must equal the ActionMaster ids (10001..10138), not the disc ids."""
    skills = load("masters_skill.json")
    discs = load("masters_disc.json")
    changed = False
    kickers = {k["kickerId"]: k for k in load("masters_kicker_parameter.json")}
    for row in skills:
        if row["id"] > DISC_ID_BASE:
            n = row["id"] - DISC_ID_BASE
            row["id"] = DISC_SKILL_BASE + n
            row["skillType"] = 1  # Disc
            if not row.get("summonId"):
                row["summonId"] = n
            changed = True
        elif 1 <= row["id"] <= 14 and row.get("skillType") != 3:
            # kicker skills: the APK ActionMaster entries with the kicker-skill effects/collisions are
            # skill_20001..skill_20014 (skill_1..14 are empty placeholders), so id = 20000 + kickerId.
            # Skill id 1 with skillType 3 is the guardian's eye laser (Guardian.skillId), left alone.
            row["id"] = KICKER_SKILL_BASE + row["id"]
            row["skillType"] = 2  # Kicker
            changed = True
        # DiscSkillParameter.GetSkillAction only knows action types 1-8, 21, 22; KickerSkillParameter.GetSkillAction
        # only knows the weapon types 9-20, 23, 24. Anything else returns null and the skill state soft-locks
        # (NullReferenceException in PlayerStateSkill.UpdateActionTargeting every frame).
        if row["skillType"] == 2 and row["id"] - KICKER_SKILL_BASE in kickers:
            wt = kickers[row["id"] - KICKER_SKILL_BASE]["weaponType"]
            want = wt + 9 if wt <= 11 else wt + 11
            if row.get("skillActionType") != want:
                row["skillActionType"] = want
                changed = True
        elif row["skillType"] == 1 and row.get("skillActionType") not in (1, 2, 3, 4, 5, 6, 7, 8, 21, 22):
            row["skillActionType"] = 7 if row.get("skillCategoryType") == CAT_TRAP else 1
            changed = True
        if row["skillType"] == 1 and row.get("skillCategoryType") == CAT_TRAP and row.get("skillActionType") != 7:
            row["skillActionType"] = 7
            changed = True
        if row["skillType"] == 1 and row["id"] in DISC_ACTION_TYPE_OVERRIDES                 and row.get("skillActionType") != DISC_ACTION_TYPE_OVERRIDES[row["id"]]:
            row["skillActionType"] = DISC_ACTION_TYPE_OVERRIDES[row["id"]]
            changed = True
        if row["skillType"] == 1 and row.get("skillActionType") == 3 and row["id"] not in DISC_SKILLS_WITH_FORCED_MOVE:
            print(f"skill {row['id']}: MoveAttack without a forced-move event in the APK timeline -> ShotAttack")
            row["skillActionType"] = 1
            changed = True
    kicker_rows = load("masters_kicker_parameter.json")
    kp_changed = False
    for k in kicker_rows:
        if k.get("skillId") != KICKER_SKILL_BASE + k["kickerId"]:
            k["skillId"] = KICKER_SKILL_BASE + k["kickerId"]
            kp_changed = True
    if kp_changed:
        (CONFIG / "masters_kicker_parameter.json").write_text(json.dumps(kicker_rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("remapped masters_kicker_parameter.json skillId -> 20000 + kickerId")
    # Jay's kicker ability (BatAbilityParameter) reads KickerAbility.value as a *skill id* and builds a disc-like
    # skill from it; the APK ActionMaster's spare entry skill_40001 is that bat-bomb trap. Without the Skill row
    # PlayerParameter..ctor throws and GameScene never finishes loading whenever Jay is in the match.
    bat_kicker = next((k["kickerId"] for k in kickers.values() if k["weaponType"] == WT_BAT), None)
    if bat_kicker is not None:
        if not any(r["id"] == BAT_BOMB_SKILL_ID for r in skills):
            skills.append({"id": BAT_BOMB_SKILL_ID, "description": "Bat bomb (kicker ability)", "skillType": 1,
                           "skillActionType": 7, "skillCategoryType": CAT_TRAP, "targetAreaType": 8, "coolTime": 0,
                           "range": 5.0, "speed": 0.0, "summonId": 0, "attributeType": 0, "seId": 0, "coefficient": 1.0})
            changed = True
        abilities = load("masters_kicker_ability.json")
        ab_changed = False
        for a in abilities:
            if a["kickerId"] == bat_kicker and a.get("value") != BAT_BOMB_SKILL_ID:
                a["value"] = BAT_BOMB_SKILL_ID
                ab_changed = True
        if ab_changed:
            (CONFIG / "masters_kicker_ability.json").write_text(json.dumps(abilities, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"remapped masters_kicker_ability.json: kicker {bat_kicker} value -> {BAT_BOMB_SKILL_ID} (bat bomb skill id)")
    for row in discs:
        if row["skillId"] > DISC_ID_BASE:
            row["skillId"] = DISC_SKILL_BASE + (row["skillId"] - DISC_ID_BASE)
            changed = True
    if changed:
        for name, rows in (("masters_skill.json", skills), ("masters_disc.json", discs)):
            shutil.copy(CONFIG / name, CONFIG / (name + ".bak"))
            (CONFIG / name).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"remapped {name} (backup in {name}.bak)")
    else:
        print("skill/disc ids already remapped")
    return skills, discs


def weapon_tables(kickers: list) -> dict[str, list]:
    attack, hit, collision, bullet = [], [], [], []
    for k in kickers:
        kid, wt = k["kickerId"], k["weaponType"]
        ranged = wt in RANGED
        # attackCount is 0-based: WeaponAttackActionBase.get_ComboCount = _totalComboCount % MaxAttackComboCount
        for count in (0, 1, 2):
            rid = kid * 10 + count + 1
            attack.append({"id": rid, "kickerId": kid, "attackCount": count,
                           "coefficient": [1.0, 1.0, 1.2][count], "seId": 0})
            if wt in SLASH:
                fx = [HIT_SLASH_S, HIT_SLASH_M, HIT_SLASH_L][count]
            elif ranged:
                fx = [HIT_GUN_S, HIT_GUN_S, HIT_GUN_M][count]
            else:
                fx = [HIT_BLOW_S, HIT_BLOW_M, HIT_BLOW_L][count]
            hit.append({"id": rid, "kickerId": kid, "attackCount": count, "commonHitEffectType": fx,
                        "hitSeId": 0, "effectPath": "", "parentBone": BONE_COMMON,
                        "offsetX": 0.0, "offsetY": 0.0, "offsetZ": 0.0, "transformType": 0,
                        "shakeVolume": 0.15, "knockBackFlag": count == 2, "fixedDamage": 0})
            # Basic attacks must be CollisionHitType.One: the collider is then destroyed by the first hit
            # (CollisionDestroyType.Hit). With All it lives out its lifetime even after hitting, and
            # WeaponAttackActionBase.CallbackAttackCollisionDestroy(LifeTime) flags the swing as a miss, drops the
            # target and ResetComboCount() fires - every swing was hit 1 (2026-09-20 KFDIAG 8210 after each swing).
            collision.append({"id": rid, "kickerId": kid, "attackCount": count,
                              "collisionType": COL_SPHERE, "collisionHitType": COLHIT_ONE,
                              "hitLayer": HIT_LAYER_CHARACTERS,
                              "radius": 0.8 if ranged else [2.5, 2.5, 3.0][count], "length": 0.0,
                              "originCenterFlag": False, "scaleX": 1.0, "scaleY": 1.0, "scaleZ": 1.0,
                              "moveRadius": 0.0})
            if ranged:
                bullet.append({"id": rid, "kickerId": kid, "attackCount": count,
                               "distance": float(k.get("attackTargetSearchDistance", 15.0)) + 5.0,
                               "speed": 40.0, "resourcePath": "", "loopSeId": 0, "homingAngle": 15.0,
                               "endType": 0, "actionType": 0, "removeOnOwnerDeadFlag": True})
    return {"masters_weapon_attack.json": attack, "masters_weapon_attack_hit.json": hit,
            "masters_weapon_attack_collision.json": collision, "masters_weapon_attack_bullet.json": bullet,
            "masters_weapon_attack_condition.json": []}


# Kicker skills whose effect lives in the SkillCondition / SkillTrap tables rather than the ActionMaster.
# Owlbert (kicker 5, skill 20005 "Dron Centinela", actionType 13): NPCDrone.InitializeAsync reads
# owner.Param.KickerSkillParameter.Conditions[0] (ArgumentOutOfRange with no row, logcat 14Mon09 02:53) - the
# silence the dropped drone applies - and the drone is left behind as a Silent trap.
COND_STEALTH = 24
COND_SHIELD_FORWARD = 26  # ShieldForwardConditionAction: frontal barrier, effectValue = its HP pool (IConditionSacrifice)
KICKER_SKILL_EXTRAS = {
    20005: {"conditions": [(COND_SILENT, 8.0, 0.0, 1.0, 5), (COND_SILENT, 8.0, 0.0, 1.0, 4)],
            "trap": {"trapType": 2, "duration": 8.0, "radius": 8.0, "effectValue": 0.0}},
    # Buzzy Big: ShieldSkillAction.UpdateExecute only does player.AcceptCondition(trigger 3 rows) - without a row the
    # kicker skill fires (cooldown) and spawns nothing. The forward barrier lasts `duration` s or until it has absorbed
    # `effectValue` damage (ShieldAll for the special uses 9999999 = unbreakable).
    20012: {"conditions": [(COND_SHIELD_FORWARD, 6.0, 0.0, 4000.0, TRIGGER_EXECUTE)]},
    # Jay: BatSkillAction.OnBeginAction is only player.AcceptCondition(trigger 3 rows). Stealth (24,
    # StealthConditionAction) fades the model (BatAttackAction.PlayMaskFade), plays the condition effect and makes him
    # un-lock-on-able (ConditionActionController.EnableLockedOn) until the duration ends or he attacks / takes damage.
    20009: {"conditions": [(COND_STEALTH, 8.0, 0.0, 1.0, TRIGGER_EXECUTE)]},
}



# Disc TRAP skills (skillActionType 7) by disc card text. conditions = (type, duration, interval, effectValue, trigger 5)
# Knock-up = a masters_skill_blow_off row (SkillBlowOffMaster.GetDataFromSkillId, read by DiscSkillParameter..ctor and
# attached to the skill's damage); directionType 1 Up, 2 Down, 3 Press, 4 AttackDirection.
_KNOCK_UP = {"distance": 6.0, "speed": 20.0, "rigorTime": 0.5, "directionType": 1}
_B = {"trapType": 7, "duration": 20.0, "effectValue": 0.0, "interval": 0.0, "blow_off": _KNOCK_UP}  # bomb, knock away
_T = lambda interval, dur=15.0: {"trapType": 3, "duration": dur, "effectValue": 0.0, "interval": interval}  # turret
DISC_TRAPS = {
    10031: {"trapType": 8, "duration": 8.0, "effectValue": 0.0, "interval": 0.5,               # Liberwolf: massive damage area 8 s
            "conditions": [(COND_DOT, 8.0, 0.5, 0.9, TRIGGER_ENTER_ENEMY_TRAP)]},
    10036: _B, 10037: _B, 10038: _B, 10039: _B, 10040: _B,                                       # Hyper/Booby Bomb, R/G/B Mine
    10041: {**_B, "conditions": [(COND_PARALYSIS, 3.0, 0.0, 1.0, TRIGGER_ENTER_ENEMY_TRAP)]},   # Hedgefish: bomb + paralyse
    10042: _T(0.4), 10044: _T(0.4),                                                              # Killer Billet, Raging Bulldog: ultra fast
    10043: _T(1.0), 10046: _T(1.0),                                                              # Septicopter, Robo Turret: medium
    10049: {**_B, "conditions": [(COND_SILENT, 8.0, 0.0, 1.0, TRIGGER_ENTER_ENEMY_TRAP)]},      # Aerojammer: bomb + skill seal 8 s
    10050: {"trapType": 1, "duration": 10.0, "effectValue": 0.5, "interval": 0.0},              # Snazzy Snail: slow area 10 s
    10082: {**_B, "conditions": [(COND_POISON, 10.0, 1.0, 0.06, TRIGGER_ENTER_ENEMY_TRAP)]},    # Jack o' Lantern: bomb + poison
    10086: {"trapType": 8, "duration": 8.0, "effectValue": 0.0, "interval": 1.0,               # Pranky Pumpkin: damage area + ally regen
            "conditions": [(COND_DOT, 8.0, 1.0, 0.4, TRIGGER_ENTER_ENEMY_TRAP), (COND_REGENERATION, 8.0, 1.0, 0.08, TRIGGER_ENTER_ALLY_TRAP)]},
    10097: {**_B, "conditions": [(COND_STUN, 2.0, 0.0, 1.0, TRIGGER_ENTER_ENEMY_TRAP)]},        # Starnova: bomb + stun
    10105: {**_T(1.0, 8.0), "conditions": [(COND_ATTACK_RATE, 5.0, 0.0, 0.8, TRIGGER_ENTER_ENEMY_TRAP)]},  # Dynaduck: turret 8 s, attack down
    10114: {**_B, "duration": 30.0},                                                             # Glass Bomb: stealth bomb 30 s
    10128: {**_T(0.6), "conditions": [(COND_SILENT, 1.0, 0.0, 1.0, TRIGGER_ENTER_ENEMY_TRAP)]},  # Hellfire Crow: fast turret, seals 1 s
    10134: {**_T(2.0), "blow_off": _KNOCK_UP},                                                  # Princess Izana: AoE turret, knocks away
}

# Disc MOVE skills. AutoMoveSkillAction (skillActionType 22) does nothing by itself: OnBeginForceMove only calls
# player.AcceptCondition(GetSkillConditionInitInfo(deckIndex, trigger 3)) and OnUpdateAction ends the skill the moment
# ConditionActionController.HasConditionActionSkill is false - so without a SkillCondition row of type 30 (AutoMove)
# the kicker just plays the pose and stops. AutoMoveConditionActionInfo..ctor: OverrideSpeed = Param.GetSpeed(1) *
# effectValue, acceleration fixed 7.5, ends after `duration` or when the player is interrupted (damage / stun). The
# backwards shots of Pyronkey / Spunkle / Tigre are the four rear bullets in their APK timeline (aed_*, bullets fired
# while the dash runs), so nothing extra is served for them. VerticalLoopSkillAction (21, Cycrane) needs no move row
# (the loop is hard-coded: 420 deg/s, radius 2.5) - only its on-hit condition.
# On-hit status effects: PlayerCharacter.ApplyCondition(DamageInfo) applies the attacker skill's SkillCondition rows
# with trigger 1 (ReceiveDamage) to whoever the skill's collider/bullet hits.
COND_AUTO_MOVE = 30
TRIGGER_RECEIVE_DAMAGE = 1
DISC_MOVES = {
    10027: {},                                                                                   # Pyronkey: ShotAttack back-shot (see DISC_ACTION_TYPE_OVERRIDES)
    10063: {"duration": 5.0, "speed": 2.0},                                                     # Leeta: speed up, auto forward 5 s
    10079: {},                                                                                   # Spunkle: ShotAttack back-shot
    10083: {"duration": 5.0, "speed": 3.0},                                                     # Stray Phantom: hyper speed 5 s
    10091: {"duration": 4.0, "speed": 2.0},                                                     # Great Glidears: speed up 4 s
    10112: {"conditions": [(COND_PARALYSIS, 3.0, 0.0, 1.0, TRIGGER_RECEIVE_DAMAGE)]},           # Tigre: ShotAttack back-shot + paralysis
    10122: {"duration": 4.0, "speed": 2.0},                                                     # Gusty Glidears: speed up 4 s
    10026: {"conditions": [(COND_PARALYSIS, 2.0, 0.0, 1.0, TRIGGER_RECEIVE_DAMAGE)]},           # Cycrane: loop, small dmg + paralyse
}

def skill_tables(skills: list) -> dict[str, list]:
    cond, heal, blow, pull, trap = [], [], [], [], []
    nid = 1
    for s in skills:
        sid, cat = s["id"], s.get("skillCategoryType", CAT_ATTACK)
        if sid in KICKER_SKILL_EXTRAS:
            x = KICKER_SKILL_EXTRAS[sid]
            for ctype, duration, interval, value, trigger in x.get("conditions", []):
                cond.append({"id": nid, "skillId": sid, "conditionType": ctype, "duration": duration,
                             "interval": interval, "effectValue": value, "triggerType": trigger})
                nid += 1
            if "trap" in x:
                t = x["trap"]
                trap.append({"id": nid, "skillId": sid, "trapType": t["trapType"], "duration": t["duration"],
                             "radius": t["radius"], "effectValue": t["effectValue"], "interval": 0.0, "executeSeId": 0,
                             "effectPath": "", "screenEffectPath": ""})
                nid += 1
            continue
        if cat == CAT_HEAL:
            heal.append({"id": nid, "skillId": sid, "skillHealType": 1, "coefficient": float(s.get("coefficient", 1.0))})
        elif cat == CAT_BUFF:
            cond.append({"id": nid, "skillId": sid, "conditionType": COND_ATTACK_RATE, "duration": 10.0,
                         "interval": 0.0, "effectValue": 1.2, "triggerType": TRIGGER_EXECUTE})
        elif cat == CAT_TRAP or s.get("skillActionType") == 7:  # Trap actions need a TrapInfo or GetSkillAction throws
            # Trap.Initialize picks the action class from trapType: 7 Bomb (BombTrapAction, a summon body that explodes on
            # the first enemy in range; explosion collider/hit/bullet come from the APK ActionMaster), 3 Turret
            # (TurretTrapAction, a summon that shoots the skill's bullet every `interval` s at enemies in range),
            # 8 Condition (ConditionTrapAction, an area applying this skill's SkillCondition rows with trigger 5/4 to
            # enemies inside, every `interval` s), 1 Slow. Bodies are disc summons (Summon row modelId = id). Radius comes
            # from the APK collision, the served radius is ignored. Table below = the disc card texts.
            t = DISC_TRAPS.get(sid, {"trapType": 1, "duration": 8.0, "effectValue": 0.5, "interval": 0.0})
            trap.append({"id": nid, "skillId": sid, "trapType": 10 if sid == BAT_BOMB_SKILL_ID else t["trapType"],
                         "duration": t["duration"], "radius": float(s.get("range", 5.0)), "effectValue": t["effectValue"],
                         "interval": t["interval"], "executeSeId": 0, "effectPath": "", "screenEffectPath": ""})
            for ctype, duration, interval, value, trigger in t.get("conditions", []):
                cond.append({"id": nid, "skillId": sid, "conditionType": ctype, "duration": duration,
                             "interval": interval, "effectValue": value, "triggerType": trigger})
                nid += 1
            if "blow_off" in t:
                bo = t["blow_off"]
                blow.append({"id": nid, "skillId": sid, "distance": bo["distance"], "speed": bo["speed"],
                             "rigorTime": bo["rigorTime"], "directionType": bo["directionType"]})
                nid += 1
        elif sid in DISC_MOVES:
            m = DISC_MOVES[sid]
            if "speed" in m:
                cond.append({"id": nid, "skillId": sid, "conditionType": COND_AUTO_MOVE, "duration": m["duration"],
                             "interval": 0.0, "effectValue": m["speed"], "triggerType": TRIGGER_EXECUTE})
                nid += 1
            for ctype, duration, interval, value, trigger in m.get("conditions", []):
                cond.append({"id": nid, "skillId": sid, "conditionType": ctype, "duration": duration,
                             "interval": interval, "effectValue": value, "triggerType": trigger})
                nid += 1
            continue
        elif sid in DISC_SKILLS_WITH_SENSOR_COLLIDER:  # sensor collider on a non-trap skill: TrapInfo is still read
            trap.append({"id": nid, "skillId": sid, "trapType": 9, "duration": 14.0, "radius": 7.0,
                         "effectValue": 0.0, "interval": 0.5, "executeSeId": 0, "effectPath": "", "screenEffectPath": ""})
        nid += 1
    return {"masters_skill_condition.json": cond, "masters_skill_heal.json": heal,
            "masters_skill_blow_off.json": blow, "masters_skill_pull_in.json": pull,
            "masters_skill_trap.json": trap}


def guardian_skill_tables(skills: list) -> dict[str, list]:
    """SkillCollision / SkillHit rows for the guardian turrets (Skill rows with skillType 3 = Guardian.skillId).

    NPCSkillParameter..ctor -> SetCollisionInitInfos / SetAttackHitInfos read these two served masters by skillId
    (TMasterBase.Find); disc and kicker skills get their colliders from the APK ActionMaster instead and never
    look here. Without the collision row NPCGuardianParameter.InitializeBulletInfo dereferences a null
    CollisionInitInfo and GameManager.CreateGuardian kills the battle-loading coroutine (stuck on "Cargando").
    The eye laser is a WeaponAttackBulletInfo whose range comes from Guardian.laserLength; the collision row only
    shapes the bullet's hit sphere."""
    collision, hit = [], []
    nid = 1
    for s in skills:
        if s.get("skillType") != 3:
            continue
        collision.append({"id": nid, "skillId": s["id"], "collisionType": COL_SPHERE, "collisionHitType": COLHIT_ALL,
                          "hitLayer": HIT_LAYER_CHARACTERS, "radius": 1.5, "length": 0.0, "originCenterFlag": True,
                          "scaleX": 1.0, "scaleY": 1.0, "scaleZ": 1.0})
        hit.append({"id": nid, "skillId": s["id"], "commonHitEffectType": HIT_GUN_M, "hitSeId": 0, "effectPath": "",
                    "parentBone": BONE_COMMON, "offsetX": 0.0, "offsetY": 0.0, "offsetZ": 0.0, "transformType": 0,
                    "shakeVolume": 0.2, "knockBackFlag": False, "fixedDamage": 0})
        nid += 1
    return {"masters_skill_collision.json": collision, "masters_skill_hit.json": hit}


def summon_table(skills: list) -> list:
    # Which model variants exist per summon id (summon/sm_{id:D4}_{variant}.unity3d, 0 low / 1 high / 2 middle).
    variants: dict[int, set[int]] = {}
    for r in json.loads((CONFIG / "resources" / "catalog.json").read_text(encoding="utf-8"))["resources"]:
        m = re.search(r"summon/sm_(\d{4})_(\d)\.unity3d$", r.get("logicalName", ""))
        if m:
            variants.setdefault(int(m.group(1)), set()).add(int(m.group(2)))
    # SummonCharacter.Finish: a body whose SummonParameter.SummonCharacterType is AttackTrap (3) goes to
    # SummonStateType.NativeAction and stays as the trap (BombTrapAction / TurretTrapAction are SummonTrapActionBase,
    # the trap IS the body); any other type goes to Finish and the body despawns when the placement ends - the
    # "trap disappears after the placement animation" phone report of 2026-09-20.
    trap_summon_ids = {s.get("summonId") for s in skills
                       if s.get("skillActionType") == 7 and DISC_TRAPS.get(s["id"], {}).get("trapType") in (3, 7)}
    rows = []
    for s in skills:
        n = s.get("summonId") or 0
        if n:
            # Two different lookups must agree (verified on the emulator 2026-09-20, logcat NRE in
            # SummonCharacter.InitializeAsync when they did not):
            #   LoadManager.LoadDeckSummonModel preloads  summon/sm_{Skill.summonId:D4}_{Summon.LowModelId}
            #   PlayerStateSkill.CreateSummon instantiates summon/sm_{Summon.modelId:D4}_{Summon.LowModelId}
            # so Summon.modelId is the id of the summon whose MODEL to use (= its own id here), and
            # LowModelId = 2 if middleModelFlag else 0 must name a bundle that exists in the catalog.
            rows.append({"id": n, "modelId": n, "summonCharacterType": 3 if n in trap_summon_ids else 0,
                         "positionX": 0.0, "positionY": 0.0, "positionZ": 1.5, "seId": 0,
                         "gachaPositionX": 0.0, "gachaPositionY": 0.0, "gachaPositionZ": 0.0,
                         "gachaRotationX": 0.0, "gachaRotationY": 0.0, "gachaRotationZ": 0.0,
                         "discDetailPositionX": 0.0, "discDetailPositionY": 0.0, "discDetailPositionZ": 0.0,
                         "discDetailRotationX": 0.0, "discDetailRotationY": 0.0, "discDetailRotationZ": 0.0,
                         "middleModelFlag": 0 not in variants.get(n, {0})})
    return rows


# Special skills. Each XxxSpecialSkillAction reads a different sub-table (see docs/COMBAT_MASTERS_FILL_IN.md §4),
# verified against the action classes in libil2cpp:
#   * Sword/Nunchaku/JapaneseSword (self), TwoGuns/Drone/Bowgun/Shield (allies), Gun/Bat (enemies) call AcceptCondition
#     with the kicker's SpecialSkillCondition rows -> triggerType 3 Execute.
#   * Hammer (Coco) drops an Inhale TRAP (SpecialSkillTrap, TrapType 5; the pull itself is InhaleConditionAction driven
#     by the APK KickerSpecialSkillMaster.Hammer + SpecialSkill.range) that applies the kicker's SpecialSkillCondition
#     rows to whoever enters (ConditionTrapAction: triggerType 5 EnterEnemyTeamTrap / 6 EnterMyTeamTrap / 7 All), then
#     the impact is a DamageCollisionData from SpecialSkillCollision+Hit (+ SpecialSkillBlowOff). Without the trap row
#     Trap.Initialize NREs (TrapInitializeInfo.TrapInfo null) and nothing happens.
#   * Laser (Sid) is an EmptyDamageCollisionData cylinder from SpecialSkillCollision whose stay callback applies the
#     SpecialSkillCondition rows with triggerType 4 EnterTrap (ConditionInitializeInfo.Set(..., trigger 4)) - damage
#     must come from a Dot condition; there is no direct hit.
#   * PunchGlove (Diatrius) drops a SpecialSkillTrap at the end of the cut (type still unconfirmed by the user).
#   * ThrowingStar/RocketLauncher fire a SpecialSkillBullet (collision/hit for the impact).
# Condition tuples: (conditionType, duration, interval, effectValue[, triggerType]).
# Keyed by weaponType; values from the kickers' special-skill descriptions (masters_kicker_detail.json).
SPECIAL_SKILL_DATA = {
    # Tsubame: speed +20 % and a tornado around her (BlowoffColliderConditionAction builds a DamageCollisionData
    # from SpecialSkillCollision + GetSpecialSkillDamageInitInfo; the knock-up itself is the SpecialSkillBlowOff row)
    WT_SWORD:          {"duration": 10.0, "conditions": [(COND_SPEED_RATE, 10.0, 0.0, 1.2), (13, 10.0, 0.0, 1.0)],
                        "collision": {"collisionType": COL_SPHERE, "radius": 4.0, "length": 0.0},
                        "blow_off": {"distance": 6.0, "speed": 20.0, "rigorTime": 0.5, "directionType": 1}},         # 1 = Up
    WT_TWO_GUNS:       {"duration": 10.0, "conditions": [(COND_REGENERATION, 10.0, 1.0, 0.05)]},                      # allies regen 5 %/s
    # Coco: tornado trap that sucks enemies in (Inhale condition on enter; speed/min range from the APK HammerMaster,
    # radius = SpecialSkill.range) then the hammer impact slams them down (collision + blow-off Down)
    WT_HAMMER:         {"duration": 5.0, "range": 100.0,
                        "trap": {"trapType": 5, "duration": 3.5, "radius": 100.0, "effectValue": 0.0},   # in-game the pull reached ~1/10 of this
                        "conditions": [(COND_INHALE, 3.5, 0.0, 1.0, TRIGGER_ENTER_ENEMY_TRAP)],
                        "collision": {"collisionType": COL_SPHERE, "radius": 8.0, "length": 0.0},
                        "blow_off": {"distance": 8.0, "speed": 30.0, "rigorTime": 1.0, "directionType": 2}},         # 2 = Down
    # Kite: one giant shuriken that one-shots everything in its path (SpecialSkillHit.fixedDamage - a coefficient
    # cannot do it, fixedDamage replaces the damage) and flies through walls (a bullet only sphere-casts against the
    # field when its hitLayer contains the Field layer, so drop bit 8); with fixedDamage >= 1 a guardian instead loses
    # the APK KickerSpecialSkillMaster.ThrowingStar._guardianDropCrystalCount crystals
    WT_THROWING_STAR:  {"duration": 5.0, "fixedDamage": ONE_SHOT_FIXED_DAMAGE,
                        # distance well past any map edge (the star must fly off the arena, not stop mid-air at 60 u) and
                        # BulletEndType.FadeOut so the effect does not linger where it ends
                        "bullet": {"distance": 300.0, "speed": 25.0, "homingAngle": 0.0, "actionType": 0, "endType": 1},
                        "collision": {"collisionType": COL_SPHERE, "radius": 6.0, "length": 0.0, "hitLayer": HIT_LAYER_CHARACTERS & ~(1 << 8)}},
    # Owlbert: DroneSpecialSkillAction.ExecuteSkillEffect applies the trigger-3 condition to every ally; the one that
    # spawns the escort drone and lays smog clouds along the ally's path is Smog (18, SmogConditionAction: cloud
    # radius = this special's TrapInfo.Radius, next cloud every radius+1 units, SendAddTrap of trapType 6). Players
    # inside a cloud then get SmogProtection (20, trigger 6 EnterMyTeamTrap) / SmogDisturb (19, trigger 5). Serving
    # 20 on trigger 3 (2026-09-14..19) applied a no-op buff and no drone/smog ever appeared.
    WT_DRONE:          {"duration": 8.0, "range": 100.0,
                        "trap": {"trapType": 6, "duration": 8.0, "radius": 5.0, "effectValue": 0.0},
                        "conditions": [(18, 8.0, 0.0, 1.0), (20, 8.0, 0.0, 1.0, TRIGGER_ENTER_ALLY_TRAP),
                                       (19, 8.0, 0.0, 1.0, TRIGGER_ENTER_ENEMY_TRAP)]},                              # 18 Smog trail on allies, 20/19 inside the clouds
    # Pitophy: RocketLauncherSpecialSkillAction.PlayMuzzleEffect instantiates BulletInfo.Path (= this resourcePath) as the
    # missile SPFX and kicks its triggers; with "" every shot NRE'd in EffectManager and no missile was ever spawned.
    # RocketLauncherSpecialSkillAction.SetTarget only locks enemies within SpecialSkill.range AND in the camera frustum
    # (up to 12); shots with no target get -1 and fly straight, so range must cover the missile's 60 u flight.
    # Each missile (BulletRocketLauncherSkillAction.OnInitialize) applies this special's trigger-3 condition to its target
    # and then steers by RocketLauncherTargetConditionAction (29) found on that target; without the row the missile
    # never homes. duration = how long the lock mark lives (>= flight time).
    WT_ROCKET:         {"duration": 6.0, "range": 60.0, "conditions": [(29, 6.0, 0.0, 1.0)],
                        "bullet": {"distance": 60.0, "speed": 45.0, "homingAngle": 90.0, "actionType": 1,
                                                   "resourcePath": "effect/ss/ef_ss_006_001/ef_ss_006_001"},
                        "collision": {"collisionType": COL_SPHERE, "radius": 1.5, "length": 0.0, "hitType": 0}},
    WT_GUN:            {"duration": 5.0, "conditions": [(16, 5.0, 0.0, 1.0)]},                                        # enemies Prison
    # Diatrius: Condition trap (8) - enemies inside are pulled to the ground and kept there while airborne
    # (Gravity 21, GravityConditionAction : IConditionMovePosition); the trap removes it again on exit
    WT_PUNCH_GLOVE:    {"duration": 6.0, "trap": {"trapType": 8, "duration": 6.0, "radius": 1000.0, "effectValue": 0.0},  # in-game the trap reached ~1/100 of this
                        "conditions": [(COND_GRAVITY, 6.0, 0.0, 1.0, TRIGGER_ENTER_ENEMY_TRAP)]},
    WT_BOWGUN:         {"duration": 12.0, "conditions": [(COND_SPEED_RATE, 12.0, 0.0, 1.2), (28, 12.0, 0.0, 1.3)]},   # allies: move speed +20 %, attack speed +30 % (28 = AttackSpeedRate)
    WT_SHIELD:         {"duration": 5.0, "conditions": [(27, 5.0, 0.0, 9999999.0)]},                                  # allies: unbreakable shield 5 s
    WT_BAT:            {"duration": 8.0, "conditions": [(22, 8.0, 0.0, 1.0)]},                                        # enemies Confusion
    WT_NUNCHAKU:       {"duration": 15.0, "conditions": [(25, 15.0, 0.0, 1.0)]},                                      # self Panda
    WT_JAPANESE_SWORD: {"duration": 15.0, "conditions": [(34, 15.0, 0.0, 1.0)]},                                      # self OneShotKiller
    # Sid: giant beam through walls; everyone inside is paralysed and takes tick damage (Dot) while they stay in it
    WT_LASER:          {"duration": 6.0, "collision": {"collisionType": COL_CYLINDER, "radius": 15.0, "length": 60.0},
                        # TEST (2026-09-14): paralysis applied but the Dot ticks did no damage even after the
                        # CommonConditionHit fix. DotConditionAction.ExecuteIntervalAction skips the damage when
                        # target.IsInvincible(TrapSkill) is true, and PlayerCharacter.IsInvincible is state-based -
                        # suspect the paralysed state counts. Dot only for this test; Poison as a second candidate.
                        "conditions": [(COND_DOT, 6.0, 0.5, 0.15, TRIGGER_ENTER_TRAP),
                                       (COND_POISON, 6.0, 1.0, 0.1, TRIGGER_ENTER_TRAP)]},
}


def special_skill_tables(kickers: list) -> dict[str, list]:
    ss, hit, col, cond, bullet, trap, blow = [], [], [], [], [], [], []
    nid = 1
    for k in kickers:
        kid = k["kickerId"]
        sid = kid
        data = SPECIAL_SKILL_DATA.get(k.get("weaponType"), {})
        ss.append({"id": sid, "kickerId": kid, "duration": float(data.get("duration", 5.0)),
                   "coefficient": float(data.get("coefficient", 3.0)), "range": float(data.get("range", 10.0)), "finishTime": 1.0})
        hit.append({"id": sid, "specialSkillId": sid, "commonHitEffectType": HIT_COMMON_L, "hitSeId": 0,
                    "effectPath": "", "parentBone": BONE_COMMON, "offsetX": 0.0, "offsetY": 0.0, "offsetZ": 0.0,
                    "transformType": 0, "shakeVolume": 0.3, "knockBackFlag": True,
                    "fixedDamage": int(data.get("fixedDamage", 0))})
        c = data.get("collision", {"collisionType": COL_SPHERE, "radius": 10.0, "length": 0.0})
        # collisionHitType All (1) = penetrating bullet (BulletActionBase.HitCallback keeps flying after a field/character
        # hit); One (0) ends the bullet on its first hit. Missiles must not pass through walls.
        col.append({"id": sid, "specialSkillId": sid, "collisionType": c["collisionType"], "collisionHitType": c.get("hitType", COLHIT_ALL),
                    "hitLayer": c.get("hitLayer", HIT_LAYER_CHARACTERS), "radius": c["radius"], "length": c["length"], "originCenterFlag": True,
                    "scaleX": 1.0, "scaleY": 1.0, "scaleZ": 1.0})
        for ctype, duration, interval, value, *trigger in data.get("conditions", []):
            cond.append({"id": nid, "specialSkillId": sid, "conditionType": ctype, "duration": duration,
                         "interval": interval, "effectValue": value, "triggerType": trigger[0] if trigger else TRIGGER_EXECUTE})
            nid += 1
        if "bullet" in data:
            b = data["bullet"]
            bullet.append({"id": sid, "specialSkillId": sid, "distance": b["distance"], "speed": b["speed"], "resourcePath": b.get("resourcePath", ""),
                           "loopSeId": 0, "homingAngle": b["homingAngle"], "endType": b.get("endType", 0), "actionType": b["actionType"],
                           "removeOnOwnerDeadFlag": True})
        if "blow_off" in data:
            bo = data["blow_off"]
            blow.append({"id": sid, "specialSkillId": sid, "distance": bo["distance"], "speed": bo["speed"],
                         "rigorTime": bo["rigorTime"], "directionType": bo["directionType"]})
        if "trap" in data:
            t = data["trap"]
            trap.append({"id": sid, "specialSkillId": sid, "trapType": t["trapType"], "duration": t["duration"],
                         "radius": t["radius"], "effectValue": t["effectValue"], "interval": 0.0, "executeSeId": 0,
                         "effectPath": "", "screenEffectPath": ""})
    return {"masters_special_skill.json": ss, "masters_special_skill_hit.json": hit,
            "masters_special_skill_collision.json": col, "masters_special_skill_condition.json": cond,
            "masters_special_skill_bullet.json": bullet, "masters_special_skill_blow_off.json": blow,
            "masters_special_skill_trap.json": trap}


def common_condition_hit_table() -> list:
    rows = []
    # Every condition that deals damage needs a row: CharacterBase.UnzipDamageInfo (AttackType Condition) copies
    # ConditionActionController.GetConditionHitInfo(conditionType) and NREs when the type is missing - Sid's Dot
    # ticks died that way (158 NREs in logcat 14Mon09 01:28).
    for i, ct in enumerate((COND_POISON, COND_PARALYSIS, COND_BURN, COND_STUN, COND_SILENT, COND_DOT, 10), start=1):
        rows.append({"id": i, "commonHitEffectType": HIT_COMMON_S, "hitSeId": 0, "effectPath": "",
                     "parentBone": BONE_COMMON, "offsetX": 0.0, "offsetY": 0.0, "offsetZ": 0.0,
                     "transformType": 0, "shakeVolume": 0.0, "knockBackFlag": False, "fixedDamage": 0,
                     "conditionType": ct})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="overwrite existing generated tables")
    ap.add_argument("--only", help="comma-separated table-name substrings to (re)write, e.g. special_skill (implies --force for them)")
    args = ap.parse_args()

    skills, _discs = remap_skill_ids(args.force)
    kickers = load("masters_kicker_parameter.json")

    tables: dict[str, list] = {}
    tables.update(weapon_tables(kickers))
    tables.update(skill_tables(skills))
    tables.update(guardian_skill_tables(skills))
    tables["masters_summon.json"] = summon_table(skills)
    tables.update(special_skill_tables(kickers))
    tables["masters_common_condition_hit.json"] = common_condition_hit_table()
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    for name, rows in tables.items():
        if only is not None and not any(o in name for o in only):
            continue
        write(name, rows, args.force or only is not None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
