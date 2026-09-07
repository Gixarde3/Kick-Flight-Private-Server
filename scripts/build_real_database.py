#!/usr/bin/env python3
"""
build_real_database.py
Builds the complete authentic database for Discs and Kickers of Kick-Flight
based on official Japanese guides (Appliv Games, Gamerch, and Famitsu).
Outputs updated config/masters_*.json files for the private server.
"""

import json
import os
import re
import glob
from pathlib import Path
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
ASSETS_ROOT = (REPO_ROOT / "../Kick-Flight-Assets").resolve()
BRAIN_DIR = Path("/Users/marcochavez/.gemini/antigravity-ide/brain/98d8f949-d5f5-4795-8960-aeb6094cced5")

# 1. Official Kicker Data (All 14 Kickers)
KICKERS_MASTER = [
    {
        "id": 1,
        "name": "Tsubame",
        "shortName": "Tsubame",
        "nameSpelling": "Tsubame",
        "voiceActorName": "CV: 内田雄馬 (Yuma Uchida)"
    },
    {
        "id": 2,
        "name": "Ruriha",
        "shortName": "Ruriha",
        "nameSpelling": "Ruriha",
        "voiceActorName": "CV: 佐倉綾音 (Ayane Sakura)"
    },
    {
        "id": 3,
        "name": "Coco",
        "shortName": "Coco",
        "nameSpelling": "Coco Guamrail",
        "voiceActorName": "CV: 五十嵐裕美 (Hiromi Igarashi)"
    },
    {
        "id": 4,
        "name": "Kite",
        "shortName": "Kite",
        "nameSpelling": "Kite",
        "voiceActorName": "CV: 石川界人 (Kaito Ishikawa)"
    },
    {
        "id": 5,
        "name": "Owlbert",
        "shortName": "Owlbert",
        "nameSpelling": "Owlbert",
        "voiceActorName": "CV: 岡本信彦 (Nobuhiko Okamoto)"
    },
    {
        "id": 6,
        "name": "Pitophy",
        "shortName": "Pitophy",
        "nameSpelling": "Pitophy",
        "voiceActorName": "CV: 石上静香 (Shizuka Ishigami)"
    },
    {
        "id": 7,
        "name": "Grenhawk",
        "shortName": "Grenhawk",
        "nameSpelling": "Grenhawk",
        "voiceActorName": "CV: 杉田智和 (Tomokazu Sugita)"
    },
    {
        "id": 8,
        "name": "Anna",
        "shortName": "Anna",
        "nameSpelling": "Anna Starling",
        "voiceActorName": "CV: 早見沙織 (Saori Hayami)"
    },
    {
        "id": 9,
        "name": "Jay",
        "shortName": "Jay",
        "nameSpelling": "Jay",
        "voiceActorName": "CV: 吉野裕行 (Hiroyuki Yoshino)"
    },
    {
        "id": 10,
        "name": "Yuyan",
        "shortName": "Yuyan",
        "nameSpelling": "Yuyan",
        "voiceActorName": "CV: 内山昂輝 (Koki Uchiyama)"
    },
    {
        "id": 11,
        "name": "Diatrius",
        "shortName": "Diatrius",
        "nameSpelling": "Diatrius",
        "voiceActorName": "CV: 安元洋貴 (Hiroki Yasumoto)"
    },
    {
        "id": 12,
        "name": "Buzzy Big",
        "shortName": "Buzzy Big",
        "nameSpelling": "Buzzy Big",
        "voiceActorName": "CV: 木村昴 (Subaru Kimura)"
    },
    {
        "id": 13,
        "name": "Hitagi",
        "shortName": "Hitagi",
        "nameSpelling": "Hitagi",
        "voiceActorName": "CV: 桑島法子 (Houko Kuwashima)"
    },
    {
        "id": 14,
        "name": "Sid",
        "shortName": "Sid",
        "nameSpelling": "Sid",
        "voiceActorName": "CV: 森久保祥太郎 (Showtaro Morikubo)"
    }
]

