import json

# Units flown to fill the special-skill gauge (games.app-liv.jp/archives/431798); PlayerCharacter.CalcChargeSP
# adds distance x addMoveSpecialSkillPoint per frame and GetMaxSP is 100.
SP_FULL_DISTANCE = {1: 740, 2: 800, 3: 800, 4: 845, 5: 650, 6: 650, 7: 760, 8: 1500, 9: 550, 10: 1180, 11: 900,
                    12: 630, 13: 960, 14: 1350}

# Canonical RoleType enum: Speed = 0, Support = 1, Attack = 2, Tank = 3
kickers_roles = {
    1: 0,  # Tsubame (Speed)
    2: 1,  # Ruriha (Support)
    3: 3,  # Coco (Tank)
    4: 2,  # Kite (Attack)
    5: 1,  # Owlbert (Support)
    6: 2,  # Pitophy (Attack)
    7: 3,  # Grenhawk (Tank)
    8: 0,  # Anna (Speed)
    9: 0,  # Jay (Speed)
    10: 2, # Yuyan (Attack)
    11: 3, # Diatrius (Tank)
    12: 3, # Buzzy Big (Tank)
    13: 2, # Hitagi (Attack)
    14: 0  # Sid (Speed)
}

# Canonical WeaponType enum:
# Sword = 0, TwoGuns = 1, Hammer = 2, ThrowingStar = 3, Drone = 4,
# RocketLauncher = 5, Gun = 6, PunchGlove = 7, Bowgun = 8, Shield = 9,
# Bat = 10, Nunchaku = 11, JapaneseSword = 12, Laser = 13
kickers_weapons = {
    1: 0,   # Tsubame (Sword)
    2: 6,   # Ruriha (Gun)
    3: 2,   # Coco (Hammer)
    4: 7,   # Kite (PunchGlove)
    5: 4,   # Owlbert (Drone)
    6: 3,   # Pitophy (ThrowingStar)
    7: 5,   # Grenhawk (RocketLauncher)
    8: 8,   # Anna (Bowgun)
    9: 1,   # Jay (TwoGuns)
    10: 12, # Yuyan (JapaneseSword)
    11: 9,  # Diatrius (Shield)
    12: 10, # Buzzy Big (Bat)
    13: 11, # Hitagi (Nunchaku)
    14: 13  # Sid (Laser)
}

param_list = []
# kickerId -> (footHeight = hips height, height = head top) measured on the pc_<k>_001 body prefabs (2026-09-19)
BODY_HEIGHTS = {1: (0.79, 1.64), 2: (0.89, 1.58), 3: (0.81, 1.56), 4: (0.83, 1.67), 5: (0.78, 1.62), 6: (0.52, 1.3),
                7: (0.99, 1.91), 8: (1.02, 1.82), 9: (0.93, 1.83), 10: (0.81, 1.6), 11: (1.16, 2.23), 12: (0.65, 1.66),
                13: (0.84, 1.63), 14: (1.0, 1.89)}

for kid in range(1, 15):
    role = kickers_roles[kid]
    weapon = kickers_weapons[kid]
    
    # Empirical private-server flight baseline. Keep role-specific turning and
    # dash-attack reach, but do not throttle traversal by role: the recovered
    # lower values made non-Speed kickers feel nearly stationary in battle.
    base_speed = 24.0
    dash_coeff = 3.2
    accel = 36.0
    if role == 0:
        turn_coeff = 1.35
        dash_range = 18.0
    elif role == 2:
        turn_coeff = 1.15
        dash_range = 15.0
    elif role == 1:
        turn_coeff = 1.2
        dash_range = 13.0
    else: # Tank (3)
        turn_coeff = 1.0
        dash_range = 12.0

    param_list.append({
        "id": kid,
        "kickerId": kid,
        "roleType": role,
        "weaponType": weapon,
        "maxHp": 1200 if role == 3 else (1000 if role == 1 else 900),
        "attack": 120 if role == 2 else 100,
        "defense": 100,
        "speed": base_speed,
        "moveSpeedCoefficient": 1.0,
        "moveTurningSpeedCoefficient": turn_coeff,
        "moveDashSpeedCoefficient": dash_coeff,
        "groundMoveSpeedCoefficient": 1.0,
        "groundMoveTurningSpeedCoefficient": 1.0,
        "acceleration": accel,
        "attackTargetSearchDistance": 12.0,
        "attackTargetSearchAngle": 60.0,
        "skillId": kid,
        "dashAttackRange": dash_range,
        "dashAttackSpeedWeight": 1.0,
        "dashAttackTime": 0.5,
        "dashAttackFollowThroughTime": 0.3,
        # PlayerModelControllerBase.SetHeight puts the model at localPosition.y = -footHeight, i.e. the character root
        # (colliders, condition effects such as the Crew Protection sphere, lock-on) sits footHeight above the feet.
        # 0.0 stood every kicker on top of its own effects. Values = hips height / head top of the body prefab
        # (scripts/re/bundle_tree.py on player/pc_<k>/pc_<k>_001, rest pose), see BODY_HEIGHTS.
        "footHeight": BODY_HEIGHTS[kid][0],
        "height": BODY_HEIGHTS[kid][1],
        "recoveryBoostPoint": 10.0,
        "recoveryBoostPointGround": 15.0,
        "addMoveSpecialSkillPoint": round(100.0 / SP_FULL_DISTANCE[kid], 4),  # SP per unit flown (MaxSP 100)
        "addWeaponAttackSpecialSkillPoint": 1.0,
        "hpCorrection": 1.0,
        "attackCorrection": 1.0
    })

with open("config/masters_kicker_parameter.json", "w", encoding="utf-8") as f:
    json.dump(param_list, f, indent=2)

print(f"Generated {len(param_list)} kicker parameters in config/masters_kicker_parameter.json")
