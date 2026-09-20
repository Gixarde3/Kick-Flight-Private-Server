import json

abilities = []
conditions = []
for kid in range(1, 15):
    abilities.append({
        "id": kid,
        "kickerId": kid,
        "triggerType": 1,
        "time": 5.0,
        "value": 1.2,
        "overlapCount": 1
    })
    conditions.append({
        "id": kid,
        "kickerAbilityId": kid,
        "conditionType": 1,
        "duration": 5.0,
        "interval": 1.0,
        "effectValue": 1.2,
        "triggerType": 1,
        "limitCount": 1
    })

with open("config/masters_kicker_ability.json", "w", encoding="utf-8") as f:
    json.dump(abilities, f, indent=2)

with open("config/masters_kicker_ability_condition.json", "w", encoding="utf-8") as f:
    json.dump(conditions, f, indent=2)

print("Generated abilities and conditions")
