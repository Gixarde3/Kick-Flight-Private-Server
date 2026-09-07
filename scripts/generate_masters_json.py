import json

kickers_meta = [
    {"id": 1, "name": "Tsubame", "short": "Tsubame", "spelling": "Tsubame", "va": "Yuma Uchida",
     "intro": "Veloz como el viento, domina el combate aéreo con agilidad.",
     "skill": "Corte Relámpago", "skill_s": "Ataque rápido frontal", "skill_l": "Se lanza hacia adelante realizando un corte veloz.",
     "sp": "Torbellino Esmeralda", "sp_s": "Genera una corriente ascendente masiva", "sp_l": "Crea un poderoso tornado que dispersa a los rivales y recoge cristales.",
     "ab": "Paso Ligero", "ab_s": "Aumenta la velocidad al recoger cristales", "ab_l": "La velocidad de movimiento se incrementa temporalmente tras recoger cristales.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 22, 23]},
    {"id": 2, "name": "Ruriha", "short": "Ruriha", "spelling": "Ruriha", "va": "Ayane Sakura",
     "intro": "Kicker de apoyo que restaura la salud de sus compañeros con notas musicales.",
     "skill": "Onda Sanadora", "skill_s": "Cura a aliados cercanos", "skill_l": "Emite una frecuencia sonora que recupera gradualmente los PS de su equipo.",
     "sp": "Concierto Estelar", "sp_s": "Inmunidad y regeneración total", "sp_l": "Crea una zona de protección absoluta con curación masiva.",
     "ab": "Ritmo Armónico", "ab_s": "Acelera la recarga de discos de apoyo", "ab_l": "Reduce el tiempo de enfriamiento de los discos curativos.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 22, 23]},
    {"id": 3, "name": "Coco", "short": "Coco", "spelling": "Coco Guamrail", "va": "Hiromi Igarashi",
     "intro": "Audaz y carismática, arrolla el campo de batalla a máxima potencia.",
     "skill": "Golpe Propulsor", "skill_s": "Embestida contundente", "skill_l": "Carga contra el enemigo lanzándolo por los aires.",
     "sp": "Explosión Titánica", "sp_s": "Impacto sísmico en área", "sp_l": "Golpea el suelo desatando una onda expansiva devastadora.",
     "ab": "Furia Mecánica", "ab_s": "Aumenta ataque con PS bajos", "ab_l": "Incrementa la potencia de ataque cuando la salud cae por debajo del 30%.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 22, 23, 51, 52]},
    {"id": 4, "name": "Kite", "short": "Kite", "spelling": "Kite", "va": "Kaito Ishikawa",
     "intro": "Maestro de las artes marciales y el engaño, ataca desde las sombras.",
     "skill": "Técnica Ilusoria", "skill_s": "Clon que distrae a rivales", "skill_l": "Deja un señuelo espectral mientras se teletransporta a espaldas del enemigo.",
     "sp": "Danza Sombría", "sp_s": "Ráfaga implacable de golpes", "sp_l": "Ejecuta una serie continua de impactos críticos a los objetivos en rango.",
     "ab": "Agilidad Fantasma", "ab_s": "Evasión mejorada", "ab_l": "Otorga breve invulnerabilidad tras esquivar con éxito.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 51]},
    {"id": 5, "name": "Owlbert", "short": "Owlbert", "spelling": "Owlbert", "va": "Nobuhiko Okamoto",
     "intro": "Estratega táctico que domina el campo con drones autónomos de defensa.",
     "skill": "Dron Centinela", "skill_s": "Despliega torreta aérea", "skill_l": "Coloca un dron que dispara proyectiles energéticos automáticos.",
     "sp": "Cortina de Humo", "sp_s": "Oculta a todo el equipo", "sp_l": "Despliega una pantalla de niebla táctica que anula el rastreo enemigo.",
     "ab": "Radar Táctico", "ab_s": "Detecta enemigos ocultos", "ab_l": "Revela la posición de los rivales en el minimapa para todos los aliados.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 21]},
    {"id": 6, "name": "Pitophy", "short": "Pitophy", "spelling": "Pitophy", "va": "Shizuka Ishigami",
     "intro": "Poder de fuego destructivo con misiles pesados de largo alcance.",
     "skill": "Bombardeo Ígneo", "skill_s": "Lanza cohetes guiados", "skill_l": "Dispara una andanada de misiles teledirigidos hacia el objetivo fijado.",
     "sp": "Lluvia de Misiles", "sp_s": "Bombardeo orbital en zona", "sp_l": "Satura el área objetivo con detonaciones masivas continuas.",
     "ab": "Carga Explosiva", "ab_s": "Discos de ataque potencian quemadura", "ab_l": "Los ataques directos aplican daño continuo de fuego.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 22, 51]},
    {"id": 7, "name": "Grenhawk", "short": "Grenhawk", "spelling": "Grenhawk", "va": "Tomokazu Sugita",
     "intro": "Tanque veterano con escudo impenetrable que lidera el frente de choque.",
     "skill": "Barrera Fortaleza", "skill_s": "Despliega escudo frontal", "skill_l": "Bloquea todo proyectil y reduce el daño frontal recibido.",
     "sp": "Impacto Meteórico", "sp_s": "Embestida con aturdimiento", "sp_l": "Se proyecta hacia el frente arrollando defensas y aturdiendo enemigos.",
     "ab": "Coraza Inquebrantable", "ab_s": "Resistencia a interrupciones", "ab_l": "Previene ser empujado mientras carga o ataca.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 51, 52]},
    {"id": 8, "name": "Anna", "short": "Anna", "spelling": "Anna Starling", "va": "Saori Hayami",
     "intro": "Elegante y letal tiradora con control absoluto del viento y prisiones de aire.",
     "skill": "Prisión Aérea", "skill_s": "Inmoviliza al rival en una esfera de aire", "skill_l": "Atrapa a un rival en un vórtice paralizándolo temporalmente.",
     "sp": "Juicio Celestial", "sp_s": "Ráfagas concentradas de alta potencia", "sp_l": "Dispara ráfagas certeras a distancia con daño masivo.",
     "ab": "Ojo de Halcón", "ab_s": "Mayor rango de fijado", "ab_l": "Incrementa la distancia máxima para apuntar y disparar a los objetivos.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 21, 51, 52]},
    {"id": 9, "name": "Jay", "short": "Jay", "spelling": "Jay", "va": "Hiroyuki Yoshino",
     "intro": "Rebelde y frenético, porta espadas gemelas a una velocidad vertiginosa.",
     "skill": "Espiral Doble", "skill_s": "Ataque giratorio múltiple", "skill_l": "Gira como un huracán cortando a los enemigos a su alrededor.",
     "sp": "Sobrecarga Eléctrica", "sp_s": "Velocidad y daño hiperbólicos", "sp_l": "Electrifica sus espadas ganando un descomunal aumento de velocidad.",
     "ab": "Adrenalina Pura", "ab_s": "Cura tras derrotar rivales", "ab_l": "Restaura una porción de vida al eliminar a un enemigo.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 21, 51]},
    {"id": 10, "name": "Yuyan", "short": "Yuyan", "spelling": "Yuyan", "va": "Koki Uchiyama",
     "intro": "Guerrero disciplinado que canaliza energía mística en cortes afilados.",
     "skill": "Corte Espectral", "skill_s": "Proyectil cortante de largo alcance", "skill_l": "Libera una hoja de energía concentrada que atraviesa formaciones.",
     "sp": "Filo Dragón", "sp_s": "Desata el dragón espiritual", "sp_l": "Invoca la silueta de un dragón celestial que devora el campo enemigo.",
     "ab": "Concentración Serena", "ab_s": "Carga de habilidad especial rápida", "ab_l": "Incrementa la ganancia de medidor especial al no recibir daño.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 21, 23, 51]},
    {"id": 11, "name": "Diatrius", "short": "Diatrius", "spelling": "Diatrius", "va": "Hiroki Yasumoto",
     "intro": "Imponente coloso de garras afiladas y poder cósmico abrumador.",
     "skill": "Garras Abisales", "skill_s": "Zarpazo de energía oscura", "skill_l": "Desgarra el espacio infligiendo daño masivo a corta distancia.",
     "sp": "Furia Devoradora", "sp_s": "Transformación colosal", "sp_l": "Entra en estado de berserker duplicando temporalmente sus defensas.",
     "ab": "Presencia Dominante", "ab_s": "Ralentiza a enemigos cercanos", "ab_l": "Los enemigos en su entorno sufren una reducción de velocidad de vuelo.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 21, 51]},
    {"id": 12, "name": "Buzzy Big", "short": "Buzzy Big", "spelling": "Buzzy Big", "va": "Subaru Kimura",
     "intro": "Pugilista ruidoso y demoledor con puños gigantes de acero.",
     "skill": "Megamartillo", "skill_s": "Golpe demoledor de aturdimiento", "skill_l": "Carga un puñetazo brutal que quiebra guardias enemigas.",
     "sp": "Impacto Sideral", "sp_s": "Atrae y detona en el centro", "sp_l": "Succiona a todos los rivales hacia su posición y desata un uppercut colosal.",
     "ab": "Piel de Acero", "ab_s": "Reducción pasiva de daño", "ab_l": "Reduce permanentemente el daño recibido de todos los ataques directos.",
     "costumes": [1, 2, 3, 4, 5, 6, 7, 22]},
    {"id": 13, "name": "Hitagi", "short": "Hitagi", "spelling": "Hitagi", "va": "Houko Kuwashima",
     "intro": "Espadachina maestra con katana oriental de cortes hiperprecisos.",
     "skill": "Envaine Relámpago", "skill_s": "Contraataque y corte rápido", "skill_l": "Adopta postura de guardia y contraataca instantáneamente si es golpeada.",
     "sp": "Corte de las Cien Sombras", "sp_s": "Aniquilación en área", "sp_l": "Realiza múltiples cortes invisibles a velocidad lumínica.",
     "ab": "Determinación de Acero", "ab_s": "Golpes críticos incrementados", "ab_l": "Aumenta la probabilidad y daño de golpes críticos.",
     "costumes": [1, 2, 3, 4, 7]},
    {"id": 14, "name": "Sid", "short": "Sid", "spelling": "Sid", "va": "Jun Fukushima",
     "intro": "Ingenioso francotirador y pícaro con trucos impredecibles en el aire.",
     "skill": "Trampa Eléctrica", "skill_s": "Coloca minas paralizantes", "skill_l": "Planta trampas invisibles que inmovilizan al rival que las active.",
     "sp": "Disparo Perforante", "sp_s": "Rifle de francotirador letal", "sp_l": "Apunta y dispara un proyectil de alta velocidad que fulmina a larga distancia.",
     "ab": "Puntería Astuta", "ab_s": "Bonus de daño por la espalda", "ab_l": "Inflige daño crítico aumentado al atacar por la espalda.",
     "costumes": [1, 2, 3, 51]}
]

kicker_list = []
kicker_detail_list = []
kicker_costume_list = []
costume_id_counter = 1

costume_names_es = {
    1: "Color estándar",
    2: "Color alternativo 1",
    3: "Color alternativo 2",
    4: "Color alternativo 3",
    5: "Traje de gala",
    6: "Traje urbano",
    7: "Edición especial",
    21: "Traje de festival",
    22: "Traje veraniego",
    23: "Traje invernal",
    51: "Traje legendario",
    52: "Traje de campeonato"
}

for km in kickers_meta:
    kid = km["id"]
    kname = km["name"]
    kicker_list.append({
        "id": kid,
        "name": kname,
        "shortName": km["short"],
        "nameSpelling": km["spelling"],
        "voiceActorName": f"CV: {km['va']}"
    })
    kicker_detail_list.append({
        "id": kid,
        "kickerId": kid,
        "kickerIntroductionText": km["intro"],
        "kickerSkillName": km["skill"],
        "kickerSkillShortText": km["skill_s"],
        "kickerSkillLongText": km["skill_l"],
        "specialSkillName": km["sp"],
        "specialSkillShortText": km["sp_s"],
        "specialSkillLongText": km["sp_l"],
        "kickerAbilityName": km["ab"],
        "kickerAbilityShortText": km["ab_s"],
        "kickerAbilityLongText": km["ab_l"],
        "kickerDiscDistinctionText": "Compatible con discos de combate aéreo y ataque rápido.",
        "kickerGraphHpRate": 0.8,
        "kickerGraphAttackRate": 0.9,
        "kickerGraphSpeedRate": 1.0,
        "age": 18,
        "birthday": "1/1",
        "height": "165cm",
        "profileText": km["intro"]
    })
    for c in km["costumes"]:
        cname = costume_names_es.get(c, f"Variante {c}")
        kicker_costume_list.append({
            "id": costume_id_counter,
            "kickerId": kid,
            "costumeId": c,
            "costumeName": f"{kname} - {cname}",
            "sortOrder": c,
            "battleResultPositionSortOrder": 1,
            "battleResultModelScale": 1.0,
            "exclusiveFlag": False,
            "releaseDatetime": "2019-01-01 00:00:00"
        })
        costume_id_counter += 1

print(f"Generated: {len(kicker_list)} kickers, {len(kicker_costume_list)} costumes, {len(kicker_detail_list)} details")

with open("config/masters_kicker.json", "w", encoding="utf-8") as f:
    json.dump(kicker_list, f, indent=2, ensure_ascii=False)

with open("config/masters_kicker_costume.json", "w", encoding="utf-8") as f:
    json.dump(kicker_costume_list, f, indent=2, ensure_ascii=False)

with open("config/masters_kicker_detail.json", "w", encoding="utf-8") as f:
    json.dump(kicker_detail_list, f, indent=2, ensure_ascii=False)
