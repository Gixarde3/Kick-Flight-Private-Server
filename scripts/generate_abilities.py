"""Kicker passive data (`masters_kicker_ability.json` / `masters_kicker_ability_condition.json`).

Everything the client does with these two tables is in `*AbilityParameter` (one class per weapon type,
chosen by `KickerParameterMasterData.WeaponType`). `PlayerAbilityParameterBase..ctor` (0x18E9064) fills
`Datas` with the `KickerAbility` rows of this kicker (in served order) and `Conditions` with the
`KickerAbilityCondition` rows of those abilities (each becomes `ConditionInfo(conditionType, triggerType,
-1, -1, limitCount, null, duration, interval, effectValue)`), so `kickerAbilityId` must point at its
ability row's `id` and the *order* of that kicker's ability rows matters where a class indexes them.

Trigger values actually delivered to a passive (verified by scanning every call site):

    1  heal path     ApplyHeal / ApplyHealBoostPoint / ApplyCondition     (to the healed character)
    2  AbilityConditionAction only, from PlayerCharacter.ApplyCondition+0x5b8 (AddDamage)
    3  PlayerStateAvoid / PlayerStateBarrelRoll UpdateState               (dodge / barrel roll)
    4  PlayerStateDead coroutine                                          (your own death)
    5  ObjectManager.AddTrap                                              (a trap disc was placed)
    6  PlayerCharacter.ApplyDamage -> ApplyDeadState (also calls AddKillCount)  (you took someone out)

Per class, which fields it reads (see docs/ for the full table):

    1  Sword          UpdateAbility (no trigger)  value = HP ratio threshold; Conditions[0].effectValue
    2  TwoGuns        ExecuteAbility(1)           time = duration; value -> DamageRate (INCOMING damage,
                                                  the field `AcceptDamageInfo` multiplies: 0.6 = -40%)
    3  Hammer         AbilityConditionAction(2)   nothing from this row; hands the *target* the condition
    4  ThrowingStar   ExecuteAbility(3)           value = fraction of the Kicker Skill cooldown removed
                                                  (Clamp01(1 - value) * maxCoolTime, so >= 1.0 = full reset)
    5  Drone          ctor+ExecuteAbility(5)      Datas[0] = attack cap, Datas[1] = time cap; both
                                                  `1 + value * overlapCount` (ctor THROWS with < 2 rows)
    6  RocketLauncher UpdateAbility (no trigger)  AttackRate = 1 + min(KillCount, overlapCount) * value
    7  Bowgun         UpdateAbility (no trigger)  value = HP ratio threshold; Conditions it owns
    8  Gun            UpdateAbility (no trigger)  value -> SpeedRate while lock-on
    9  Bat            ExecuteAbility(4)           value = trap skill id (skill_40001 = the bat bomb)
    10 Nunchaku       AbilityConditionAction(2)   time = window; value = add per weapon hit; cap =
                                                  `1 + value * overlapCount` (ctor 0x13F897C); weapon-only
    11 PunchGlove     UpdateAbility (no trigger)  time = seconds between heals; value = heal as a
                                                  fraction of MaxHP (threshold 0.5 lives in the asset
                                                  KickerAbilityParameterMaster._executeAbilityHpValue)
    12 Shield         ExecuteAbility(4)           requires >= 1 condition row; hands every living ally a
                                                  ShieldAll condition
    13 JapaneseSword  ExecuteAbility(6)           same shape as 4 (full reset needs value >= 1.0)
    14 Laser          AbilityConditionAction(2)   time = seconds subtracted from the Kicker Skill cooldown,
                                                  but ONLY for weapon hits on a shielded target (ShieldAll /
                                                  ShieldForward condition) or a TagType.Sacrifice object -
                                                  the 2.11.0 passive. The design passive (+100 % attack speed
                                                  while his statue stands) is served as an AttackSpeedRate
                                                  condition on kicker skill 20014 (generate_combat_masters.py).

Design numbers (Tanuki, 2026-09-20): Sword 50% HP -> +100% boost gauge recovery (the character is Tsubame);
TwoGuns heal disc -> -40%
incoming damage for 3 s; Hammer -> -40% outgoing damage on the target for 2 s; ThrowingStar dodge ->
Kicker Skill reset; Drone TRAP disc damage +7.5% per cast up to +75% and its duration +2.5% per cast up
to +50% (two rows: 10 casts and 20 casts to their caps); RocketLauncher +15% per takedown (the
client needs `overlapCount` as the cap; reset on death is engine-side via ResetKillCount); Bowgun +30%
atk under 50% HP; Gun speed while locked on (number not specified); Bat drops a bomb on your own death
(the 10x ATK payload lives in the trap skill, not here); Nunchaku +10% per normal hit, max +50%,
resetting 1 s after the last hit; PunchGlove heal per period (number to tune); Shield on your death
grants all allies a ShieldAll that eats one instance (limitCount 1); JapaneseSword takedown -> reset;
Laser cooldown reduction per basic-attack hit.
"""

