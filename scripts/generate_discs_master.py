#!/usr/bin/env python3
"""Generate complete master data for all 126 Kick-Flight Discs and Skills."""

import json
import re
import glob
from pathlib import Path
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_ROOT = (REPO_ROOT / "../Kick-Flight-Assets").resolve()
SPRITES_GLOB = str(ASSETS_ROOT / "PIPELINE_OUTPUT_V3/2_converted_unity_assets/images/Sprite/**/*thumbnail_3010*.png")

def analyze_element(path):
    try:
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        # Sample upper corner pixels
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
    print("Collecting and analyzing 126 disc thumbnails...")
    sprites = sorted(glob.glob(SPRITES_GLOB, recursive=True))
    disc_map = {}
    for s in sprites:
        m = re.search(r"thumbnail_(3010\d+)", s)
        if m:
            disc_id = int(m.group(1))
            if disc_id not in disc_map:
                disc_map[disc_id] = s

    all_ids = sorted(list(disc_map.keys()))
    print(f"Found {len(all_ids)} unique disc IDs: {all_ids[0]} to {all_ids[-1]}")

    # Skill archetypes
    # Categories: 0: Attack, 1: Heal, 2: Buff, 3: Trap, 4: Warp
    # Actions: 1: ShotAttack, 2: AroundAttack, 3: MoveAttack, 4: FrontAttack, 5: BeamAttack, 6: Support, 7: Trap, 8: Warp
    archetypes = [
        # Front Attack (CQC)
        {"cat": 0, "act": 4, "range": 8.0, "speed": 20.0, "cd": 14, "coef": 2.4,
         "names": {
             1: ["Colmillo Ígneo", "Garra Volcánica", "Corte Abrasador", "Mordisco de Fuego", "Puño Sísmico"],
             2: ["Zarpazo Glacial", "Colmillo Polar", "Corte Abisal", "Gélido Desgarro", "Impacto Marea"],
             3: ["Tajo Esmeralda", "Garra Huracanada", "Céfiro Cortante", "Espina Vórtice", "Corte Ciclón"]
         },
         "desc": "Ataque cuerpo a cuerpo contundente que causa gran daño al rival y lo desestabiliza."},

        # Move Attack (Dash attack)
        {"cat": 0, "act": 3, "range": 16.0, "speed": 28.0, "cd": 16, "coef": 2.2,
         "names": {
             1: ["Embestida Ardiente", "Vuelo de Meteorito", "Carga Ígnea", "Cohete Carmesí", "Ráfaga Ígnea"],
             2: ["Embestida Tsunami", "Carga Glacial", "Delfín Abisal", "Ráfaga Torrencial", "Ola Rompedora"],
             3: ["Vuelo Ciclónico", "Embestida Huracán", "Ráfaga Viento Feroz", "Picado Celestial", "Dardo Tempestuoso"]
         },
         "desc": "Carga veloz hacia el frente recorriendo gran distancia y embistiendo a los rivales a su paso."},

        # Shot Attack (Projectile)
        {"cat": 0, "act": 1, "range": 25.0, "speed": 35.0, "cd": 13, "coef": 1.9,
         "names": {
             1: ["Disparo de Magma", "Piroesfera Guiada", "Lanza Solar", "Chispazo Fulgurante", "Bala de Fuego"],
             2: ["Carámbano Afilado", "Proyectil Marino", "Dardo Helado", "Gota Perforante", "Flecha Acuática"],
             3: ["Pluma Tempestuosa", "Aguja de Aire", "Ráfaga Huracán", "Flecha Sonora", "Dardo Verde"]
         },
         "desc": "Dispara proyectiles veloces guiados de alta precisión contra objetivos a larga distancia."},

        # Around Attack (Radial AoE)
        {"cat": 0, "act": 2, "range": 10.0, "speed": 15.0, "cd": 18, "coef": 2.6,
         "names": {
             1: ["Nova Ardiente", "Estallido Volcánico", "Anillo Ígneo", "Supernova Carmesí", "Círculo de Llamas"],
             2: ["Ventisca Polar", "Maelstrom Abisal", "Tormenta Glacial", "Onda Marea", "Esfera Fría"],
             3: ["Tornado Esmeralda", "Cúpula Tempestad", "Vórtice Aéreo", "Huracán Radial", "Viento Desatado"]
         },
         "desc": "Libera una devastadora explosión elemental en área circular alrededor del Kicker."},

        # Beam Attack
        {"cat": 0, "act": 5, "range": 30.0, "speed": 45.0, "cd": 20, "coef": 2.8,
         "names": {
             1: ["Láser Solar", "Haz de Plasma", "Rayo Ígneo", "Cañón Magmático", "Rayo Térmico"],
             2: ["Rayo Criogénico", "Haz Glacial", "Láser Abisal", "Columna de Agua", "Rayo Polar"],
             3: ["Haz de Vacío", "Rayo Sísmico", "Láser Temporal", "Corte Cuántico", "Haz Galáctico"]
         },
         "desc": "Canaliza un potente rayo continuo que atraviesa defensas y golpea a todos los objetivos en fila."},

        # Heal (Instant / Regen)
        {"cat": 1, "act": 6, "range": 0.0, "speed": 0.0, "cd": 22, "coef": 1.0,
         "names": {
             1: ["Llama de Vitalidad", "Calor Reparador", "Fénix Restaurador", "Corazón Ígneo", "Bendición Solar"],
             2: ["Manantial Puro", "Gotas de Rocío", "Bálsamo Marino", "Oasis Sanador", "Gotas de Vida"],
             3: ["Brisa Sanadora", "Aliento de Vida", "Savia del Bosque", "Cura Esmeralda", "Céfiro Vital"]
         },
         "desc": "Recupera instantáneamente una porción sustancial de los puntos de salud máximos."},

        # Shield / Buff
        {"cat": 2, "act": 6, "range": 0.0, "speed": 0.0, "cd": 24, "coef": 1.0,
         "names": {
             1: ["Manto de Lava", "Escudo Ígneo", "Muralla de Fuego", "Coraza de Rubí", "Baluarte Ardiente"],
             2: ["Barrera Égida", "Cúpula de Hielo", "Manto Acuático", "Escudo de Cristal", "Baluarte Zafiro"],
             3: ["Velo Huracanado", "Escudo Ciclónico", "Manto de Plumas", "Barrera Tempestad", "Aura Esmeralda"]
         },
         "desc": "Despliega una resistente barrera de energía que anula el daño y previene derribos."},

        # Trap
        {"cat": 3, "act": 7, "range": 5.0, "speed": 0.0, "cd": 19, "coef": 1.8,
         "names": {
             1: ["Mina de Fuego", "Trampa Volcánica", "Red Ardiente", "Cepo Explosivo", "Foso de Magma"],
             2: ["Cepo de Escarcha", "Mina Fría", "Trampa Marea", "Foso Glacial", "Prisión de Hielo"],
             3: ["Trampa Gravitatoria", "Mina de Vacío", "Cepo Vendaval", "Red Tempestuosa", "Vórtice Oculto"]
         },
         "desc": "Coloca una trampa invisible en el espacio que inmoviliza y daña a cualquier rival que la detone."},

        # Warp
        {"cat": 4, "act": 8, "range": 50.0, "speed": 0.0, "cd": 25, "coef": 1.0,
         "names": {
             1: ["Paso Ígneo", "Salto de Fénix", "Teletransporte Carmesí", "Parpadeo Solar", "Salto Magmático"],
             2: ["Warp de Marea", "Salto Acuático", "Reflejo Marino", "Teletransporte Polar", "Parpadeo Abisal"],
             3: ["Salto Dimensional", "Warp Estratégico", "Parpadeo Céfiro", "Salto Huracán", "Teletransporte Aéreo"]
         },
         "desc": "Teletransporta instantáneamente al Kicker a la posición de un aliado o del guardián de cristales."}
    ]

    discs = []
    skills = []
    rarity_dist = [0, 1, 2, 3] # N, R, SR, UR

    for idx, disc_id in enumerate(all_ids):
        sprite_path = disc_map[disc_id]
        element = analyze_element(sprite_path) # 1: Fire, 2: Water, 3: Wind
        
        # Determine archetype cleanly across index
        arch = archetypes[idx % len(archetypes)]
        
        # Determine rarity:
        # Lower IDs (first 20) -> N and R
        # Middle IDs (20..80) -> R and SR
        # Higher IDs (80..126) -> SR and UR
        if idx < 20:
            rarity = 0 if idx % 2 == 0 else 1
            rank = 0 # Rank D
        elif idx < 60:
            rarity = 1 if idx % 2 == 0 else 2
            rank = 1 if idx < 40 else 2 # Rank C or B
        elif idx < 95:
            rarity = 2 if idx % 3 != 0 else 3
            rank = 3 # Rank A
        else:
            rarity = 3 # UR
            rank = 4 # Rank S

        # Select name
        name_list = arch["names"][element]
        name_base = name_list[idx % len(name_list)]
        suffix = f" {['I', 'II', 'III', 'IV', 'V', 'EX', 'Zero', 'Plus', 'Alpha', 'Omega'][idx % 10]}" if idx >= len(name_list) else ""
        disc_name = f"{name_base}{suffix}"

        # Base stats scaling with rarity
        # N: HP 200..700, Atk 60..200
        # R: HP 350..1100, Atk 110..320
        # SR: HP 500..1500, Atk 160..480
        # UR: HP 700..2100, Atk 220..680
        base_hp = [200, 350, 500, 700][rarity]
        max_hp = [700, 1100, 1500, 2100][rarity]
        base_atk = [60, 110, 160, 220][rarity]
        max_atk = [200, 320, 480, 680][rarity]
        cd_min = arch["cd"]
        cd_max = max(8.0, arch["cd"] - [2.0, 3.0, 4.0, 5.0][rarity])

        coef_min = arch["coef"]
        coef_max = coef_min * [1.4, 1.6, 1.8, 2.0][rarity]

        disc_entry = {
            "id": disc_id,
            "name": disc_name,
            "rarityType": rarity,
            "skillId": disc_id,
            "sortOrder": idx + 1,
            "rank": rank,
            "discType": 1,
            "minHp": base_hp,
            "maxHp": max_hp,
            "hpGrowGroupId": 1,
            "minAttack": base_atk,
            "maxAttack": max_atk,
            "attackGrowGroupId": 1,
            "minCoefficient": round(coef_min, 2),
            "maxCoefficient": round(coef_max, 2),
            "coefficientGrowGroupId": 1,
            "minCoolTime": float(cd_min),
            "maxCoolTime": float(cd_max),
            "coolTimeGrowGroupId": 1,
            "releaseDatetime": "2019-01-01 00:00:00"
        }
        discs.append(disc_entry)

        skill_entry = {
            "id": disc_id,
            "description": arch["desc"],
            "skillType": 1, # Disc
            "skillActionType": arch["act"],
            "skillCategoryType": arch["cat"],
            "targetAreaType": 0,
            "coolTime": cd_min,
            "range": arch["range"],
            "speed": arch["speed"],
            "summonId": 0,
            "attributeType": element,
            "seId": 1001,
            "coefficient": round(coef_max, 2)
        }
        skills.append(skill_entry)

    # Disc Rarity Master
    disc_rarities = [
        {"id": 1, "rarityType": 0, "initialLevel": 1},
        {"id": 2, "rarityType": 1, "initialLevel": 1},
        {"id": 3, "rarityType": 2, "initialLevel": 1},
        {"id": 4, "rarityType": 3, "initialLevel": 1}
    ]

    # Disc Grow Master (Levels 1 to 50)
    disc_grows = []
    for lvl in range(1, 51):
        disc_grows.append({
            "id": lvl,
            "groupId": 1,
            "level": lvl,
            "rate": round(1.0 + (lvl - 1) * 0.05, 3)
        })

    # Disc Buildup Master (Levels 1 to 50 for each rarity)
    disc_buildups = []
    buildup_id = 1
    for r in range(4): # N, R, SR, UR
        for lvl in range(1, 51):
            disc_buildups.append({
                "id": buildup_id,
                "rarityType": r,
                "level": lvl,
                "necessaryDiscForceAmount": lvl * 50 * (r + 1),
                "totalDiscAmount": 1 + lvl * (4 - r)
            })
            buildup_id += 1

    # Initial Disc Decks
    initial_decks = [
        {"id": 1, "number": 1, "discId1": all_ids[0], "discId2": all_ids[1], "discId3": all_ids[2], "discId4": all_ids[3]},
        {"id": 2, "number": 2, "discId1": all_ids[4], "discId2": all_ids[5], "discId3": all_ids[6], "discId4": all_ids[7]},
        {"id": 3, "number": 3, "discId1": all_ids[8], "discId2": all_ids[9], "discId3": all_ids[10], "discId4": all_ids[11]}
    ]

    # Gears Master
    # Color types: 0: Red, 1: Green, 2: Yellow, 3: Blue, 4: White
    # 25 GearSkillTypes
    gear_skills_def = [
        (0, "Aumento de PS Máximos", "Incrementa la salud máxima del Kicker."),
        (1, "Aumento de Potencia de Ataque", "Incrementa el daño de todos los ataques."),
        (2, "Velocidad de Movimiento", "Aumenta la velocidad de vuelo y desplazamiento."),
        (3, "Potenciación de Fuego", "Incrementa el daño de habilidades y discos ígneos."),
        (4, "Potenciación de Agua", "Incrementa el daño de habilidades y discos de agua."),
        (5, "Potenciación de Viento", "Incrementa el daño de habilidades y discos de viento."),
        (6, "Resistencia al Aturdimiento", "Reduce la duración del aturdimiento recibido."),
        (7, "Resistencia a la Parálisis", "Reduce la probabilidad y duración de parálisis."),
        (8, "Resistencia al Veneno", "Reduce el daño continuo causado por veneno."),
        (9, "Resistencia al Silencio", "Reduce la duración del bloqueo de habilidades."),
        (10, "Resistencia a Debuffs de Ataque", "Mitiga la reducción de ataque enemiga."),
        (11, "Resistencia a Debuffs de Defensa", "Mitiga la reducción de defensa enemiga."),
        (12, "Resistencia a Debuffs de Velocidad", "Mitiga la ralentización de vuelo enemiga."),
        (13, "Reducción de Tiempo de Recarga", "Acelera la recarga de todos los discos equipados."),
        (14, "Carga Acelerada de Habilidad Especial", "Aumenta la ganancia de medidor especial."),
        (15, "Regeneración Rápida de Boost", "Recupera la barra de aceleración con mayor velocidad."),
        (16, "Aumento de Curación Recibida", "Potencia los efectos de curación recibidos."),
        (17, "Potenciador de Buffs de Ataque", "Extiende la duración y potencia de mejoras de ataque."),
        (18, "Potenciador de Buffs de Defensa", "Extiende la duración y potencia de mejoras de defensa."),
        (19, "Potenciador de Buffs de Velocidad", "Extiende la duración de mejoras de velocidad."),
        (20, "Reaparición Acelerada tras Muerte", "Reduce los segundos de reaparición en combate."),
        (21, "Retención de Puntos Especiales al Morir", "Conserva parte del medidor especial al ser derrotado."),
        (22, "Resistencia Mixta: Ataque y Velocidad", "Mitiga debuffs tanto de ataque como de velocidad."),
        (23, "Resistencia Mixta: Silencio y Veneno", "Inmunidad parcial a silencio y veneno."),
        (24, "Sinergia Mixta: Ataque y Velocidad", "Aumenta conjuntamente las mejoras de ataque y vuelo.")
    ]

    gear_skills = []
    gears = []
    gear_id = 1
    for skill_type, name, desc in gear_skills_def:
        gear_skills.append({
            "id": skill_type + 1,
            "name": name,
            "gearSkillType": skill_type,
            "groupId": skill_type + 1
        })
        # Generate gears of different rarities and colors for each skill
        for rarity in range(4): # N, R, SR, UR
            for color in range(5): # Red, Green, Yellow, Blue, White
                coef = round(0.02 + 0.02 * rarity + 0.005 * color, 3)
                gears.append({
                    "id": gear_id,
                    "name": f"Engranaje {name} ({['N', 'R', 'SR', 'UR'][rarity]})",
                    "rarityType": rarity,
                    "gearColorType": color,
                    "gearSkillId": skill_type + 1,
                    "coefficient": coef
                })
                gear_id += 1

    # Gear Same Color Bonus
    gear_color_bonuses = []
    bonus_id = 1
    for r in range(4):
        for count in [2, 3]:
            gear_color_bonuses.append({
                "id": bonus_id,
                "groupId": 1,
                "rarityType": r,
                "count": count,
                "coefficient": round(0.05 * count * (r + 1), 3)
            })
            bonus_id += 1

    # Write files
    (REPO_ROOT / "config/masters_disc.json").write_text(json.dumps(discs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPO_ROOT / "config/masters_skill.json").write_text(json.dumps(skills, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPO_ROOT / "config/masters_disc_rarity.json").write_text(json.dumps(disc_rarities, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPO_ROOT / "config/masters_disc_grow.json").write_text(json.dumps(disc_grows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPO_ROOT / "config/masters_disc_buildup.json").write_text(json.dumps(disc_buildups, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPO_ROOT / "config/masters_initial_disc_deck.json").write_text(json.dumps(initial_decks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPO_ROOT / "config/masters_gear.json").write_text(json.dumps(gears, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPO_ROOT / "config/masters_gear_skill.json").write_text(json.dumps(gear_skills, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPO_ROOT / "config/masters_gear_same_color_bonus.json").write_text(json.dumps(gear_color_bonuses, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Generated:")
    print(f" - {len(discs)} Discs in config/masters_disc.json")
    print(f" - {len(skills)} Skills in config/masters_skill.json")
    print(f" - {len(disc_rarities)} Rarity entries in config/masters_disc_rarity.json")
    print(f" - {len(disc_grows)} Grow levels in config/masters_disc_grow.json")
    print(f" - {len(disc_buildups)} Buildup tiers in config/masters_disc_buildup.json")
    print(f" - {len(initial_decks)} Initial Decks in config/masters_initial_disc_deck.json")
    print(f" - {len(gears)} Gears in config/masters_gear.json")
    print(f" - {len(gear_skills)} Gear Skills in config/masters_gear_skill.json")
    print(f" - {len(gear_color_bonuses)} Gear Color Bonuses in config/masters_gear_same_color_bonus.json")

if __name__ == "__main__":
    main()
