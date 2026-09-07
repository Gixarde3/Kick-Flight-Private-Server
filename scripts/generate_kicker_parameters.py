import json

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
for kid in range(1, 15):
    role = kickers_roles[kid]
    weapon = kickers_weapons[kid]
    param_list.append({
        "id": kid,
        "kickerId": kid,
        "roleType": role,
        "weaponType": weapon,
        "maxHp": 1200 if role == 3 else (1000 if role == 1 else 900),
        "attack": 120 if role == 2 else 100,
        "defense": 100,
        "speed": 1.2 if role == 0 else 1.0,
        "moveSpeedCoefficient": 1.0,
        "moveTurningSpeedCoefficient": 1.0,
        "moveDashSpeedCoefficient": 1.0,
        "groundMoveSpeedCoefficient": 1.0,
        "groundMoveTurningSpeedCoefficient": 1.0,
        "acceleration": 1.0,
        "attackTargetSearchDistance": 12.0,
        "attackTargetSearchAngle": 60.0,
        "skillId": kid,
        "dashAttackRange": 5.0,
        "dashAttackSpeedWeight": 1.0,
        "dashAttackTime": 0.5,
        "dashAttackFollowThroughTime": 0.3,
        "footHeight": 0.0,
        "height": 1.6,
        "recoveryBoostPoint": 10.0,
        "recoveryBoostPointGround": 15.0,
        "addMoveSpecialSkillPoint": 1.0,
        "addWeaponAttackSpecialSkillPoint": 1.0,
        "hpCorrection": 1.0,
        "attackCorrection": 1.0
    })

with open("config/masters_kicker_parameter.json", "w", encoding="utf-8") as f:
    json.dump(param_list, f, indent=2)

print(f"Generated {len(param_list)} kicker parameters in config/masters_kicker_parameter.json")
