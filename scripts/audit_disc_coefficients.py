#!/usr/bin/env python3
"""Check per-hit coefficients against the integer runtime Disc calculation and Skill multiplier."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path

from apply_disc_cards import REPO_ROOT, gen, per_hit_coefficient


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def runtime_disc_coefficient(minimum: float, maximum: float, rate: float) -> int:
    """Mirror DiscParameterUtil.CalcCoefficient: Mathf.FloorToInt(min + (max-min)*rate/100)."""
    return math.floor(minimum + (maximum - minimum) * rate / 100.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--masters-dir", type=Path, default=REPO_ROOT / "config",
                        help="directory containing effective masters_disc.json, masters_skill.json, etc.")
    args = parser.parse_args()
    masters_dir = args.masters_dir.expanduser().resolve()
    cards = load_json(REPO_ROOT / "docs" / "disc_cards.json")["cards"]
    cards_by_id = {row["discId"]: row for row in cards}
    expected_data = load_json(REPO_ROOT / "docs" / "disc_damage_expectations.json")
    expected_rows = [row for row in expected_data["discs"] if row["skillId"] is not None]
    expected_by_skill = {row["skillId"]: row for row in expected_rows}
    skills = {row["id"]: row for row in load_json(masters_dir / "masters_skill.json")}
    discs = {row["id"]: row for row in load_json(masters_dir / "masters_disc.json")}
    traps = {row["skillId"]: row for row in load_json(masters_dir / "masters_skill_trap.json")}
    conditions = load_json(masters_dir / "masters_skill_condition.json")
    grow_rows = load_json(REPO_ROOT / "config" / "masters_disc_grow.json")
    grow_rates = Counter()
    for row in grow_rows:
        grow_rates[row["groupId"]] += 1
    grow_levels = {
        group_id: [row["rate"] for row in grow_rows if row["groupId"] == group_id]
        for group_id in grow_rates
    }
    cards_by_skill: dict[int, list[int]] = {}
    for card in cards:
        cards_by_skill.setdefault(card["discId"] - 3000000, []).append(card["discId"])
    explicit = 0
    mismatches = []
    without_coefficient = Counter()
    user_overrides = []
    levels_checked = set()

    expected_skill_ids = set(expected_by_skill)
    if len(expected_skill_ids) != len(expected_rows):
        mismatches.append("expectation file contains duplicate Skill ids")
    for skill_id in sorted(expected_skill_ids):
        disc_ids = cards_by_skill.get(skill_id, [])
        if len(disc_ids) != 1:
            mismatches.append(f"expected Skill {skill_id}: maps to {disc_ids!r} Disc cards, expected exactly one")

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
        if skill_coefficient is None or not math.isclose(float(skill_coefficient), expected, rel_tol=0, abs_tol=1e-9):
            mismatches.append(f"{card['name']}: Skill.coefficient={skill_coefficient!r}, expected {expected:g}")
        disc_grow_group = disc.get("coefficientGrowGroupId")
        rates = grow_levels.get(disc_grow_group, [])
        if not rates:
            mismatches.append(f"{card['name']}: no DiscGrow rows for coefficient group {disc_grow_group!r}")
        for rate in rates:
            levels_checked.add((disc_grow_group, rate))
        for endpoint in ("minCoefficient", "maxCoefficient"):
            value = disc.get(endpoint)
            if value is None or not math.isclose(float(value), 1.0, rel_tol=0, abs_tol=1e-9):
                mismatches.append(f"{card['name']}: Disc.{endpoint}={value!r}, expected integer-safe unit factor 1")
        minimum = float(disc.get("minCoefficient", 0))
        maximum = float(disc.get("maxCoefficient", 0))
        for rate in rates:
            runtime_value = runtime_disc_coefficient(minimum, maximum, float(rate))
            product = runtime_value * float(skill_coefficient or 0)
            if runtime_value != 1:
                mismatches.append(f"{card['name']}: runtime Disc coefficient at rate {rate:g} is {runtime_value}, expected 1")
            if not math.isclose(product, expected, rel_tol=0, abs_tol=1e-9):
                mismatches.append(f"{card['name']}: runtime Skill x Disc at rate {rate:g} is {product:g}, expected {expected:g}")

    # Regression probes for fractional and >1 coefficients across every coefficient growth rate in the masters.
    probe_values = (0.05, 0.63, 5.8)
    all_rates = [float(row["rate"]) for row in grow_rows]
    for expected in probe_values:
        for rate in all_rates:
            runtime_value = runtime_disc_coefficient(1.0, 1.0, rate)
            if runtime_value != 1 or not math.isclose(runtime_value * expected, expected, rel_tol=0, abs_tol=1e-12):
                mismatches.append(f"fractional regression probe {expected:g} failed at growth rate {rate:g}")

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
    print(f"masters_dir={masters_dir}")
    print(f"cards={len(cards)} explicit_damage_coefficients={explicit} user_expected_matches={len(expected_by_skill)} "
          f"growth_rates_checked={len(all_rates)} card_growth_levels_checked={len(levels_checked)} "
          f"unmatched_user_rows={len(unmatched)} without_explicit_coefficient={sum(without_coefficient.values())}")
    print("without explicit coefficient by card type=" + json.dumps(dict(sorted(without_coefficient.items()))))
    print("user expectation overrides versus Appliv=" + json.dumps(user_overrides, ensure_ascii=False))
    if unmatched:
        print("unmatched user-row names=" + json.dumps(unmatched, ensure_ascii=False))
    print("runtime multiplier checked as Skill.coefficient x floor(Disc.min + (Disc.max-Disc.min) * rate / 100); ×N is not multiplied per hit")
    if mismatches:
        print("MISMATCHES:")
        print("\n".join(mismatches))
        return 1
    print("User expected values survive the integer Disc calculation at every applicable growth level; action overrides, trap effects, and Princess Izana's interval match the masters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
