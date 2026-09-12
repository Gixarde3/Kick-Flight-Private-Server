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
# hitLayer used by the shipped ActionMaster collisions (players + guardians)
HIT_LAYER_CHARACTERS = 4864

DISC_ID_BASE = 3010000     # disc ids are 3010001..; skill id = 10000 + n; summon/model id = n
DISC_SKILL_BASE = 10000
BAT_BOMB_SKILL_ID = 40001
KICKER_SKILL_BASE = 20000  # Skill.id of kicker skills; SpecialSkill ids are the plain kickerId


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
        elif 1 <= row["id"] <= 14:
            # kicker skills: the APK ActionMaster entries with the kicker-skill effects/collisions are
            # skill_20001..skill_20014 (skill_1..14 are empty placeholders), so id = 20000 + kickerId
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
            collision.append({"id": rid, "kickerId": kid, "attackCount": count,
                              "collisionType": COL_SPHERE, "collisionHitType": COLHIT_ALL,
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


def skill_tables(skills: list) -> dict[str, list]:
    cond, heal, blow, pull, trap = [], [], [], [], []
    nid = 1
    for s in skills:
        sid, cat = s["id"], s.get("skillCategoryType", CAT_ATTACK)
        if cat == CAT_HEAL:
            heal.append({"id": nid, "skillId": sid, "skillHealType": 1, "coefficient": float(s.get("coefficient", 1.0))})
        elif cat == CAT_BUFF:
            cond.append({"id": nid, "skillId": sid, "conditionType": COND_ATTACK_RATE, "duration": 10.0,
                         "interval": 0.0, "effectValue": 1.2, "triggerType": TRIGGER_EXECUTE})
        elif cat == CAT_TRAP or s.get("skillActionType") == 7:  # Trap actions need a TrapInfo or GetSkillAction throws
            trap.append({"id": nid, "skillId": sid, "trapType": 10 if sid == BAT_BOMB_SKILL_ID else 1, "duration": 8.0, "radius": float(s.get("range", 5.0)),
                         "effectValue": 0.5, "interval": 0.0, "executeSeId": 0, "effectPath": "", "screenEffectPath": ""})
        nid += 1
    return {"masters_skill_condition.json": cond, "masters_skill_heal.json": heal,
            "masters_skill_blow_off.json": blow, "masters_skill_pull_in.json": pull,
            "masters_skill_trap.json": trap}


def summon_table(skills: list) -> list:
    rows = []
    for s in skills:
        n = s.get("summonId") or 0
        if n:
            rows.append({"id": n, "modelId": n, "summonCharacterType": 0,
                         "positionX": 0.0, "positionY": 0.0, "positionZ": 1.5, "seId": 0,
                         "gachaPositionX": 0.0, "gachaPositionY": 0.0, "gachaPositionZ": 0.0,
                         "gachaRotationX": 0.0, "gachaRotationY": 0.0, "gachaRotationZ": 0.0,
                         "discDetailPositionX": 0.0, "discDetailPositionY": 0.0, "discDetailPositionZ": 0.0,
                         "discDetailRotationX": 0.0, "discDetailRotationY": 0.0, "discDetailRotationZ": 0.0,
                         "middleModelFlag": False})
    return rows


def special_skill_tables(kickers: list) -> dict[str, list]:
    ss, hit, col, cond = [], [], [], []
    for k in kickers:
        kid = k["kickerId"]
        sid = kid
        ss.append({"id": sid, "kickerId": kid, "duration": 5.0, "coefficient": 3.0, "range": 10.0, "finishTime": 1.0})
        hit.append({"id": sid, "specialSkillId": sid, "commonHitEffectType": HIT_COMMON_L, "hitSeId": 0,
                    "effectPath": "", "parentBone": BONE_COMMON, "offsetX": 0.0, "offsetY": 0.0, "offsetZ": 0.0,
                    "transformType": 0, "shakeVolume": 0.3, "knockBackFlag": True, "fixedDamage": 0})
        col.append({"id": sid, "specialSkillId": sid, "collisionType": COL_SPHERE, "collisionHitType": COLHIT_ALL,
                    "hitLayer": HIT_LAYER_CHARACTERS, "radius": 10.0, "length": 0.0, "originCenterFlag": True,
                    "scaleX": 1.0, "scaleY": 1.0, "scaleZ": 1.0})
    return {"masters_special_skill.json": ss, "masters_special_skill_hit.json": hit,
            "masters_special_skill_collision.json": col, "masters_special_skill_condition.json": cond,
            "masters_special_skill_bullet.json": [], "masters_special_skill_blow_off.json": [],
            "masters_special_skill_trap.json": []}


def common_condition_hit_table() -> list:
    rows = []
    for i, ct in enumerate((COND_POISON, COND_PARALYSIS, COND_BURN, COND_STUN, COND_SILENT), start=1):
        rows.append({"id": i, "commonHitEffectType": HIT_COMMON_S, "hitSeId": 0, "effectPath": "",
                     "parentBone": BONE_COMMON, "offsetX": 0.0, "offsetY": 0.0, "offsetZ": 0.0,
                     "transformType": 0, "shakeVolume": 0.0, "knockBackFlag": False, "fixedDamage": 0,
                     "conditionType": ct})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="overwrite existing generated tables")
    args = ap.parse_args()

    skills, _discs = remap_skill_ids(args.force)
    kickers = load("masters_kicker_parameter.json")

    tables: dict[str, list] = {}
    tables.update(weapon_tables(kickers))
    tables.update(skill_tables(skills))
    tables["masters_summon.json"] = summon_table(skills)
    tables.update(special_skill_tables(kickers))
    tables["masters_common_condition_hit.json"] = common_condition_hit_table()
    for name, rows in tables.items():
        write(name, rows, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
