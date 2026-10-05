#!/usr/bin/env python3
"""Translate the authentic Japanese Kick-Flight master data into English.
Applies real localized names, canonical stats, and comprehensive English lore/skills.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
BRAIN_DIR = Path("/Users/marcochavez/.gemini/antigravity-ide/brain/98d8f949-d5f5-4795-8960-aeb6094cced5")

# 1. DISC NAMES TRANSLATION MAP (Katakana -> Localized / English Name)
DISC_NAME_TRANSLATION = {
    "フレイムザウラー": "Flamezaurer",
    "ガイモス": "Gaimos",
    "レイジコング": "Rage Kong",
    "ウルファング": "Wolfang",
    "ヘルザウラー": "Hellzaurer",
    "フォースティング": "Frost Sting",
    "ラークス": "Larx",
    "イノッシン": "Inoshin",
    "ホエーリア": "Whaleria",
    "ガストル": "Gastor",
    "ファイタガメ": "Fighter Turtle",
    "ボムスター": "Bomb Star",
    "フェアリザード": "Fairy Lizard",
    "ウーバービーバー": "Uber Beaver",
    "バブルスター": "Bubble Star",
    "レッドブラスター": "Red Blaster",
    "エアブラスター": "Air Blaster",
    "ブルーブラスター": "Blue Blaster",
    "ジェットシャーク": "Jet Shark",
    "ラッシュブレイド": "Rush Blade",
    "プロペダイル": "Propedile",
    "ボルケータス": "Volcatus",
    "カゼタチヌ": "Kazetachinu (Rising Wind)",
    "ハナプーゴン": "Hanapoogon",
    "ラピビット": "Lapibit",
    "アームドカリス": "Armed Calis",
    "レオレックス": "Leorex",
    "ゲコダルマ": "Gekodarma",
    "マンタリオン": "Mantalion",
    "アサルトランス": "Assault Lance",
    "バニーバーン": "Bunny Burn",
    "トドロック": "Todorock",
    "ビリリット": "Birilit",
    "ジェットタマゴ": "Jet Tamago",
    "ライノット": "Rhinot",
    "ハタキドラ": "Hatakidora",
    "ヤンチャラ": "Yanchara",
    "ブロックス": "Blox",
    "ジャックアッパー": "Jack Upper",
    "カバンドス": "Kabandos",
    "ジェットハンマー": "Jet Hammer",
    "ヘルムック": "Hellmuck",
    "タイダリオン": "Tidalion",
    "ハカイジュウキ": "Hakaijuki (Bulldozer)",
    "マジマジン": "Majimajin",
    "セレスティア": "Celestia",
    "オクトヴァース": "Octoverse",
    "ガガガガトリン": "Gagagatling",
    "ガトリンウルトラ": "Gatling Ultra",
    "ドラガルム": "Dragarum",
    "フォークシー": "Foxy",
    "ローズミー": "Roseme",
    "アヴァサラム": "Avasalam",
    "ヌタウツボン": "Nutautsubon",
    "シビリードラ": "Sibilydra",
    "ウィザビロコ": "Wizard Biloco",
    "バクリュー": "Bakuryu (Explosive Dragon)",
    "ジャンクバレット": "Junk Bullet",
    "ドクドクバレット": "Poison Bullet",
    "ボムヘビ": "Bomb Snake",
    "メラキランチャー": "Melaki Launcher",
    "スルゥマジン": "Through Majin",
    "ボッシューター": "Box Shooter",
    "ヴァンプキン": "Vampkin",
    "フェニーロラ": "Phenilora",
    "ペガシア": "Pegasia",
    "キュジャック": "Kyujack",
    "ヒルミャン": "Healmyan",
    "キュパルーパー": "Cupalooper",
    "ピコリーフ": "Pico Leaf",
    "ウミガミ": "Umigami (Sea God)",
    "キュアウィー": "Cure Wee",
    "メディカルBOX": "Medical BOX",
    "ナースロイド": "Nursdroid",
    "エネガエル": "Enegaeru",
    "エアガエル": "Airgaeru",
    "パワワンワ": "Powerwanwa",
    "ブーストボトル": "Boost Bottle",
    "ガンコブルド": "Ganko Bulld",
    "チアラウダー": "Cheer Louder",
    "フラッシュバリア": "Flash Barrier",
    "スピュードル": "Spoodle",
    "ファイタガルー": "Fightgaroo",
    "シェルカブト": "Shell Kabuto",
    "テトラシールド": "Tetra Shield",
    "マモリガニ": "Mamorigani (Guardian Crab)",
    "エンカレッジオ": "Encouragio",
    "ポンポコヌシ": "Pompokonushi",
    "スターリオン": "Starlion",
    "ギャラクシールド": "Galaxyshield",
    "アントレイズ": "Antraise",
    "テンクウテイ": "Tenkutei (Celestial Emperor)",
    "イルダ・ルマ": "Ilda Ruma",
    "ワイルディア": "Wildia",
    "ポップキャンディ": "Pop Candy",
    "イザナヒメ": "Izanahime",
    "ブービーボンバー": "Booby Bomber",
    "レッドマイン": "Red Mine",
    "グリーンマイン": "Green Mine",
    "ブルーマイン": "Blue Mine",
    "ハイパーボム": "Hyper Bomb",
    "スタンノヴァ": "Stun Nova",
    "セプタコプター": "Septacopter",
    "レイジブルド": "Rage Bulld",
    "アクトタレット": "Robo Turret",
    "キラービレット": "Killer Billet",
    "ノロマイマイ": "Noromaimai",
    "カモガンガン": "Kamo Gangan",
    "ステルスマイン": "Stealth Mine",
    "イビルクロウ": "Evil Crow",
    "エアロジャマー": "Aero Jammer",
    "リベリオウルフ": "Rebelio Wolf",
    "ハリマンボー": "Harimanbo",
    "ヘルパンプキン": "Hell Pumpkin",
    "ウォーランタン": "War Lantern",
    "アークオルフィン": "Arc Orphin",
    "スタートゲート": "Start Gate",
    "アサシンゲート": "Assassin Gate",
    "サポットロイド": "Supportdroid",
    "キラーセクタ": "Killer Secta",
    "ネオイルミー": "Neo Illumi",
    "プリンシア": "Princia",
    "キズナゲート": "Bond Gate",
    "モモンドラ": "Momondra",
    "モモンボン": "Momonbon",
    "レイター": "Later",
    "ホノウッキー": "Honokki",
    "スカパンクル": "Skapunkle",
    "タイガルガ": "Tigarga",
    "クックロン": "Cookron",
    "マッハオバケ": "Mach Ghost"
}

# 3. KICKER COMPLETE LOCALIZATION (English; skill and ability text is the official wording from
# https://kick-flight.fandom.com/wiki/Category:Characters, except the rows listed in the commit message)
KICKER_PROFILES = {
    1: {
        "name": "Tsubame",
        "cv": "Kaito Ishikawa",
        "profile": "A hot-blooded youth that aims to be the best Kicker ever. Tsubame's earliest memories are of living in the orphanage in which he was raised. The goggles he wears are something he received from a legendary Kicker he admires, and are a key source of his strength. Tsubame's first steps into Kick-Flight were marked by failures to effectively use discs in battle, and he was treated as a washout. But when he puts on his goggles in key moments, his concentration skyrockets as he puts unfathomable hidden talents on display. Ruriha and Owlbert are his childhood friends.",
        "specialSkillName": "Burst Glide",
        "specialSkillDescription": "Movement speed increases 20%. Opponents will be knocked up and take small damage (10 seconds).",
        "kickerSkillName": "Sonic Rush",
        "kickerSkillDescription": "Deals medium slash damage to one enemy in front. Cancels damage reduction of enemy and increases dealt damage.",
        "abilityName": "Accel Charge",
        "abilityDescription": "Dash gauge heal increases by 100% when HP is below 50%."
    },
    2: {
        "name": "Ruriha",
        "cv": "Azumi Waki",
        "profile": "An influencer whose middle name is chic. Precociously fashionable, Ruriha puts all of her energy into her social media presence. As a result, this budding influencer has attracted an incredible number of fans. To further increase her popularity, Ruriha has alighted the Kick-Flight stage. As always, she dons her favorite outfit and strives to ensure that all eyes are on her. She has known Tsubame and Owlbert since childhood.",
        "specialSkillName": "Cure Light Stage",
        "specialSkillDescription": "Regenerates 20% of HP for every 1 second (10 seconds).",
        "kickerSkillName": "Back-Step Shot",
        "kickerSkillDescription": "Quickly moves backwards from recoil while dealing small paralysis damage to one enemy in front.",
        "abilityName": "#neversurrender",
        "abilityDescription": "Damage taken reduced by 40% when HEAL type Disc Skill is used. (3 seconds)"
    },
    3: {
        "name": "Coco",
        "cv": "Yuki Kuwahara",
        "profile": "The daughter of the weapons maker, Guamrail Co. As the youngest child doted upon by her parents and two older brothers, Coco knows little about the harsh realities of life. That naivety is often reflected in the preposterous things that come out of her mouth. Coco has joined Kick-Flight to become a billboard for Guamrail Co. and help improve its flagging sales. Having been around weapons her whole life, she is incredibly knowledgeable about and adept at using them in her battles, attracting attention as a rising star amongst the younger Kickers.",
        "specialSkillName": "Coco Swing Tornado",
        "specialSkillDescription": "Whips up a giant tornado to draw in opponents and slams them down, dealing large damage.",
        "kickerSkillName": "Shock Dive",
        "kickerSkillDescription": "Jumps forward and delivers a slam ranged attack. Inflicts medium damage to nearby opponents.",
        "abilityName": "Coco Rhythm",
        "abilityDescription": "Damage afflicted by attacking enemy reduced by 40% (2 seconds)."
    },
    4: {
        "name": "Kite",
        "cv": "Kouki Uchiyama",
        "profile": "A youth that hails from a ninja village, their future resting on his shoulders. Kite's goal is to bring a second wind to ninja work, which has been left behind in the modern era. Washing his hands of the older generation set in their ways, he overcame much resistance to stand in the Kick-Flight arena. His physical ability together with the Infinite Style handed down in his family for generations past, has set him aside as a Kicker to watch. Though they're always at loggerheads, Tsubame's occasional flashes of potential ensure that Kite keeps him in his sights.",
        "specialSkillName": "Wind-Fanged Throwing Star",
        "specialSkillDescription": "An arcane infinite-style attack that delivers a single devastating frontal blow.",
        "kickerSkillName": "Art of Illusion",
        "kickerSkillDescription": "Creates a substitute on the spot and warps forward.",
        "abilityName": "Mystery Moment",
        "abilityDescription": "Perform Perfect Evade to remove cooldown for \"Art of Illusion\"."
    },
    5: {
        "name": "Owlbert",
        "cv": "Mutsumi Tamura",
        "profile": "A young, genius inventor. Influenced by his grandfather, Owlbert has grown up creating new devices all on his own. Unlike the other participants, Owlbert participates in Kick-Flight not for his own glory, but rather to keep creating new inventions and keep improving his existing devices. When focused on his research, he loses sight of everything else around him. Whenever he completes a new invention, Owlbert shows it to his childhood friends, Tsubame and Ruriha.",
        "specialSkillName": "Formation Cloud",
        "specialSkillDescription": "Deploys drone that emits smoke screen for all allies, making them untargetable. (15 seconds).",
        "kickerSkillName": "Hacking Drone",
        "kickerSkillDescription": "Deploys drone that on contact with an enemy, suppressing skills (10 seconds).",
        "abilityName": "Trap Theory",
        "abilityDescription": "With each use of TRAP-type Disc Skills, damage increases by 7.5% ( up to 75% ) and effect duration increases by 5.0%. (up to 50%)."
    },
    6: {
        "name": "Pitophy",
        "cv": "Miku Ito",
        "profile": "A master treasure hunter that's both agile and resourceful. With earnings as a treasure hunter falling, Pitophy throws his hat into the Kick-Flight ring both for the prize money and also to make a name for himself. Having been abandoned in the slums where he fought to eke out a meager existence, he is obsessed with money and the idea of living a life of luxury. Pitophy's charming appearance belies a rash temper - in particular, pat his head and you'll see him erupt with fury. He also thinks of Diatrius as his henchman, though this is one-sided.",
        "specialSkillName": "Missile Party",
        "specialSkillDescription": "Launches 12 small-damage guided missiles forward.",
        "kickerSkillName": "Reverse Joker",
        "kickerSkillDescription": "Dashes forward a short distance from recoil while dealing small damage to an enemy behind.",
        "abilityName": "Damage Raiser",
        "abilityDescription": "Dealt damage increases 15% each time you take an opponent out, but resets when you are killed."
    },
    7: {
        "name": "Grenhawk",
        "cv": "Hiroki Yasumoto",
        "profile": "Combat pro whose Kicker Skill slows down opponents, while his Special Skill increases movement and attack speed of allies.",
        "specialSkillName": "Operation Wing",
        "specialSkillDescription": "Increases movement speed by 30% and attack speed by 30% for all allies (12 seconds).",
        "kickerSkillName": "Slow Shot",
        "kickerSkillDescription": "Deals small damage to one enemy in front and reduces movement speed temporarily.",
        "abilityName": "Battlefield Memories",
        "abilityDescription": "Attack increases by 30% when HP falls below 50%."
    },
    8: {
        "name": "Anna",
        "cv": "Shizuka Ito",
        "profile": "An outstanding police officer with a brilliant mind. Specially trained from a young age, Anna has top-class marksmanship and hand-to-hand combat skills. On the flip side, her sense of justice and responsibility is so strong that failure really gets her down. Anna takes part in Kick-Flight under orders from the top brass, who have instructed her to secretly investigate any suspicious activity related to the matches. Annoyed at Jay's interference with her investigations, she now views his questionable words and actions with suspicion.",
        "specialSkillName": "Aeroprison",
        "specialSkillDescription": "Creates a cage that detains the whole opponent team, blocking them from making any move. (5 seconds)",
        "kickerSkillName": "Binding Ray",
        "kickerSkillDescription": "Restrains enemy & deals small continuous damage while player is still. (3 seconds)",
        "abilityName": "Star Chaser",
        "abilityDescription": "Movement speed increases by 20% while locked on to opponents."
    },
    9: {
        "name": "Jay",
        "cv": "Hiroyuki Yoshino",
        "profile": "A backstreet punk who sees the world as an uninteresting place he should change and make more amusing. Jay gets carried away easily and doesn't come across as being particularly smart, but that's precisely where his aesthetic lies. And now, Jay has set his sights on Kick-Flight, which has grown in popularity worldwide. No one will be able to stop him if he takes this contest - and thus the world - by storm. Having fallen for Anna at first sight, he tags along behind her, utterly unconcerned about her cold attitude towards him.",
        "specialSkillName": "Halcynation Graffiti",
        "specialSkillDescription": "Disguises battle and map information for the opposing team (12 seconds).",
        "kickerSkillName": "Stealth Paint",
        "kickerSkillDescription": "Disappear from mini map and field and become untargetable (4 seconds).",
        "abilityName": "Present 4 U",
        "abilityDescription": "On death, sets a massive damage bomb trap that knocks away nearby opponents. (2 seconds)"
    },
    10: {
        "name": "Yuyan",
        "cv": "Yu Kobayashi",
        "profile": "The tomboyish daughter of the master of a Kung Fu School. Yuyan was raised and trained deep in the mountains, secluded from the rest of society. But the lure of that prohibited, unknown world only grew with each passing day. Unable to suppress that curiosity, Yuyan secretly ventured out one day, and became captivated with Kick-Flight. After an entire month, she finally managed to obtain permission to participate. Now, with her trusted friend, Fei Fei, by her side, Yuyan sets her sights on victory.",
        "specialSkillName": "Panda Rush",
        "specialSkillDescription": "Temporary automatic high-speed movement with x3 attack speed increase. (12 seconds)",
        "kickerSkillName": "Nunchaku Nirvana",
        "kickerSkillDescription": "Nunchaku deals damage to one enemy in the front and forcibly draws them to you.",
        "abilityName": "God Combo Strike",
        "abilityDescription": "Normal attack increases by 10% each time one hits (1 seconds, max 50%)."
    },
    11: {
        "name": "Diatrius",
        "cv": "Tetsu Inada",
        "profile": "An alien hailing from a planet with a more advanced civilization. Diatrius crash-landed on Earth after encountering engine trouble as he was travelling through space. When he regained consciousness, he found himself under the control of an organization scheming to use him for scientific advancement. In order to find a way back home, Diatrius agrees to participate in Kick-Flight based on an offer to supply him with the necessary fuel if he becomes the champion. He considers Pitophy, who shows some kind of interest in him, to be his only friend on Earth.",
        "specialSkillName": "Mega Graviton",
        "specialSkillDescription": "Generates a gravity well that pulls in all opponents in the area and holds them in place.",
        "kickerSkillName": "Meteor Impact",
        "kickerSkillDescription": "Dashes forward at high speed and slams into the target, dealing large damage and knocking it back.",
        "abilityName": "Boot Nanomachine",
        "abilityDescription": "If HP falls below 50%, HP recovers 5% every 1 seconds."
    },
    12: {
        "name": "Buzzy Big",
        "cv": "Subaru Kimura",
        "profile": "A singing, dancing and flying MC Kicker. Optimistic and easy-going, Buzzy Big is the mood maker wherever he goes, and he also cares a great deal about his friends. One day, frustrated by the seemingly meaningless life he was leading, Buzzy Big came across a rapper whose performance changed his life. Now a rapper himself, he participates in Kick-Flight for both the popularity and the prize money, so that he can achieve his dream of performing on the biggest stage in the world. He can often be found busking in between his Kick-Flight matches.",
        "specialSkillName": "Crew Protection",
        "specialSkillDescription": "Deploys a barrier that absorbs damage dealt to all teammates in a wide area.",
        "kickerSkillName": "Front Barrier",
        "kickerSkillDescription": "Deploys an energy barrier in front that blocks projectiles and pushes back opponents that collide with it.",
        "abilityName": "B.B. in da House",
        "abilityDescription": "On death, deploys a one-time barrier that blocks any damage to all teammates."
    },
    13: {
        "name": "Hitagi",
        "cv": "Rika Tachibana",
        "profile": "The young daughter of a distinguished, noble family, who has escaped from her filial duties. Weary of her strict upbringing as the heir, Hitagi ran away from home and was taken in by a group of hooligans. The group's demon crest is a well-known symbol in the territory they control, and also the target of many an envious rival. In order to repay her new family, Hitagi aims for victory in Kick-Flight, so that she can increase the group's authority and influence. Secretly, she also longs to be praised by the leader who took her in.",
        "specialSkillName": "Demon God Marionette",
        "specialSkillDescription": "Releases the power of a demon to turn a normal attack on an opponent into a lethal strike. (15 seconds)",
        "kickerSkillName": "Demonic Shadow",
        "kickerSkillDescription": "Move instantaneously behind targeted opponent. (If there is no target, you'll move forward instead)",
        "abilityName": "Demonic Reincarnation",
        "abilityDescription": "Cooldown for her Kicker Skill Demonic Shadow shortens with each kill."
    },
    14: {
        "name": "Sid",
        "cv": "Tomokazu Sugita",
        "profile": "A street sculptor who does guerrilla art activities under the moniker of Azumaya. A mysterious personage whose background and age are unknown. With his beloved laser gun, Sid goes around creating works of art using pillars and trees he finds on the streets. This \"destruction\" sees him regarded as a delinquent, but none have ever seen his enigmatic figure, leaving the cops no course for response. His reasons for participating in Kick-Flight are unclear. In fact, no one knows that the sculptor that has joined the competition is the delinquent in question.",
        "specialSkillName": "Engraving Laser",
        "specialSkillDescription": "Continuously fires a wall-piercing laser over a wide area in front, damage (small) and paralysis.",
        "kickerSkillName": "Sculpt Make",
        "kickerSkillDescription": "Sets a sculpture that absorbs attacks from Guardians, and turrets and bombs created with discs (6 seconds).",
        "abilityName": "Artistic High",
        "abilityDescription": "Each successful normal attack against an opponent reduces Kicker Skill Cooldown by 1 second & attack speed increased by 100% while kicker skill is activated."
    }
}


def main():
    print("Loading raw Japanese masters and translating to English...")

    # 1. Update config/masters_disc.json
    discs_file = CONFIG_DIR / "masters_disc.json"
    with open(discs_file, encoding="utf-8") as f:
        discs = json.load(f)

    discs_translated = 0
    for d in discs:
        orig_name = d.get("name", "")
        if orig_name in DISC_NAME_TRANSLATION:
            d["name"] = DISC_NAME_TRANSLATION[orig_name]
            discs_translated += 1

    with open(discs_file, "w", encoding="utf-8") as f:
        json.dump(discs, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Updated {discs_translated}/{len(discs)} disc names in {discs_file}")

    # 2. masters_skill.json descriptions are English and owned by apply_disc_cards.py / generate_combat_masters.py.

    # 3. Update config/masters_kicker.json
    kicker_file = CONFIG_DIR / "masters_kicker.json"
    with open(kicker_file, encoding="utf-8") as f:
        kickers = json.load(f)

    for k in kickers:
        kid = k.get("id")
        if kid in KICKER_PROFILES:
            info = KICKER_PROFILES[kid]
            k["name"] = info["name"]
            k["cv"] = info["cv"]

    with open(kicker_file, "w", encoding="utf-8") as f:
        json.dump(kickers, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Updated {len(kickers)} kickers in {kicker_file}")

    # 4. Update config/masters_kicker_detail.json
    detail_file = CONFIG_DIR / "masters_kicker_detail.json"
    with open(detail_file, encoding="utf-8") as f:
        details = json.load(f)

    for d in details:
        kid = d.get("id")
        if kid in KICKER_PROFILES:
            info = KICKER_PROFILES[kid]
            d["kickerIntroductionText"] = info["profile"]
            d["profileText"] = info["profile"]
            d["profile"] = info["profile"]
            d["specialSkillName"] = info["specialSkillName"]
            d["specialSkillShortText"] = info["specialSkillDescription"]
            d["specialSkillLongText"] = info["specialSkillDescription"]
            d["specialSkillDescription"] = info["specialSkillDescription"]
            d["kickerSkillName"] = info["kickerSkillName"]
            d["kickerSkillShortText"] = info["kickerSkillDescription"]
            d["kickerSkillLongText"] = info["kickerSkillDescription"]
            d["kickerSkillDescription"] = info["kickerSkillDescription"]
            d["kickerAbilityName"] = info["abilityName"]
            d["kickerAbilityShortText"] = info["abilityDescription"]
            d["kickerAbilityLongText"] = info["abilityDescription"]
            d["abilityName"] = info["abilityName"]
            d["abilityDescription"] = info["abilityDescription"]

    with open(detail_file, "w", encoding="utf-8") as f:
        json.dump(details, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Updated {len(details)} kicker details in {detail_file}")

    print("Translation complete!")

if __name__ == "__main__":
    main()
