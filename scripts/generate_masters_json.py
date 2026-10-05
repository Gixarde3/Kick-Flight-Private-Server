import json

import sys
from pathlib import Path

# All player-visible kicker text lives in translate_real_database.KICKER_PROFILES (English, wiki wording).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from translate_real_database import KICKER_PROFILES

kickers_meta = [
    {"id": 1, "name": "Tsubame", "short": "Tsubame", "spelling": "Tsubame", "va": "Yuma Uchida", "costumes": [1, 2, 3, 4, 5, 6, 7, 22, 23]},
    {"id": 2, "name": "Ruriha", "short": "Ruriha", "spelling": "Ruriha", "va": "Ayane Sakura", "costumes": [1, 2, 3, 4, 5, 6, 7, 22, 23]},
    {"id": 3, "name": "Coco", "short": "Coco", "spelling": "Coco Guamrail", "va": "Hiromi Igarashi", "costumes": [1, 2, 3, 4, 5, 6, 7, 22, 23, 51, 52]},
    {"id": 4, "name": "Kite", "short": "Kite", "spelling": "Kite", "va": "Kaito Ishikawa", "costumes": [1, 2, 3, 4, 5, 6, 7, 51]},
    {"id": 5, "name": "Owlbert", "short": "Owlbert", "spelling": "Owlbert", "va": "Nobuhiko Okamoto", "costumes": [1, 2, 3, 4, 5, 6, 7, 21]},
    {"id": 6, "name": "Pitophy", "short": "Pitophy", "spelling": "Pitophy", "va": "Shizuka Ishigami", "costumes": [1, 2, 3, 4, 5, 6, 7, 22, 51]},
    {"id": 7, "name": "Grenhawk", "short": "Grenhawk", "spelling": "Grenhawk", "va": "Tomokazu Sugita", "costumes": [1, 2, 3, 4, 5, 6, 7, 51, 52]},
    {"id": 8, "name": "Anna", "short": "Anna", "spelling": "Anna Starling", "va": "Saori Hayami", "costumes": [1, 2, 3, 4, 5, 6, 7, 21, 51, 52]},
    {"id": 9, "name": "Jay", "short": "Jay", "spelling": "Jay", "va": "Hiroyuki Yoshino", "costumes": [1, 2, 3, 4, 5, 6, 7, 21, 51]},
    {"id": 10, "name": "Yuyan", "short": "Yuyan", "spelling": "Yuyan", "va": "Koki Uchiyama", "costumes": [1, 2, 3, 4, 5, 6, 7, 21, 23, 51]},
    {"id": 11, "name": "Diatrius", "short": "Diatrius", "spelling": "Diatrius", "va": "Hiroki Yasumoto", "costumes": [1, 2, 3, 4, 5, 6, 7, 21, 51]},
    {"id": 12, "name": "Buzzy Big", "short": "Buzzy Big", "spelling": "Buzzy Big", "va": "Subaru Kimura", "costumes": [1, 2, 3, 4, 5, 6, 7, 22]},
    {"id": 13, "name": "Hitagi", "short": "Hitagi", "spelling": "Hitagi", "va": "Houko Kuwashima", "costumes": [1, 2, 3, 4, 7]},
    {"id": 14, "name": "Sid", "short": "Sid", "spelling": "Sid", "va": "Jun Fukushima", "costumes": [1, 2, 3, 51]}
]

for _km in kickers_meta:
    _p = KICKER_PROFILES[_km["id"]]
    _km.update({
        "intro": _p["profile"],
        "skill": _p["kickerSkillName"], "skill_s": _p["kickerSkillDescription"], "skill_l": _p["kickerSkillDescription"],
        "sp": _p["specialSkillName"], "sp_s": _p["specialSkillDescription"], "sp_l": _p["specialSkillDescription"],
        "ab": _p["abilityName"], "ab_s": _p["abilityDescription"], "ab_l": _p["abilityDescription"],
    })