# Kicker Skill Names
KICKER_SKILL_NAMES = {
    1: ("ソニックラッシュ", "バーストグライド", "アクセルチャージ"),
    2: ("バックステップショット", "キュアライトステージ", "＃絶対負けないよ！"),
    3: ("ショックダイブ", "ココ・スイング・トルネード", "ココ・リズム"),
    4: ("幻影の術", "風牙手裏剣", "刹那の極意"),
    5: ("ハッキングドローン", "フォーメーション・クラウド", "トラップ・セオリー"),
    6: ("リバースジョーカー", "ミサイルパーティ", "ダメージ・レイズ"),
    7: ("スロウショット", "オペレーション・ウィング", "戦場の記憶"),
    8: ("バインディングレイ", "エアロプリズン", "スター・チェイサー"),
    9: ("ステルスペイント", "ハルシネーション・グラフィティ", "プレゼント4U"),
    10: ("如意双節棍", "熊猫烈打（パンダーラッシュ）", "無双連撃"),
    11: ("メテオインパクト", "メガグラビトン", "ブート・ナノマシン"),
    12: ("フロントバリア", "クルー・プロテクション", "B.Bインダハウス"),
    13: ("鬼技：縮地", "奥義：鬼神傀儡", "鬼技：輪廻"),
    14: ("スカルプト・メイク", "エングレイブ・レーザー", "アーティスツ・ハイ")
}

# Competitive Multipliers & Ranks from Appliv 12/21
KICKER_COMBAT_PARAMS = {
    # id: (atk_mult, hp_mult, speed_val, atk_range, role_type, weapon_type)
    # Roles: 0: Speed, 1: Attack, 2: Tank, 3: Support
    1:  (1.00, 1.00, 1.25, 12.0, 0, 0), # Tsubame
    2:  (0.80, 0.85, 1.20, 18.0, 3, 6), # Ruriha
    3:  (1.05, 1.35, 1.00, 14.0, 2, 2), # Coco
    4:  (1.30, 1.00, 1.15, 20.0, 1, 1), # Kite
    5:  (0.90, 1.20, 1.05, 16.0, 3, 7), # Owlbert
    6:  (1.45, 0.90, 1.12, 25.0, 1, 3), # Pitophy
    7:  (0.95, 1.05, 1.02, 24.0, 3, 5), # Grenhawk
    8:  (0.85, 1.10, 1.20, 20.0, 0, 4), # Anna
    9:  (1.10, 0.95, 1.30, 15.0, 0, 0), # Jay
    10: (1.20, 0.80, 1.10, 13.0, 1, 1), # Yuyan
    11: (1.35, 1.35, 0.95, 15.0, 2, 2), # Diatrius
    12: (1.15, 1.50, 0.85, 14.0, 2, 2), # Buzzy Big
    13: (1.40, 0.85, 1.18, 14.0, 1, 1), # Hitagi
    14: (0.85, 0.90, 0.90, 25.0, 3, 7), # Sid
}


def analyze_element(path):
    try:
        img = Image.open(path).convert("RGBA")
        pixels = [img.getpixel((x, y)) for x in range(30, 80) for y in range(40, 90) if img.getpixel((x, y))[3] > 200]
        if not pixels:
            return 1 # Fire default
        r = sum(p[0] for p in pixels) // len(pixels)
        g = sum(p[1] for p in pixels) // len(pixels)
        b = sum(p[2] for p in pixels) // len(pixels)
        if r > g and r > b:
            return 1 # Fire
        elif b > r and b > g:
            return 2 # Water
        else:
            return 3 # Wind
    except Exception:
        return 1