import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config"

BAT_BOMB_SKILL_ID = 40001  # skill_40001, the trap `BatAbilityParameter` spawns (see generate_combat_masters.py)

# kickerId, triggerType, time, value, overlapCount
ABILITIES = [
    (1, 1, 5.0, 0.50, 1),        # Sword: HP threshold; the +20% is the condition's effectValue
    (2, 1, 3.0, 0.60, 1),        # TwoGuns: heal disc -> DamageRate 0.6 (-40% incoming) for 3 s
    (3, 2, 5.0, 1.2, 1),         # Hammer: fires through AbilityConditionAction; magnitude in the condition
    (4, 3, 5.0, 1.0, 1),         # ThrowingStar: dodge -> Kicker Skill cooldown reset
    (5, 5, 5.0, 0.075, 10),      # Drone (Datas[0], trap damage): +7.5% per cast, cap 1 + 0.075*10 = +75%
    (6, 1, 5.0, 0.15, 10),       # RocketLauncher: +15% per takedown, cap 1 + 0.15*10 = +150%
    (7, 1, 5.0, 0.50, 1),        # Bowgun: HP threshold; +30% atk comes from its condition
    (8, 1, 5.0, 1.20, 1),        # Gun: SpeedRate while locked on (design number unspecified)
    (9, 4, 5.0, BAT_BOMB_SKILL_ID, 1),  # Bat: own death -> bomb trap (kept an int, as it was served before)
    (10, 2, 1.0, 0.10, 5),       # Nunchaku: +10% per weapon hit, cap +50%, 1 s since the last hit
    (11, 1, 5.0, 0.05, 1),       # PunchGlove: 5% MaxHP every 5 s under 50% HP (TUNE)
    (12, 4, 5.0, 1.2, 1),        # Shield: own death -> ShieldAll to all allies
    (13, 6, 5.0, 1.0, 1),        # JapaneseSword: takedown -> Kicker Skill cooldown reset
    (14, 2, 0.5, 1.2, 1),        # Laser: -0.5 s of Kicker Skill cooldown per weapon hit on a shield (TUNE)
]

# Drone is the only kicker whose class indexes its rows: Datas[0] = trap attack rate, Datas[1] = trap
# time rate, and the ctor reads Datas[1] unconditionally (a single row throws IndexOutOfRange and the
# match never finishes loading). Keep the duration row second; id 15 keeps it after id 5 even if the
# master is sorted by id.
DRONE_TIME_ROW = {"id": 15, "kickerId": 5, "triggerType": 5, "time": 5.0, "value": 0.025, "overlapCount": 20}

# kickerAbilityId, conditionType, duration, effectValue, triggerType, limitCount
CONDITIONS = [
    # Sword reads Conditions[0].effectValue with no type filter. It is a multiplier on the boost gauge
    # gain (PlayerCharacter.UpdateBoostPointRecovery: base * gear * this rate, and ResetRate() puts every
    # rate back to 1.0), so +100% is 2.0.
    (1, 1, 5.0, 2.0, 1, 1),
    # Hammer hands the hit target a ConditionInitializeInfo whose only discriminator is
    # ConditionTriggerType.Execute (3) -- so this row's triggerType must be 3 or nothing resolves.
    # AttackRate 0.6 = -40% outgoing damage (AttackRate is what PlayerParameter.GetAttack multiplies).
    (3, 1, 2.0, 0.6, 3, 1),
    # Bowgun only takes conditions whose conditionType is AttackRate.
    (7, 1, 5.0, 1.3, 1, 1),
    # Shield: ShieldAll (27 -- ShieldForward 26 is his Kicker Skill), one instance blocked.
    (12, 27, 5.0, 1.0, 3, 1),
]


def main() -> None:
    abilities = [{"id": kid, "kickerId": kid, "triggerType": trig, "time": t, "value": v, "overlapCount": n}
                 for kid, trig, t, v, n in ABILITIES]
    abilities.insert(5, dict(DRONE_TIME_ROW))  # right after kicker 5's attack row

    conditions = [{"id": ability_id, "kickerAbilityId": ability_id, "conditionType": ctype,
                   "duration": dur, "interval": 1.0, "effectValue": effect, "triggerType": trig,
                   "limitCount": limit}
                  for ability_id, ctype, dur, effect, trig, limit in CONDITIONS]

    for name, rows in (("masters_kicker_ability.json", abilities),
                       ("masters_kicker_ability_condition.json", conditions)):
        (CONFIG / name).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote config/{name} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
