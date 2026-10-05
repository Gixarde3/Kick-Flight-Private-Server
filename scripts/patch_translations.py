#!/usr/bin/env python3
"""Patch placeholders and residual untranslated keys in config/masters_translation.json."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANS_FILE = REPO_ROOT / "config/masters_translation.json"

CUSTOM_TRANSLATIONS = {
    "common.rankUpDiscCountDescriptionFormat": "Rank Up Disc Count Description {0}",
    "common.kickerTicket": "Kicker Ticket",
    "common.possession": "Possessed: {0}",
    "common.all": "All",
    "common.pickup": "Pickup",
    "common.enableGetDiscRank": "Rank required: {0}",
    "common.rankFormat": "Rank {0}",
    "common.purchase": "Purchase",
    "common.paidFree": "Paid / Free",
    "common.discForce": "Disc Force",
    "common.secondsAgo": "{0} s ago",
    "common.ability": "Ability",
    "common.show": "Show",
    "common.hide": "Hide",
    "common.on": "On",
    "common.off": "Off",
    "common.sortTypeId": "Sort By ID",
    "common.sortTypeGet": "Sort By Type",
    "common.sortTypeRarity": "Rarity",
    "common.sortTypeLevel": "Lv",
    "common.sortTypeAttack": "ATK",
    "common.sortTypeHp": "HP",
    "common.sortTypeCoolTime": "Cooldown",
    "common.sort": "Sort",
    "common.filter": "Filter",
    "common.filterAll": "All",
    "common.filterOff": "No filter",
    "common.filterOn": "Filtered",
    "common.filterRarity": "Rarity",
    "common.filterAttribute": "Attribute",
    "common.filterSkillType": "Skill Type",
    "attackType.default": "Normal Attack",
    "attackType.skill": "Ability",
    "tutorial.defaultPlayerName": "Pilot",
    "game.crystalDeposite": "Deposit Crystals",
    "disc.set": "Disc",
    "disc.sort": "Sort",
    "disc.drawFreeTitle": "Draw Free Title",
    "disc.nextDropRewardTitleFormat": "Next Drop Reward: {0}",
    "shop.purchaseDiscForce": "Purchase Disc Force",
    "inApp.discLevelUpTitle": "Disc Lv Up",
    "skillActionType.shotAttackDetail": "Guided long-range shot",
    "skillActionType.aroundAttackDetail": "Area of Effect Attack",
    "skillActionType.moveAttackDetail": "Lunging forward attack",
    "skillActionType.frontAttackDetail": "Attack in a short-range in front",
    "inGameTutorial.autoAttackTitle": "Auto Attack",
    "inGameTutorial.autoAttackDescription": "Fly close to a locked-on enemy to attack them automatically.",
    "inGameTutorial.boostDashTitleFormat": "Boost Acceleration",
    "inGameTutorial.boostDashDescription": "Press and hold to accelerate to top speed.",
    "inGameTutorial.boostDashSubDescription": "Boost is consumed while accelerating",
    "inGameTutorial.catchCrystalTitleFormat": "Collect the Crystals!",
    "inGameTutorial.crysrtalUnit": "Crystals",
    "inGameTutorial.catchCrystalSubDescription": "Pass through the floating crystals to collect them.",
    "inGameTutorial.depositCrystalTitle": "Deposit Crystals",
    "inGameTutorial.depositCrystalDescription": "Take the crystals to your team's guardian to deposit points.",
    "inGameTutorial.depositCrystalDescription2": "Deposit crystals before you get taken down.",
    "inGameTutorial.depositCrystalDescription3": "The team with the most crystals when time runs out wins.",
    "inGameTutorial.flipTurnTitleFormat": "Flip Turn",
    "inGameTutorial.turnAvoidTitleFormat": "Dodge",
    "inGameTutorial.underFlickTitleFormat": "Flick Down",
    "inGameTutorial.moveTitleFormat": "Three-Dimensional Flight",
    "inGameTutorial.moveDistanceUnit": "m",
    "inGameTutorial.moveSubDescription": "Swipe to move freely through 3D airspace.",
    "inGameTutorial.hitDiscSkillTitleFormat": "Disc Usage",
    "inGameTutorial.hitDiscSkillDescription": "Slide the equipped disc upward to unleash its ability.",
    "inGameTutorial.hitKickerSkillTitleFormat": "Kicker Skill",
    "inGameTutorial.hitKickerSkillDescription": "Tap the icon to use your Special Skill. ",
    "inGameTutorial.specialSkillTitleFormat": "Special Skill",
    "inGameTutorial.specialSkillDescription": "Tap the Special Ability button when the gauge is full.",
    "inGameTutorial.enemyUserName": "Practice Opponent",
    "inGameTutorial.countDownMessage": "Battle Start!",
    "outGameTutorial.capsule1": "You've obtained a combat capsule!",
    "outGameTutorial.capsule2": "Open capsules to get new discs and Disc Force.",
    "outGameTutorial.growDisc1": "You can level up your discs using Disc Force.",
    "outGameTutorial.growDisc2": "Upgrade the discs to boost your health and attack damage.",
    "outGameTutorial.discGacha1": "Use the disc gacha to expand your collection.",
    "outGameTutorial.discGacha2": "Obtain higher-rarity discs with devastating abilities!",
    "outGameTutorial.discGacha3": "Configure your decks to adapt to each combat mode.",
    "outGameTutorial.kickerScout1": "Recruit new Kickers using Kicker Tickets.",
    "outGameTutorial.changeKicker1": "Switch your kicker based on your favorite playstyle.",
    "outGameTutorial.inputName1": "Enter your name: ",
    "outGameTutorial.inputName2": "You can change your name later in settings.",
    "premium.description": "Kick-Flight Premium Pass",
    "premium.missionDescription": "Exclusive missions with additional daily rewards.",
    "premium.capsuleSlotDescription": "Expanded capsule slots to store more loot at once.",
    "premium.discForceDescription": "50% Disc Force earnings multiplier in all battles.",
    "battleDisconnect.warningTitle": "Disconnected from Battle",
    "battleDisconnect.warningText1": "Leaving a battle in progress hurts your team.",
    "battleDisconnect.warningText2": "Intentional disconnections may result in temporary penalties.",
    "battleDisconnect.penaltyText1": "Battle point penalty applied.",
    "battleDisconnect.penaltyText2": "Please wait a moment before searching for a match again.",
    "battleDisconnect.resultText": "Disconnected from Battle",
    "gacha.discPurchaseConfirm": "Do you wish to confirm your purchase?",
    "gachaDetail.getDiscRank": "Disc Rank {0}",
    "gachaDetail.unlockRank": "Unlock Rank {0}",
    "shop.unlockRankFormat": "Unlocks at {0} Rank",
    "battleSummary.rankFormat": "Rank {0}",
    "battleSummary.usedDiscSkillCount": "Discs used: {0}",
    "battleSummary.usedKickerSkillCount": "Kicker Skills used: {0}",
    "battleSummary.usedSpecialSkillCount": "Special Skills used: {0}",
    "battleSummary.battleCount": "Battle Count {0}",
    "battleSummary.winCount": "Win Count {0}",
    "battleSummary.mvpCount": "MVP: {0}",
    "battleSummary.killCount": "Kill Count {0}",
    "battleSummary.killAssistCount": "Kill Assist Count {0}",
    "battleSummary.movingDistance": "Distance covered: {0} m",
    "battle.backHome": "Return to Home"
}

def main():
    data = json.loads(TRANS_FILE.read_text(encoding="utf-8"))
    updated = 0
    for item in data:
        key = item.get("key", "")
        if key in CUSTOM_TRANSLATIONS:
            item["text"] = CUSTOM_TRANSLATIONS[key]
            updated += 1
        elif item.get("text") == "{0}":
            # Fallback for remaining single {0} placeholders
            item["text"] = f"{key.split('.')[-1].capitalize()}: {{0}}"
            updated += 1

    TRANS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Successfully patched {updated} translations in {TRANS_FILE}")

if __name__ == "__main__":
    main()
