#!/usr/bin/env python3
"""Complete config/masters_translation.json with every key the client looks up.

Why: `LocalizeText` / `LocalizeTextMeshPro` components in the UI prefabs and `LocalizeManager.GetText(Enum)`
resolve their text through `MasterManager.TranslationMaster.GetText(key)`; a key that is not in the served
Translation master renders as an EMPTY string. The master we serve was hand-made (536 rows, 300+ of them
"Xxx: {0}" placeholders), so the settings window, most menus and the disc type labels (ATK/TRAP/MOVE/HEAL/BUFF/WARP
= `skillCategoryType.<value>`) came out blank.

Key sources (all merged here):
  * docs/localize_keys.json - the `TranslationInfo._key` of the 1588 LocalizeText components in the APK's UI prefabs
    (extracted from assets/bin/Data/data.unity3d with UnityPy: MonoBehaviours whose m_Script is LocalizeText 268 /
    LocalizeTextMeshPro 544, length-prefixed strings that look like `section.name`);
  * ENUM_KEYS - LocalizeManager.GetText(Enum) builds `<TypeName first-lower>.<ValueName first-lower>` for the 13 enums
    passed to it (PoseDirectionType, PresentListType, SortType, RoleType, MissionListType, GearColorType, ConditionType,
    WeaponType, SkillCategoryType, BattleRuleType, AttackDistanceType, AttackType, AttributeType);
  * code literals of libil2cpp (`section.name` strings in stringliteral.json) whose section already exists in one of
    the two lists above.

Texts: TEXTS below for the screens people actually read (settings, menus, disc types, enum names); everything else
falls back to the key's last segment split into words ("nameEditWarning" -> "Name Edit Warning"), which is also what
replaces the old "Xxx: {0}" placeholders (a `{0}` is kept only when the key says it is a format). Existing real
translations are never touched. Rerun after editing TEXTS:

    python scripts/generate_translations.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "config" / "masters_translation.json"
PREFAB_KEYS = ROOT / "docs" / "localize_keys.json"
LITERALS = ROOT.parent / "Kick-Flight-Assets" / "server_revival_analysis" / "il2cpp" / "stringliteral.json"

ENUM_KEYS = {
    "poseDirectionType": ["Default", "Right", "Left", "Up", "Down"],
    "presentListType": ["None", "Limited", "Unlimited", "History"],
    "sortType": ["Default", "Level", "Rarity", "Attack", "Hp", "Amount", "Get", "KickerCompatibility", "CoolTime"],
    "roleType": ["Speed", "Support", "Attack", "Tank"],
    "missionListType": ["None", "Daily", "Limited", "Badge", "Season", "Festival"],
    "gearColorType": ["Red", "Green", "Yellow", "Blue", "White"],
    "conditionType": ["None", "AttackRate", "SpeedRate", "DefenseRate", "DamageRate", "Poison", "Paralysis", "Burn", "Stun",
                      "Silent", "Drain", "Regeneration", "Inhale", "BlowoffCollider", "Restrainted", "Restraint", "Prison",
                      "Dot", "Smog", "SmogDisturb", "SmogProtection", "Gravity", "Confusion", "PullIn", "Stealth", "Panda",
                      "ShieldForward", "ShieldAll", "AttackSpeedRate", "RocketLauncherTarget", "AutoMove",
                      "BoostHealSpeedRate", "SpecialSkillGaugeRate", "OneShotKiller"],
    "weaponType": ["Sword", "TwoGuns", "Hammer", "ThrowingStar", "Drone", "RocketLauncher", "Gun", "PunchGlove", "Bowgun",
                   "Shield", "Bat", "Nunchaku", "JapaneseSword", "Laser"],
    "skillCategoryType": ["Attack", "Heal", "Buff", "Trap", "Warp", "Move"],
    "battleRuleType": ["Scramble50", "FlagBattle", "BallShoot", "Trial"],
    "attackDistanceType": ["Short", "Long"],
    "attackType": ["WeaponDirect", "WeaponBullet", "Skill", "KickerSkill", "SpecialSkill", "Condition", "TrapSkill",
                   "SummonTrapAttack", "Ability", "DashAttack"],
    "attributeType": ["None", "Fire", "Water", "Wind"],
}

TEXTS = {
    # disc type labels (SkillCategoryTypeExtensions.GetName) and the disc list filter
    "skillCategoryType.attack": "ATK", "skillCategoryType.heal": "HEAL", "skillCategoryType.buff": "BUFF",
    "skillCategoryType.trap": "TRAP", "skillCategoryType.warp": "WARP", "skillCategoryType.move": "MOVE",
    "type.all": "All", "type.attack": "ATK", "type.heal": "HEAL", "type.buff": "BUFF", "type.trap": "TRAP",
    "type.warp": "WARP", "type.move": "MOVE",
    "attackDistanceType.short": "Short range", "attackDistanceType.long": "Long range",
    "roleType.speed": "Speed", "roleType.support": "Support", "roleType.attack": "Attack", "roleType.tank": "Tank",
    "attributeType.none": "None", "attributeType.fire": "Fire", "attributeType.water": "Water", "attributeType.wind": "Wind",
    "weaponType.sword": "Sword", "weaponType.twoGuns": "Twin guns", "weaponType.hammer": "Hammer",
    "weaponType.throwingStar": "Shuriken", "weaponType.drone": "Drone", "weaponType.rocketLauncher": "Rocket launcher",
    "weaponType.gun": "Gun", "weaponType.punchGlove": "Gauntlets", "weaponType.bowgun": "Bowgun", "weaponType.shield": "Shield",
    "weaponType.bat": "Bat", "weaponType.nunchaku": "Nunchaku", "weaponType.japaneseSword": "Katana", "weaponType.laser": "Laser",
    "battleRuleType.scramble50": "Crystal Scramble", "battleRuleType.flagBattle": "Flag Flight",
    "battleRuleType.ballShoot": "Rapid Ball", "battleRuleType.trial": "Trial",
    "sortType.default": "Default", "sortType.level": "Level", "sortType.rarity": "Rarity", "sortType.attack": "ATK",
    "sortType.hp": "HP", "sortType.amount": "Owned", "sortType.get": "Obtained", "sortType.kickerCompatibility": "Kicker match",
    "sortType.coolTime": "Cooldown",
    "sort.switchTitle": "Sort", "sort.displayOrder": "Order", "sort.hp": "HP", "sort.rarity": "Rarity", "sort.amount": "Owned",
    "sort.default": "Default", "sort.attack": "ATK", "sort.level": "Level",
    "filter.title": "Filter", "filter.rarity": "Rarity", "filter.attribute": "Attribute", "filter.type": "Type", "rarity.all": "All",
    "conditionType.poison": "Poison", "conditionType.paralysis": "Paralysis", "conditionType.burn": "Burn",
    "conditionType.stun": "Stun", "conditionType.silent": "Skill seal", "conditionType.regeneration": "Regeneration",
    "conditionType.attackRate": "ATK change", "conditionType.speedRate": "Speed change", "conditionType.damageRate": "Damage cut",
    "conditionType.defenseRate": "DEF change", "conditionType.drain": "Drain", "conditionType.stealth": "Stealth",
    "conditionType.shieldForward": "Front shield", "conditionType.shieldAll": "Shield", "conditionType.confusion": "Confusion",
    "conditionType.prison": "Prison", "conditionType.gravity": "Gravity", "conditionType.inhale": "Vortex",
    "conditionType.oneShotKiller": "One-shot", "conditionType.panda": "Panda", "conditionType.autoMove": "Auto move",
    "conditionType.boostHealSpeedRate": "Boost recovery", "conditionType.specialSkillGaugeRate": "SS gauge",
    "conditionType.attackSpeedRate": "Attack speed",
    "attackType.weaponDirect": "Basic attack", "attackType.weaponBullet": "Basic attack", "attackType.skill": "Disc",
    "attackType.kickerSkill": "Kicker Skill", "attackType.specialSkill": "Special Skill", "attackType.condition": "Status effect",
    "attackType.trapSkill": "Trap", "attackType.summonTrapAttack": "Turret", "attackType.ability": "Passive",
    "attackType.dashAttack": "Dash attack",
    # settings window (OutGameSettingWindow / InGameSettingWindow / Setting*CategoryView)
    "setting.title": "Settings", "setting.battle": "Battle", "setting.graphics": "Graphics", "setting.sound": "Sound",
    "setting.textChat": "Text chat", "setting.execute": "Apply", "setting.exit": "Quit",
    "setting.battleControlDefault": "Default", "setting.battleControlReverse": "Reversed",
    "setting.dominantLeftHand": "Left-handed", "setting.dominantRightHand": "Right-handed",
    "setting.graphicsLow": "Low", "setting.graphicsMiddle": "Medium", "setting.graphicsHigh": "High", "setting.graphicsCustom": "Custom",
    "setting.exitTraining": "Quit training", "setting.exitTrainingTitle": "Quit training?",
    "setting.exitTrial": "Quit trial", "setting.exitTrialTitle": "Quit trial?", "setting.trialSettingTitle": "Trial settings",
    "setting.exitTutorial": "Quit tutorial", "setting.exitTutorialTitle": "Quit tutorial?",
    "setting.exitReplay": "Quit replay", "setting.exitReplayTitle": "Quit replay?",
    "cacheClear.description": "Delete the downloaded game data. It will be downloaded again the next time you play.",
    "common.cacheClear": "Clear cache", "common.language": "Language", "common.languageChangeTitle": "Change language",
    "language.change": "Change language", "languageChangeConfirm.description": "Change the language? The game will restart.",
    "tutorial.graphicSettingDescription": "You can change the graphics quality in Settings.",
    # main menus / common
    "common.menuOtherTitle": "Other", "common.battleMode": "Battle mode", "common.battlePlayerCount": "{0} players",
    "common.start": "Start", "common.playStart": "Play", "common.live": "Live", "common.watching": "Watching",
    "common.watchAr": "AR view", "common.copy": "Copy", "common.search": "Search", "common.sort": "Sort", "common.social": "Social",
    "common.exchange": "Exchange", "common.up": "UP", "common.sum": "Total", "common.stage": "Stage", "common.scout": "Scout",
    "common.agree": "Agree", "common.disagree": "Disagree", "common.termsOfServiceAgree": "I agree to the Terms of Service",
    "common.privacyPolicyAgree": "I agree to the Privacy Policy", "common.paid": "Paid", "common.tweet": "Tweet",
    "common.officialTwitter": "Official Twitter", "common.facebookAuth": "Facebook login", "common.purchaseAlert": "Purchase alert",
    "common.premiumMemberBonus": "Premium bonus", "common.confirmPurchase": "Confirm purchase",
    "common.kickerPurchaseConfirm": "Buy this Kicker?", "common.kickerPurchaseExecute": "Buy",
    "common.notPossession": "Not owned", "common.notPossessDisc": "You do not own this disc",
    "common.possessionableDisk": "Discs you can own", "common.rankUpDiskRelease": "Unlocked at rank up",
    "common.untilHolding": "Held until", "common.monthName": "{0}", "common.yearName": "{0}",
    "common.inputNameDescription": "Enter your name.", "common.nameEditDescription": "Enter a new name.",
    "common.nameEditWarning": "Names that break the rules may be changed.",
    "common.nameChangeRuleDescription": "Up to 10 characters.", "common.nameChangeRuleWarning": "Offensive names are not allowed.",
    "common.idSearchDialogDescription": "Enter a player ID.",
    "disc.swapTitle": "Swap discs", "game.crystalLost": "Crystals lost", "battle.continueBattle": "Continue",
    "result.regularEndRankMessage": "Rank at the end of the season", "boost.empty": "No boost", "trial.title": "Trial",
    "mission.clearMessage": "Mission complete!", "challenge.addReward": "Bonus reward", "badge.set": "Set badge",
    "present.empty": "No presents", "present.limitAttention": "Some presents expire soon", "present.countAttention": "Up to {0} presents",
    "download.downloading": "Downloading...", "download.downloadingAttention": "Please do not close the app while downloading.",
    "download.confirmDescription": "Download the latest game data?", "download.recommendWifi": "A Wi-Fi connection is recommended.",
    "gacha.newDisc": "NEW", "gacha.discSystem": "About discs", "gacha.discFragmentGet": "Disc fragments obtained",
    "gacha.battleRankDiscProvisionRate": "Drop rates", "shop.stampGet": "Stamp obtained",
    "shop.exchangeDiscFragmentEmpty": "No disc fragments", "shop.exchangeDiscFragmentDescription": "Exchange fragments for discs",
    "shop.exchangeDiscFragmentPrecautions": "Fragments cannot be refunded.", "shop.limitAttentionMessage": "Limited-time offer",
    "gear.bonus": "Gear bonus", "gear.bonusDescription": "Same-colour gear grants a bonus.", "gear.setExecute": "Equip",
    "gear.setConfirm": "Equip this gear?", "gear.setPositionTitle": "Choose a slot", "gear.setCostumeTitle": "Choose a costume",
    "gear.analysisExecute": "Analyse", "gear.analysisSet": "Analyse", "gear.analysisDetail": "Analysis details",
    "gear.deleteDescription": "Delete this gear?", "gear.overrideDescription": "Replace the equipped gear?",
    "review.androidButton": "Rate on Google Play", "review.androidMessage1": "Enjoying Kick-Flight?",
    "review.androidMessage2": "A review would help us a lot!", "replay.empty": "No replays",
    "replay.invalidVersionAnnounce": "This replay was recorded with another version.",
}


def words(segment: str) -> str:
    seg = re.sub(r"(Format|Title|Description|Message|Text)$", "", segment) or segment
    parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", seg)
    text = " ".join(parts).strip()
    return (text[:1].upper() + text[1:]) if text else segment


def fallback(key: str) -> str:
    last = key.split(".")[-1]
    text = words(last)
    if last.endswith("Format") or last.endswith("Count"):
        text += " {0}"
    return text


def main() -> None:
    rows = json.loads(MASTER.read_text(encoding="utf-8"))
    by_key = {r["key"]: r for r in rows}
    wanted = set(json.loads(PREFAB_KEYS.read_text(encoding="utf-8")))
    for section, values in ENUM_KEYS.items():
        for v in values:
            wanted.add(f"{section}.{v[:1].lower() + v[1:]}")
    sections = {k.split(".")[0] for k in wanted} | {k.split(".")[0] for k in by_key}
    if LITERALS.exists():
        for lit in (x["value"] for x in json.loads(LITERALS.read_text(encoding="utf-8"))):
            if re.match(r"^[a-z][A-Za-z0-9]*\.[A-Za-z0-9_]+$", lit) and lit.split(".")[0] in sections:
                wanted.add(lit)
    placeholder = re.compile(r"^[A-Z][a-z]*: \{0\}$")
    added = fixed = 0
    next_id = max(r["id"] for r in rows) + 1
    for key in sorted(wanted | set(by_key)):
        if key in by_key:
            row = by_key[key]
            if placeholder.match(row["text"]):
                row["text"] = TEXTS.get(key, fallback(key)); fixed += 1
            elif key in TEXTS and row["text"] != TEXTS[key] and row["text"].lower() == fallback(key).lower():
                row["text"] = TEXTS[key]; fixed += 1
            continue
        row = {"id": next_id, "key": key, "text": TEXTS.get(key, fallback(key))}
        next_id += 1
        rows.append(row); by_key[key] = row; added += 1
    MASTER.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"masters_translation.json: {len(rows)} rows ({added} added, {fixed} placeholders replaced)")


if __name__ == "__main__":
    main()