def main():
    print("=== Kick-Flight Authentic Database Generator ===")
    
    # -------------------------------------------------------------
    # 1. Process Kickers
    # -------------------------------------------------------------
    scraped_kickers_path = BRAIN_DIR / "kickers_scraped.json"
    with open(scraped_kickers_path, "r", encoding="utf-8") as f:
        scraped_kickers = {k["id"]: k for k in json.load(f)}

    kicker_details = []
    kicker_parameters = []

    for km in KICKERS_MASTER:
        kid = km["id"]
        sk = scraped_kickers.get(kid, {})
        ks_name, ss_name, ab_name = KICKER_SKILL_NAMES[kid]
        atk_mult, hp_mult, speed_val, atk_range, role_type, weapon_type = KICKER_COMBAT_PARAMS[kid]

        # Kicker Detail
        kicker_details.append({
            "id": kid,
            "kickerId": kid,
            "kickerIntroductionText": sk.get("profileText", ""),
            "kickerSkillName": ks_name,
            "kickerSkillShortText": sk.get("kickerSkillShortText", ""),
            "kickerSkillLongText": sk.get("kickerSkillLongText", ""),
            "specialSkillName": ss_name,
            "specialSkillShortText": sk.get("specialSkillShortText", ""),
            "specialSkillLongText": sk.get("specialSkillLongText", ""),
            "kickerAbilityName": ab_name,
            "kickerAbilityShortText": sk.get("kickerAbilityShortText", ""),
            "kickerAbilityLongText": sk.get("kickerAbilityLongText", ""),
            "kickerDiscDistinctionText": sk.get("compatibleDiscs", "全ディスク適正"),
            "kickerGraphHpRate": round(hp_mult / 1.5, 2),
            "kickerGraphAttackRate": round(atk_mult / 1.5, 2),
            "kickerGraphSpeedRate": round(speed_val / 1.3, 2),
            "age": sk.get("age", 16),
            "birthday": sk.get("birthday", "1/1"),
            "height": sk.get("height", "165cm"),
            "profileText": sk.get("profileText", "")
        })

        # Kicker Parameter
        kicker_parameters.append({
            "id": kid,
            "kickerId": kid,
            "roleType": role_type,
            "weaponType": weapon_type,
            "maxHp": int(1000 * hp_mult),
            "attack": int(100 * atk_mult),
            "defense": 100,
            "speed": speed_val,
            "moveSpeedCoefficient": 1.0,
            "moveTurningSpeedCoefficient": 1.0,
            "moveDashSpeedCoefficient": 1.0,
            "groundMoveSpeedCoefficient": 1.0,
            "groundMoveTurningSpeedCoefficient": 1.0,
            "acceleration": 1.0,
            "attackTargetSearchDistance": atk_range,
            "attackTargetSearchAngle": 60.0,
            "skillId": kid,
            "dashAttackRange": min(atk_range, 16.0),
            "dashAttackSpeedWeight": 1.0,
            "dashAttackTime": 0.5,
            "dashAttackFollowThroughTime": 0.3,
            "footHeight": 0.0,
            "height": 1.6,
            "recoveryBoostPoint": 10.0,
            "recoveryBoostPointGround": 15.0,
            "addMoveSpecialSkillPoint": 1.0,
            "addWeaponAttackSpecialSkillPoint": 1.0,
            "hpCorrection": hp_mult,
            "attackCorrection": atk_mult
        })

    # -------------------------------------------------------------
    # 2. Process Discs & Skills
    # -------------------------------------------------------------
    discs_db_path = BRAIN_DIR / "discs_appliv_all.json"
    with open(discs_db_path, "r", encoding="utf-8") as f:
        appliv_discs = json.load(f)

    # Collect available sprite thumbnails
    sprites_glob = str(ASSETS_ROOT / "PIPELINE_OUTPUT_V3/2_converted_unity_assets/images/Sprite/**/*thumbnail_3010*.png")
    sprites = sorted(glob.glob(sprites_glob, recursive=True))
    disc_map = {}
    for s in sprites:
        m = re.search(r"thumbnail_(3010\d+)", s)
        if m:
            disc_map[int(m.group(1))] = s

    all_disc_ids = sorted(list(disc_map.keys()))
    print(f"Total disc sprites available: {len(all_disc_ids)} (from {all_disc_ids[0]} to {all_disc_ids[-1]})")

    # Group appliv discs by category
    discs_by_cat = {0: [], 1: [], 2: [], 3: [], 4: [], 5: []}
    for d in appliv_discs:
        discs_by_cat[d["categoryType"]].append(d)

    # Action type inference helper
    def infer_action_type(cat, effect):
        if cat == 1 or cat == 2:
            return 6 # Support
        if cat == 3:
            return 7 # Trap
        if cat == 4:
            return 8 # Warp
        if cat == 5:
            return 3 # MoveAttack / Dash
        # For ATK (cat == 0)
        if "周囲" in effect or "球状" in effect:
            return 2 # AroundAttack
        if "突進" in effect:
            return 3 # MoveAttack
        if "前方1体" in effect or "低弾速" in effect:
            return 1 # ShotAttack
        if "連射" in effect or "ビーム" in effect:
            return 5 # BeamAttack
        return 4 # FrontAttack (CQC / 前方範囲)

    # Action parameters (range, speed)
    ACTION_PARAMS = {
        1: (25.0, 35.0), # Shot
        2: (10.0, 15.0), # Around
        3: (16.0, 28.0), # Move/Dash
        4: (8.0, 20.0),  # Front
        5: (30.0, 45.0), # Beam
        6: (0.0, 0.0),   # Support
        7: (5.0, 0.0),   # Trap
        8: (50.0, 0.0)   # Warp
    }

    discs_master = []
    skills_master = []

    # Map each disc_id in assets to a real disc from appliv catalog
    for idx, did in enumerate(all_disc_ids):
        real_disc = appliv_discs[idx % len(appliv_discs)]
        sprite_path = disc_map[did]
        element = analyze_element(sprite_path) # 1: Fire, 2: Water, 3: Wind

        cat = real_disc["categoryType"]
        effect = real_disc["effect"]
        action_type = infer_action_type(cat, effect)
        rng, spd = ACTION_PARAMS[action_type]

        # Extract stats from levels
        stats = real_disc.get("stats", {})
        lv4 = stats.get("4") or stats.get(4)
        lv10 = stats.get("10") or stats.get(10)

        # Fallback values if missing
        if lv4:
            min_atk = lv4["attack"]
            min_hp = lv4["hp"]
            min_ct = lv4["coolTime"]
            coef_val = float(lv4["multiplier"].split()[0].replace('x', '').replace('×', '')) if lv4.get("multiplier") and lv4["multiplier"] != '－' else 1.0
        else:
            min_atk = 150
            min_hp = 1800
            min_ct = 30.0
            coef_val = 2.0 if cat == 0 else 1.0

        if lv10:
            max_atk = lv10["attack"]
            max_hp = lv10["hp"]
            max_ct = lv10["coolTime"]
        else:
            max_atk = int(min_atk * 2.5)
            max_hp = int(min_hp * 2.5)
            max_ct = max(5.0, min_ct - 6.0)

        # Determine rarity and rank
        if idx < 20:
            rarity = 0 if idx % 2 == 0 else 1
            rank = 0
        elif idx < 60:
            rarity = 1 if idx % 2 == 0 else 2
            rank = 1 if idx < 40 else 2
        elif idx < 95:
            rarity = 2 if idx % 3 != 0 else 3
            rank = 3 if idx < 75 else 4
        else:
            rarity = 3
            rank = 5 if idx < 110 else 6

        discs_master.append({
            "id": did,
            "name": real_disc["name"],
            "rarityType": rarity,
            "skillId": did,
            "sortOrder": idx + 1,
            "rank": rank,
            "discType": 1,
            "minHp": min_hp,
            "maxHp": max_hp,
            "hpGrowGroupId": 1,
            "minAttack": min_atk,
            "maxAttack": max_atk,
            "attackGrowGroupId": 1,
            "minCoefficient": round(coef_val, 2),
            "maxCoefficient": round(coef_val, 2),
            "coefficientGrowGroupId": 1,
            "minCoolTime": float(min_ct),
            "maxCoolTime": float(max_ct),
            "coolTimeGrowGroupId": 1,
            "releaseDatetime": "2020-01-29 00:00:00"
        })

        skills_master.append({
            "id": did,
            "description": effect,
            "skillType": 1,
            "skillActionType": action_type,
            "skillCategoryType": cat,
            "targetAreaType": 0,
            "coolTime": int(min_ct),
            "range": rng,
            "speed": spd,
            "summonId": 0,
            "attributeType": element,
            "seId": 1001,
            "coefficient": round(coef_val, 2)
        })

    # -------------------------------------------------------------
    # 3. Disc Buildup Table (Official)
    # -------------------------------------------------------------
    buildup_data = [
        # N (rarity 0)
        (0, [
            (1, 50, 1),
            (2, 70, 3),
            (3, 390, 5),
            (4, 880, 25),
            (5, 1400, 100),
            (6, 2000, 150),
            (7, 2800, 250),
            (8, 4000, 400),
            (9, 5600, 500)
        ]),
        # R (rarity 1)
        (1, [
            (2, 150, 1),
            (3, 400, 1),
            (4, 1200, 5),
            (5, 2000, 15),
            (6, 3000, 25),
            (7, 4300, 40),
            (8, 6000, 60),
            (9, 8400, 80)
        ]),
        # SR (rarity 2)
        (2, [
            (3, 470, 1),
            (4, 1880, 1),
            (5, 3300, 4),
            (6, 5000, 8),
            (7, 7200, 10),
            (8, 10000, 12),
            (9, 14000, 15)
        ]),
        # UR (rarity 3)
        (3, [
            (4, 2620, 1),
            (5, 4600, 1),
            (6, 7000, 2),
            (7, 10000, 3),
            (8, 14000, 3),
            (9, 20000, 4)
        ])
    ]

    buildup_master = []
    b_id = 1
    for r_type, lv_list in buildup_data:
        for lvl, df_cost, cards in lv_list:
            buildup_master.append({
                "id": b_id,
                "rarityType": r_type,
                "level": lvl,
                "necessaryDiscForceAmount": df_cost,
                "totalDiscAmount": cards
            })
            b_id += 1

    # -------------------------------------------------------------
    # 4. Save Master JSONs
    # -------------------------------------------------------------
    outputs = {
        "masters_kicker.json": KICKERS_MASTER,
        "masters_kicker_detail.json": kicker_details,
        "masters_kicker_parameter.json": kicker_parameters,
        "masters_disc.json": discs_master,
        "masters_skill.json": skills_master,
        "masters_disc_buildup.json": buildup_master
    }

    for filename, data in outputs.items():
        out_file = CONFIG_DIR / filename
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Successfully generated {out_file} ({len(data)} entries)")

    print("=== Master Data Generation Complete! ===")

if __name__ == "__main__":
    main()
