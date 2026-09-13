#!/usr/bin/env python3
"""
apply_disc_cards.py - write docs/disc_cards.json (the identified disc list) into the combat masters.

Updates, per disc:
  config/masters_disc.json     name, rarityType (N0 R1 SR2 UR3), skillId, sortOrder, max stats from the card
                               (min = max x the ratio the existing table uses), rows added for ids that were missing
  config/masters_skill.json    description (card effect), skillActionType/skillCategoryType from the card type,
                               coolTime, attributeType (Fire 1 / Water 2 / Wind 3), summonId; rows added when missing
  config/masters_summon.json   one row per summonId; middleModelFlag = true when only the summon/sm_NNNN_2 bundle
                               exists (SummonMasterData.LowModelId = middleModelFlag ? 2 : 0 picks the bundle suffix)
  config/masters_skill_{heal,condition,trap,blow_off,pull_in}.json  regenerated templates for the new categories
                               (generate_combat_masters.skill_tables)
Columns the dataset does not cover (range, speed, seId, coefficient, targetAreaType, grow groups, ...) are kept.
Min columns come from the Lv.1 stats ('lv1', Appliv) when present, else the table's mean min/max ratio; coefficient from 'coefficient_appliv' when it is a plain number.

    python scripts/apply_disc_cards.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import generate_combat_masters as gen  # noqa: E402

RARITY = {"N": 0, "R": 1, "SR": 2, "UR": 3}
CATEGORY_OF_TYPE = {"ATK": 0, "HEAL": 1, "BUFF": 2, "TRAP": 3, "WARP": 4, "MOVE": 5}
MIN_RATIO = {"hp": 0.393, "attack": 0.393, "coolTime": 1.16}   # mean min/max of the pre-existing rows
NEW_SKILL_DEFAULTS = {"targetAreaType": 0, "range": 8.0, "speed": 20.0, "seId": 1001, "coefficient": 3.0}
NEW_DISC_DEFAULTS = {"rank": 0, "discType": 1, "hpGrowGroupId": 1, "attackGrowGroupId": 1, "minCoefficient": 3.0,
                     "maxCoefficient": 3.0, "coefficientGrowGroupId": 1, "coolTimeGrowGroupId": 1,
                     "releaseDatetime": "2020-01-29 00:00:00"}


def load(name):
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def save(name, rows, dry):
    if dry:
        print(f"would write {name} ({len(rows)} rows)")
        return
    (CONFIG / name).write_text(json.dumps(rows, ensure_ascii=False, indent=1).replace("\n", "\r\n"), encoding="utf-8")
    print(f"wrote {name} ({len(rows)} rows)")


def summon_bundle_suffixes():
    t = json.loads((CONFIG / "resources" / "title-minimum.json").read_text(encoding="utf-8-sig"))
    out = {}
    for e in t["entries"]:
        for n in e["names"]:
            if n.startswith("summon/sm_"):
                out.setdefault(int(n.split("_")[1]), set()).add(n.split("_")[2][0])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    data = json.loads((REPO_ROOT / "docs" / "disc_cards.json").read_text(encoding="utf-8"))
    action_of_type = data["typeToSkillActionType"]
    attribute_of = data["attributeType"]
    discs = {r["id"]: r for r in load("masters_disc.json")}
    skills = {r["id"]: r for r in load("masters_skill.json")}
    suffixes = summon_bundle_suffixes()

    for c in data["cards"]:
        did, sid = c["discId"], c["discId"] - 3000000
        atk, hp, ct = c["atk"], c["hp"], c["coolTime"]
        if c.get("level", 1) > 1 and "perLevel" in c:   # card shown mid-level: project to Lv.10
            k = 10 - c["level"]
            atk += c["perLevel"]["atk"] * k
            hp += c["perLevel"]["hp"] * k
            ct += c["perLevel"]["coolTime"] * k
        disc = discs.get(did)
        if disc is None:
            disc = {"id": did, **NEW_DISC_DEFAULTS}
            discs[did] = disc
        lv1 = c.get("lv1") or {"atk": round(atk * MIN_RATIO["attack"]), "hp": round(hp * MIN_RATIO["hp"]),
                                "coolTime": round(ct * MIN_RATIO["coolTime"])}
        disc.update({"name": c["name"], "rarityType": RARITY[c["rarity"]], "skillId": sid, "sortOrder": did - 3010000,
                     "maxHp": int(hp), "minHp": int(lv1["hp"]),
                     "maxAttack": int(atk), "minAttack": int(lv1["atk"]),
                     "maxCoolTime": float(ct), "minCoolTime": float(lv1["coolTime"])})
        coef = c.get("coefficient_appliv")
        if coef and coef.replace(".", "", 1).isdigit():          # "0.75 ×19" style multi-hit values are left to the tuner
            disc["minCoefficient"] = disc["maxCoefficient"] = float(coef)

        skill = skills.get(sid)
        if skill is None:
            skill = {"id": sid, "skillType": 1, "summonId": sid - 10000, **NEW_SKILL_DEFAULTS}
            skills[sid] = skill
        type_key = c["type"].split("(")[0] if not c["type"].startswith("MOVE") else "MOVE"
        summon_id = skill.get("summonId") or (sid - 10000)
        if not suffixes.get(summon_id):
            summon_id = 0   # no model bundle captured for this pet at all
        skill.update({"description": c["effect"], "skillType": 1,
                      "skillActionType": action_of_type[c["type"]],
                      "skillCategoryType": CATEGORY_OF_TYPE[type_key],
                      "coolTime": int(ct), "attributeType": attribute_of[c["attribute"]],
                      "summonId": summon_id})

    # disc ids that are not in the dataset are not released discs (e.g. 3010054/3010121: pets exist, no card,
    # no thumbnail, not on Appliv) - drop them and their disc-skill rows so they never reach a deck
    card_ids = {c["discId"] for c in data["cards"]}
    for did in [d for d in discs if d not in card_ids]:
        print(f"dropping disc {did} ({discs[did].get('name')}): not in disc_cards.json")
        del discs[did]
        skills.pop(did - 3000000, None)
    disc_rows = [discs[k] for k in sorted(discs)]
    skill_rows = [skills[k] for k in sorted(skills)]
    save("masters_disc.json", disc_rows, args.dry_run)
    save("masters_skill.json", skill_rows, args.dry_run)

    # pets: rebuild from the skills, flagging the ids whose only in-game model is the _2 ("middle") bundle
    summon_rows = gen.summon_table(skill_rows)
    for r in summon_rows:
        s = suffixes.get(r["id"], set())
        r["modelId"] = r["id"]            # informational only; the client derives the bundle from id + middleModelFlag
        r["middleModelFlag"] = ("0" not in s and "2" in s)
    save("masters_summon.json", summon_rows, args.dry_run)
    for name, rows in gen.skill_tables(skill_rows).items():
        save(name, rows, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