# KickerCostume rows are keyed by a composite retail id, 2|KK|CC|VV: a class digit, the kicker id, the
# costume number and a variant. The numbering is not ours to choose, because one of those ids is baked
# into the binary: TutorialUtil.KICKER_COSTUME_ID is 2010101, i.e. kicker 1's costume 1, and the client
# resolves every id the server hands it through this same table. A sequential 1..N table (what this
# script used to emit) misses that lookup and throws a NullReferenceException building the home screen,
# which stalls a new account on the loading screen before the tutorial can even ask for a name.
def costume_row_id(kicker_id: int, costume_id: int, variant: int = 1) -> int:
    return 2_000_000 + kicker_id * 10_000 + costume_id * 100 + variant


kicker_list = []
kicker_detail_list = []
kicker_costume_list = []

costume_names = {
    1: "Standard Color",
    2: "Alt Color 1",
    3: "Alt Color 2",
    4: "Alt Color 3",
    5: "Formal Outfit",
    6: "Urban Outfit",
    7: "Special Edition",
    21: "Festival Outfit",
    22: "Summer Outfit",
    23: "Winter Outfit",
    51: "Legendary Outfit",
    52: "Championship Outfit"
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
        "kickerDiscDistinctionText": "Compatible with aerial combat and quick attack discs.",
        # The client fills these gauges with Image.fillAmount = rate / 100, so they are 0..100 percentages, not fractions.
        "kickerGraphHpRate": 80,
        "kickerGraphAttackRate": 90,
        "kickerGraphSpeedRate": 100,
        "age": 18,
        "birthday": "1/1",
        "height": "165cm",
        "profileText": km["intro"]
    })
    for c in km["costumes"]:
        cname = costume_names.get(c, f"Variant {c}")
        kicker_costume_list.append({
            "id": costume_row_id(kid, c),
            "kickerId": kid,
            "costumeId": c,
            "costumeName": f"{kname} - {cname}",
            "sortOrder": c,
            "battleResultPositionSortOrder": 1,
            "battleResultModelScale": 1.0,
            "exclusiveFlag": False,
            "releaseDatetime": "2019-01-01 00:00:00"
        })

print(f"Generated: {len(kicker_list)} kickers, {len(kicker_costume_list)} costumes, {len(kicker_detail_list)} details")

with open("config/masters_kicker.json", "w", encoding="utf-8") as f:
    json.dump(kicker_list, f, indent=2, ensure_ascii=False)

with open("config/masters_kicker_costume.json", "w", encoding="utf-8") as f:
    json.dump(kicker_costume_list, f, indent=2, ensure_ascii=False)

with open("config/masters_kicker_detail.json", "w", encoding="utf-8") as f:
    json.dump(kicker_detail_list, f, indent=2, ensure_ascii=False)

# Two more masters point at a costume, and both are derived from the table above rather than authored by
# hand, so the composite id stays in one place: the lottery drop table has exactly one row per costume,
# and an AI parameter row wears its kicker's first costume. The AI file is otherwise hand-tuned - only
# that one column is written here.
lottery_drop_kicker_list = [
    {
        "id": row["id"],
        "kickerCostumeId": row["id"],
        "dropRatio": 1,
        "pickupFlag": False,
        "sortOrder": index,
        "newFlag": False,
    }
    for index, row in enumerate(kicker_costume_list, start=1)
]

with open("config/masters_lottery_drop_kicker.json", "w", encoding="utf-8") as f:
    json.dump(lottery_drop_kicker_list, f, indent=2, ensure_ascii=False)

with open("config/masters_kicker_ai_parameter.json", encoding="utf-8") as f:
    ai_parameter_list = json.load(f)

for row in ai_parameter_list:
    row["kickerCostumeId"] = costume_row_id(row["kickerId"], 1)

with open("config/masters_kicker_ai_parameter.json", "w", encoding="utf-8") as f:
    json.dump(ai_parameter_list, f, indent=2, ensure_ascii=False)

print(f"Generated: {len(lottery_drop_kicker_list)} lottery drop rows, "
      f"{len(ai_parameter_list)} AI parameter rows rewired to the composite costume ids")
