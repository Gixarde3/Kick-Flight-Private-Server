#!/usr/bin/env python3
"""Check every explicit per-hit coefficient against the Disc x Skill multiplier endpoints."""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from apply_disc_cards import REPO_ROOT, gen, per_hit_coefficient


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    cards = load_json(REPO_ROOT / "docs" / "disc_cards.json")["cards"]
    cards_by_id = {row["discId"]: row for row in cards}
    expected_data = load_json(REPO_ROOT / "docs" / "disc_damage_expectations.json")
    expected_by_skill = {row["skillId"]: row for row in expected_data["discs"] if row["skillId"] is not None}
    skills = {row["id"]: row for row in load_json(REPO_ROOT / "config" / "masters_skill.json")}
    discs = {row["id"]: row for row in load_json(REPO_ROOT / "config" / "masters_disc.json")}
    traps = {row["skillId"]: row for row in load_json(REPO_ROOT / "config" / "masters_skill_trap.json")}
    conditions = load_json(REPO_ROOT / "config" / "masters_skill_condition.json")
    explicit = 0
    mismatches = []
    without_coefficient = Counter()
    user_overrides = []

    for card in cards:
        source = card.get("coefficient_appliv")
        if source is None:
            without_coefficient[card["type"].split("(")[0]] += 1
            continue
        skill_id = card["discId"] - 3000000
        expected = (expected_by_skill[skill_id]["expectedMultiplierPerHit"] if skill_id in expected_by_skill
                    else per_hit_coefficient(source))
        if expected is None:
            mismatches.append(f"{card['name']}: cannot parse {source!r}")
            continue
        explicit += 1
        skill = skills.get(skill_id)
        if skill is None:
            mismatches.append(f"{card['name']}: missing Skill {skill_id}")
            continue
        disc = discs.get(card["discId"])
        if disc is None:
            mismatches.append(f"{card['name']}: missing Disc {card['discId']}")
            continue
        skill_coefficient = skill.get("coefficient")
        if skill_coefficient is None or not math.isclose(float(skill_coefficient), 1.0, rel_tol=0, abs_tol=1e-9):
            mismatches.append(f"{card['name']}: Skill.coefficient={skill_coefficient!r}, expected neutral 1.0")
        for endpoint in ("minCoefficient", "maxCoefficient"):
            value = disc.get(endpoint)
            product = float(value) * float(skill_coefficient or 0)
            if value is None or not math.isclose(float(value), expected, rel_tol=0, abs_tol=1e-9):
                mismatches.append(f"{card['name']}: Disc.{endpoint}={value!r}, expected {expected:g} per hit")
            if not math.isclose(product, expected, rel_tol=0, abs_tol=1e-9):
                mismatches.append(f"{card['name']}: level endpoint product Skill x Disc.{endpoint}={product:g}, expected {expected:g}")

    for skill_id, action_type in gen.DISC_ACTION_TYPE_OVERRIDES.items():
        if skills.get(skill_id, {}).get("skillActionType") != action_type:
            mismatches.append(f"Skill {skill_id}: skillActionType={skills.get(skill_id, {}).get('skillActionType')}, expected {action_type}")

    for skill_id, row in expected_by_skill.items():
        card = cards_by_id.get(row["discId"])
        if row.get("matchedCardName") and (card is None or card["name"] != row["matchedCardName"]):
            mismatches.append(f"{row['name']}: alias maps to {row['matchedCardName']} at Disc {row['discId']}, but source card is {card and card['name']}")
        appliv = per_hit_coefficient(card.get("coefficient_appliv")) if card else None
        if appliv is not None and not math.isclose(appliv, row["expectedMultiplierPerHit"], rel_tol=0, abs_tol=1e-9):
            user_overrides.append(row["name"])

    for skill_id in (10041, 10049, 10082, 10097, 10105, 10128):
        rows = [row for row in conditions if row["skillId"] == skill_id]
        if not rows or any(row["triggerType"] != 1 for row in rows):
            mismatches.append(f"Skill {skill_id}: bomb/turret hit conditions must use triggerType 1")

    if traps.get(10134, {}).get("interval") != 3.0:
        mismatches.append(f"Princess Izana (10134): trap interval={traps.get(10134, {}).get('interval')}, expected 3.0 s")

    unmatched = [row["name"] for row in expected_data["discs"] if row["skillId"] is None]
    print(f"cards={len(cards)} explicit_damage_coefficients={explicit} user_expected_matches={len(expected_by_skill)} "
          f"unmatched_user_rows={len(unmatched)} without_explicit_coefficient={sum(without_coefficient.values())}")
    print("without explicit coefficient by card type=" + json.dumps(dict(sorted(without_coefficient.items()))))
    print("user expectation overrides versus Appliv=" + json.dumps(user_overrides, ensure_ascii=False))
    if unmatched:
        print("unmatched user-row names=" + json.dumps(unmatched, ensure_ascii=False))
    print("multiplier endpoints checked as Skill.coefficient x Disc.{min,max}Coefficient; ×N is not multiplied per hit")
    if mismatches:
        print("MISMATCHES:")
        print("\n".join(mismatches))
        return 1
    print("User expected values, coefficient products at both Disc level endpoints, action overrides, trap effects, and Princess Izana's interval match the masters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
