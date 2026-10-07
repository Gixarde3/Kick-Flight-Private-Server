#!/usr/bin/env python3
"""Decode versioned ApplyHp KFDIAG records without conflating input and HP loss.

Usage:
  python scripts/audit_battle_damage.py .local/run/logcat-balance-apply.txt \
      --deck-ids 3010013,3010014,3010020,3010022

Version 2 records are framed by 9800/9900 and contain six raw values in order:
attacker id, victim object id, attack type, attack index, collision id, and the
damage decoded from DamageInfo before later corrections. This is not necessarily
the amount applied to HP; v2 contains no actual HP delta. Version 1 records
(9500/9700) are retained as legacy data and reported with their original fields.
Verified zero-based deck-slot mapping applies to AttackType 2 (Skill) and 7
(SummonTrapBullet). AttackType 5 (Condition) can carry the originating
DamageInitializeInfo.AttackIndex; this is source attribution, not a direct hit
or coefficient measurement. AttackType 1 is a weapon/bullet index and is never
mapped to the disc deck. Type 7 uses SummonParameter's attack path, so its
damage must not be assumed to use the generic Skill coefficient path.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1_FIELDS = (
    "attacker_id",
    "victim_object_id",
    "attack_type",
    "attack_index",
    "collision_id",
    "hp_after",
    "hp_before",
    "legacy_damage_after_extra_hp",
)
V2_FIELDS = (
    "attacker_id",
    "victim_object_id",
    "attack_type",
    "attack_index",
    "collision_id",
    "damage_decoded_before_corrections",
)
HP_PRE_FIELDS = ("victim_object_id", "hp_before", "damage_after_extra_hp")
HP_POST_FIELDS = ("victim_object_id", "hp_after")


def read_hp_events(path: Path):
    """Yield v4 pre-SetHP/post-SetHP snapshots and framing errors.

    These are independent records so zero-damage/bypass branches cannot shift
    the v2 damage record schema. `hp_before - hp_after` is the realized HP delta
    only when a pre and post snapshot for the same victim can be paired.
    """
    events = []
    current = None
    fields = ()
    ends = {9810: ("pre", HP_PRE_FIELDS, 9910), 9811: ("post", HP_POST_FIELDS, 9911)}
    raw_fields_remaining = 0
    raw_end_marker = None
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        match = re.search(r"\bv=(-?\d+)\b", line)
        if not match:
            continue
        value = int(match.group(1))
        parts = line.split()
        timestamp = parts[1] if len(parts) > 1 else "?"
        # v1/v2 records also encode one integer per line. Ignore those values
        # before looking for v4 markers, since a damage/ID may equal 9810/9811.
        if current is None and raw_fields_remaining:
            raw_fields_remaining -= 1
            continue
        if current is None and raw_end_marker is not None:
            if value == raw_end_marker:
                raw_end_marker = None
                continue
            raw_end_marker = None
        if current is None and value in (9500, 9800):
            raw_fields_remaining = 8 if value == 9500 else 6
            raw_end_marker = 9700 if value == 9500 else 9900
            continue
        if current is None:
            if value in ends:
                phase, fields, end_marker = ends[value]
                current = {"schema": 4, "phase": phase, "timestamp": timestamp,
                           "line": line_no, "_field_index": 0, "_end_marker": end_marker}
            continue
        index = current["_field_index"]
        if index < len(fields):
            if value in ends:
                events.append((current, f"incomplete v4 {current['phase']} record; restarted at line {line_no}"))
                phase, fields, end_marker = ends[value]
                current = {"schema": 4, "phase": phase, "timestamp": timestamp,
                           "line": line_no, "_field_index": 0, "_end_marker": end_marker}
                continue
            current[fields[index]] = value
            current["_field_index"] = index + 1
            continue
        if value == current["_end_marker"]:
            current.pop("_field_index", None)
            current.pop("_end_marker", None)
            events.append((current, None))
            current = None
            fields = ()
        elif value in ends:
            events.append((current, f"missing v4 {current['phase']} end marker before line {line_no}"))
            phase, fields, end_marker = ends[value]
            current = {"schema": 4, "phase": phase, "timestamp": timestamp,
                       "line": line_no, "_field_index": 0, "_end_marker": end_marker}
        else:
            events.append((current, f"expected v4 end marker {current['_end_marker']}, got {value} at line {line_no}"))
            current = None
            fields = ()
    if current is not None:
        index = current.pop("_field_index", 0)
        current.pop("_end_marker", None)
        events.append((current, f"incomplete v4 {current['phase']} record at EOF ({len(fields) - index} fields missing)"))
    return events


def pair_hp_events(path: Path, raw_events):
    """Pair v4 snapshots by victim and order, then attach the nearest raw v2 hit."""
    snapshots = read_hp_events(path)
    pending = collections.defaultdict(list)
    pairs = []
    orphan_posts = []
    malformed = []
    for snap, problem in snapshots:
        if problem:
            malformed.append((snap, problem))
            continue
        victim = snap["victim_object_id"]
        if snap["phase"] == "pre":
            pending[victim].append(snap)
        elif pending[victim]:
            before = pending[victim].pop(0)
            pairs.append({
                "victim_object_id": victim,
                "hp_before": before["hp_before"],
                "damage_after_extra_hp": before["damage_after_extra_hp"],
                "hp_after": snap["hp_after"],
                "actual_hp_delta": before["hp_before"] - snap["hp_after"],
                "pre_line": before["line"], "post_line": snap["line"],
                "timestamp": before["timestamp"],
            })
        else:
            orphan_posts.append(snap)
    orphan_pres = [snap for items in pending.values() for snap in items]
    valid_raw = [(event, problem) for event, problem in raw_events
                 if problem is None and event.get("schema") == 2]
    claimed_raw_lines = set()
    for pair in pairs:
        candidates = [(event, problem) for event, problem in valid_raw
                      if event.get("victim_object_id") == pair["victim_object_id"]
                      and event.get("line", 0) < pair["pre_line"]
                      and event.get("line") not in claimed_raw_lines]
        event = max(candidates, key=lambda item: item[0]["line"])[0] if candidates else None
        if event:
            claimed_raw_lines.add(event["line"])
            pair.update({key: event.get(key) for key in (
                "attacker_id", "attack_type", "attack_index", "collision_id",
                "damage_decoded_before_corrections")})
            pair["raw_line"] = event["line"]
        else:
            pair["raw_line"] = None
    return pairs, orphan_pres, orphan_posts, malformed


def read_events(path: Path):
    """Yield (event, problem) for complete and malformed v1/v2 records.

    Once a begin marker is seen, the parser consumes the declared number of raw
    fields before looking for an end marker. This allows legitimate values such
    as damage=9800/9900 without confusing them for framing markers.
    """
    events = []
    current = None
    fields = ()
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        match = re.search(r"\bv=(-?\d+)\b", line)
        if not match:
            continue
        value = int(match.group(1))
        parts = line.split()
        timestamp = parts[1] if len(parts) > 1 else "?"

        if current is None:
            if value in (9500, 9800):
                version = 1 if value == 9500 else 2
                current = {"schema": version, "timestamp": timestamp, "line": line_no}
                fields = V1_FIELDS if version == 1 else V2_FIELDS
                current["_field_index"] = 0
            continue

        index = current["_field_index"]
        if index < len(fields):
            # A nested begin means the previous record was truncated. Restart at
            # the new marker rather than shifting its values into the old schema.
            if value in (9500, 9800):
                events.append((current, f"incomplete v{current['schema']} record; restarted at line {line_no}"))
                version = 1 if value == 9500 else 2
                current = {"schema": version, "timestamp": timestamp, "line": line_no, "_field_index": 0}
                fields = V1_FIELDS if version == 1 else V2_FIELDS
                continue
            current[fields[index]] = value
            current["_field_index"] = index + 1
            continue

        expected_end = 9700 if current["schema"] == 1 else 9900
        if value == expected_end:
            current.pop("_field_index", None)
            events.append((current, None))
            current = None
            fields = ()
        elif value in (9500, 9800):
            events.append((current, f"missing v{current['schema']} end marker before line {line_no}"))
            version = 1 if value == 9500 else 2
            current = {"schema": version, "timestamp": timestamp, "line": line_no, "_field_index": 0}
            fields = V1_FIELDS if version == 1 else V2_FIELDS
        else:
            events.append((current, f"expected v{current['schema']} end marker {expected_end}, got {value} at line {line_no}"))
            current = None
            fields = ()

    if current is not None:
        index = current.pop("_field_index", 0)
        missing = max(0, len(fields) - index)
        events.append((current, f"incomplete v{current['schema']} record at EOF ({missing} fields missing)"))
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--deck-ids", help="four Disc row IDs in AttackIndex order; no deck is assumed")
    parser.add_argument("--slot-base", type=int, choices=(0, 1), default=0,
                        help="whether AttackIndex starts at zero or one (default: zero; verify from this run)")
    parser.add_argument("--hp-pairs", action="store_true",
                        help="also pair v4 9810/9910 and 9811/9911 snapshots into actual HP deltas")
    args = parser.parse_args()

    expected_rows = json.loads((ROOT / "docs/disc_damage_expectations.json").read_text(encoding="utf-8"))["discs"]
    expected_by_skill = {row["skillId"]: row for row in expected_rows if row.get("skillId") is not None}
    deck_ids = [int(v) for v in args.deck_ids.split(",")] if args.deck_ids else []
    discs = {row["id"]: row for row in json.loads((ROOT / "config/masters_disc.json").read_text(encoding="utf-8"))}
    skills = {row["id"]: row for row in json.loads((ROOT / "config/masters_skill.json").read_text(encoding="utf-8"))}

    print("schema\ttime\tattacker\tvictim\ttype\tindex\tcollision\tdisc\tskill\texpected_product\tdamage_decoded_before_corrections\tlegacy_damage_after_extra_hp\tlegacy_hp_delta\tstatus")
    count = 0
    complete_count = 0
    for event, problem in read_events(args.log):
        count += 1
        if problem:
            print(f"# discarded record at line {event.get('line', '?')}: {problem}")
            continue
        attack_type = event.get("attack_type")
        if attack_type is not None and not -1 <= attack_type < 10:
            print(f"# discarded record at line {event.get('line', '?')}: invalid AttackType {attack_type}; expected enum -1..9")
            continue
        complete_count += 1
        index = event.get("attack_index")
        disc_id = skill_id = expected_coef = None
        status_parts = [problem] if problem else []
        if attack_type in (2, 5, 7) and index is not None and deck_ids:
            slot = index - args.slot_base
            if 0 <= slot < len(deck_ids):
                disc_id = deck_ids[slot]
                disc = discs.get(disc_id, {})
                skill_id = disc.get("skillId")
                expected = expected_by_skill.get(skill_id)
                skill = skills.get(skill_id, {})
                if attack_type == 5:
                    status_parts.append("Condition source slot from AttackIndex; this is not a direct-hit coefficient measurement")
                elif expected:
                    expected_coef = float(expected["expectedMultiplierPerHit"])
                    product = float(skill.get("coefficient", 0)) * float(disc.get("maxCoefficient", 0))
                    if not math.isclose(product, expected_coef, rel_tol=0, abs_tol=1e-8):
                        status_parts.append(f"configured_product={product:g} differs from expected")
                else:
                    status_parts.append("no explicit expected damage coefficient")
            else:
                status_parts.append("AttackIndex outside supplied deck; check --slot-base/deck order")
        elif attack_type == 1:
            status_parts.append("weapon/bullet index; not a disc deck slot")
        if attack_type == 7:
            status_parts.append("summon/trap bullet uses SummonParameter attack path; coefficient application must be checked separately")

        # V2's decoded DamageInfo value precedes later corrections; it is neither
        # the realized HP delta nor a reliable proxy for the player's Attack stat.
        hp_delta = None
        if event.get("schema") == 1:
            before, after = event.get("hp_before"), event.get("hp_after")
            hp_delta = before - after if before is not None and after is not None else None
            status_parts.append("legacy v1: not comparable to v2 input damage")

        values = [event.get("schema"), event.get("timestamp", "?"), event.get("attacker_id"),
                  event.get("victim_object_id"), attack_type, index, event.get("collision_id"),
                  disc_id, skill_id, expected_coef, event.get("damage_decoded_before_corrections"),
                  event.get("legacy_damage_after_extra_hp"), hp_delta, "; ".join(status_parts)]
        print("\t".join("" if v is None else f"{v:g}" if isinstance(v, float) else str(v) for v in values))

    if not complete_count:
        print("No complete or partial ApplyHp events found. Confirm the v2 diagnostic build was installed and the file contains KFDIAG `v=` lines.")
        return 1
    if args.hp_pairs:
        pairs, orphan_pres, orphan_posts, malformed_hp = pair_hp_events(args.log, read_events(args.log))
        print("\nHP snapshots paired by victim and chronology; delta=HPbefore-HPafter (actual applied HP delta)")
        print("time\tvictim\tattacker\ttype\tindex\tcollision\tdecoded_before_corrections\tdamage_after_extra_hp\tHP_before\tHP_after\tactual_HP_delta\traw_line\tpre_line\tpost_line")
        for pair in pairs:
            values = [pair.get("timestamp"), pair["victim_object_id"], pair.get("attacker_id"),
                      pair.get("attack_type"), pair.get("attack_index"), pair.get("collision_id"),
                      pair.get("damage_decoded_before_corrections"), pair["damage_after_extra_hp"],
                      pair["hp_before"], pair["hp_after"], pair["actual_hp_delta"],
                      pair.get("raw_line"), pair["pre_line"], pair["post_line"]]
            print("\t".join("" if value is None else str(value) for value in values))
        print(f"HP pairing summary: {len(pairs)} pairs; {len(orphan_pres)} unmatched pre; "
              f"{len(orphan_posts)} orphan post (discarded); {len(malformed_hp)} malformed/incomplete v4 records")
        for snap in orphan_pres:
            print(f"# unmatched pre snapshot line {snap['line']} victim={snap['victim_object_id']}")
        for snap in orphan_posts:
            print(f"# orphan post snapshot line {snap['line']} victim={snap['victim_object_id']} (discarded)")
        for snap, problem in malformed_hp:
            print(f"# malformed v4 snapshot line {snap.get('line', '?')}: {problem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
