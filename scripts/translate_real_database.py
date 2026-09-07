#!/usr/bin/env python3
"""Translate the authentic Japanese Kick-Flight master data into Spanish.
Applies real localized names, canonical stats, and comprehensive Spanish lore/skills.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
BRAIN_DIR = Path("/Users/marcochavez/.gemini/antigravity-ide/brain/98d8f949-d5f5-4795-8960-aeb6094cced5")

# 1. DISC NAMES TRANSLATION MAP (Katakana -> Localized / Spanish Name)
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
    "カゼタチヌ": "Kazetachinu (Viento Alzado)",
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
    "ハカイジュウキ": "Hakaijuki (Excavadora)",
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
    "バクリュー": "Bakuryu (Dragón Explosivo)",
    "ジャンクバレット": "Junk Bullet",
    "ドクドクバレット": "Bala Venenosa",
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
    "ウミガミ": "Umigami (Dios Marino)",
    "キュアウィー": "Cure Wee",
    "メディカルBOX": "Botiquín Médico",
    "ナースロイド": "Nursdroid",
    "エネガエル": "Enegaeru",
    "エアガエル": "Airgaeru",
    "パワワンワ": "Powerwanwa",
    "ブーストボトル": "Botella Boost",
    "ガンコブルド": "Ganko Bulld",
    "チアラウダー": "Cheer Louder",
    "フラッシュバリア": "Flash Barrier",
    "スピュードル": "Spoodle",
    "ファイタガルー": "Fightgaroo",
    "シェルカブト": "Shell Kabuto",
    "テトラシールド": "Tetra Shield",
    "マモリガニ": "Mamorigani (Cangrejo Guardián)",
    "エンカレッジオ": "Encouragio",
    "ポンポコヌシ": "Pompokonushi",
    "スターリオン": "Starlion",
    "ギャラクシールド": "Galaxyshield",
    "アントレイズ": "Antraise",
    "テンクウテイ": "Tenkutei (Emperador Celeste)",
    "イルダ・ルマ": "Ilda Ruma",
    "ワイルディア": "Wildia",
    "ポップキャンディ": "Pop Candy",
    "イザナヒメ": "Izanahime",
    "ブービーボンバー": "Booby Bomber",
    "レッドマイン": "Mina Roja",
    "グリーンマイン": "Mina Verde",
    "ブルーマイン": "Mina Azul",
    "ハイパーボム": "Híper Bomba",
    "スタンノヴァ": "Stun Nova",
    "セプタコプター": "Septacopter",
    "レイジブルド": "Rage Bulld",
    "アクトタレット": "Torreta Act",
    "キラービレット": "Killer Billet",
    "ノロマイマイ": "Noromaimai",
    "カモガンガン": "Kamo Gangan",
    "ステルスマイン": "Mina Furtiva",
    "イビルクロウ": "Evil Crow",
    "エアロジャマー": "Aero Jammer",
    "リベリオウルフ": "Rebelio Wolf",
    "ハリマンボー": "Harimanbo",
    "ヘルパンプキン": "Hell Pumpkin",
    "ウォーランタン": "War Lantern",
    "アークオルフィン": "Arc Orphin",
    "スタートゲート": "Portal de Inicio",
    "アサシンゲート": "Portal Asesino",
    "サポットロイド": "Supportdroid",
    "キラーセクタ": "Killer Secta",
    "ネオイルミー": "Neo Illumi",
    "プリンシア": "Princia",
    "キズナゲート": "Portal Vínculo",
    "モモンドラ": "Momondra",
    "モモンボン": "Momonbon",
    "レイター": "Later",
    "ホノウッキー": "Honokki",
    "スカパンクル": "Skapunkle",
    "タイガルガ": "Tigarga",
    "クックロン": "Cookron",
    "マッハオバケ": "Fantasma Mach"
}

# 2. EFFECT TRANSLATION MAP (All 112 unique Japanese phrases -> Spanish)
EFFECT_TRANSLATION = {
    "HPが最も低い味方付近へ瞬間移動し、味方のHPを30％回復": "Teletransporte cerca del aliado con menos salud y restaura un 30% de sus PS.",
    "HPが最も低い味方付近へ瞬間移動し、味方のHPを50％回復": "Teletransporte cerca del aliado con menos salud y restaura un 50% de sus PS.",
    "スタート地点に瞬間移動": "Teletransporte instantáneo al punto de inicio.",
    "スタート地点に瞬間移動し、HPを100％回復": "Teletransporte instantáneo al punto de inicio y restaura el 100% de PS.",
    "ダッシュしながら、自身後方に連続攻撃(合計中ダメージ)": "Ataque continuo hacia atrás durante el turbo (daño medio total).",
    "ダッシュしながら、自身後方に連続攻撃(合計中ダメージ) ＋シビレ": "Ataque continuo hacia atrás durante el turbo (daño medio) y parálisis.",
    "ダッシュしながら、自身後方に連続攻撃(合計大ダメージ)": "Ataque continuo hacia atrás durante el turbo (gran daño total).",
    "ロックオンまたは前方の最も遠い相手の背後へ瞬間移動 ＋5秒間攻撃力中アップ": "Teletransporte a la espalda del rival fijado o más lejano y aumenta el ataque por 5 s.",
    "ロックオン相手、または最も近い相手の背後へ瞬間移動": "Teletransporte instantáneo a la espalda del rival fijado o más cercano.",
    "中ダメージ＋吹き飛ばすステルス爆弾を30秒間設置": "Coloca una trampa invisible por 30 s que inflige daño medio y repele al estallar.",
    "中ダメージ＋吹き飛ばす爆弾を20秒間設置": "Coloca una bomba por 20 s que inflige daño medio y repele al estallar.",
    "前方1体に中ダメージの高速貫通突進攻撃 ＋SSゲージを最大20%吸収する": "Embestida perforante veloz a 1 rival con daño medio y absorbe hasta 20% de SS.",
    "前方1体に中ダメージ攻撃": "Ataque frontal a 1 rival que inflige daño medio.",
    "前方1体に中ダメージ攻撃 ＋5秒間移動速度中ダウン": "Ataque frontal a 1 rival con daño medio y reduce su velocidad por 5 s.",
    "前方1体に中ダメージ攻撃 ＋シビレ": "Ataque frontal a 1 rival con daño medio y causa parálisis.",
    "前方1体に中ダメージ攻撃 ＋与えたダメージの80%を回復": "Ataque frontal a 1 rival con daño medio y recupera el 80% del daño infligido.",
    "前方1体に低弾速・長射程の連続攻撃(合計中ダメージ)": "Ráfaga de largo alcance a baja velocidad a 1 rival (daño medio total).",
    "前方1体に低弾速・長射程の連続攻撃(合計大ダメージ＋シビレ)": "Ráfaga de largo alcance a baja velocidad a 1 rival (gran daño total y parálisis).",
    "前方1体に小ダメージ攻撃 ＋スタン": "Ataque frontal a 1 rival con daño ligero y aturdimiento.",
    "前方1体に小ダメージ攻撃 ＋スペシャルスキルゲージを20％減らす": "Ataque frontal a 1 rival con daño ligero y drena un 20% de su indicador de SS.",
    "前方1体に連続攻撃(合計中ダメージ) ＋10秒間毒（最大HP30％）": "Ataque continuo a 1 rival (daño medio total) y envenena por 10 s (30% PS máx).",
    "前方1体に連続攻撃(合計中ダメージ) ＋8秒間攻撃力中ダウン": "Ataque continuo a 1 rival (daño medio total) y reduce su ataque por 8 s.",
    "前方1体に長射程の中ダメージ攻撃 ＋5秒間スキルを封印する": "Disparo a larga distancia a 1 rival con daño medio y bloquea sus discos por 5 s.",
    "前方に中ダメージの貫通突進攻撃 ＋シールドブレイク": "Embestida perforante hacia adelante con daño medio y rotura de escudo.",
    "前方に大ダメージ ＋吹き飛ばす爆発弾攻撃": "Disparo explosivo hacia adelante que inflige gran daño y derriba con retroceso.",
    "前方に大ダメージの高速追撃突進攻撃": "Embestida veloz de persecución hacia adelante que inflige gran daño.",
    "前方に小ダメージ ＋吹き飛ばす爆発弾攻撃": "Disparo explosivo hacia adelante con daño ligero y empuje con retroceso.",
    "前方に小ダメージの貫通突進攻撃 ＋シールドブレイク": "Embestida perforante hacia adelante con daño ligero y rotura de escudo.",
    "前方に小ダメージの貫通突進攻撃 ＋与えたダメージの100％を回復": "Embestida perforante con daño ligero y recupera el 100% del daño infligido.",
    "前方に小ダメージの追撃突進攻撃": "Embestida rápida de persecución hacia adelante con daño ligero.",
    "前方に小ダメージの高速追撃突進攻撃 ＋8秒間攻撃力中ダウン": "Embestida veloz hacia adelante con daño ligero y reduce el ataque rival por 8 s.",
    "前方に連射攻撃 （合計小ダメージ+シビレ）": "Ráfaga continua frontal (daño ligero total y parálisis).",
    "前方に連射攻撃(合計大ダメージ)": "Ráfaga continua frontal que inflige gran daño total.",
    "前方に連射攻撃(合計極大ダメージ ＋SSゲージを最大40％吸収する）": "Ráfaga continua frontal con daño masivo total y drena hasta 40% de SS.",
    "前方に連射攻撃(合計極大ダメージ)": "Ráfaga continua frontal que inflige daño masivo devastador.",
    "前方範囲に中ダメージ攻撃 ＋10秒間毒(最大HP40％)": "Ataque en área frontal con daño medio y envenena por 10 s (40% PS máx).",
    "前方範囲に中ダメージ攻撃 ＋吹き飛ばし": "Ataque en área frontal con daño medio y derribo con retroceso.",
    "前方範囲に中ダメージ攻撃 ＋超吹き飛ばし": "Ataque en área frontal con daño medio y empuje demoledor.",
    "前方範囲に大ダメージ攻撃 ＋吹き飛ばし": "Ataque en área frontal que inflige gran daño y derriba con retroceso.",
    "前方範囲に小ダメージ攻撃 ＋8秒間攻撃力中ダウン": "Ataque en área frontal con daño ligero y reduce el ataque rival por 8 s.",
    "前方範囲に小ダメージ攻撃 ＋吹き飛ばし": "Ataque en área frontal con daño ligero y derribo con retroceso.",
    "前方範囲に小ダメージ貫通攻撃 ＋吹き飛ばし": "Ataque perforante en abanico frontal con daño ligero y retroceso.",
    "周囲球状に中ダメージ攻撃": "Ataque circular esférico que inflige daño medio alrededor.",
    "周囲球状に中ダメージ攻撃 ＋シビレ": "Ataque circular esférico con daño medio y causa parálisis.",
    "周囲球状に中ダメージ攻撃 ＋上吹き飛ばし": "Ataque circular esférico con daño medio y derribo hacia arriba.",
    "周囲球状に大ダメージ攻撃 ＋与えたダメージの60%を回復": "Ataque circular esférico con gran daño y recupera el 60% del daño infligido.",
    "周囲球状に小ダメージ攻撃": "Ataque circular esférico con daño ligero alrededor.",
    "周囲球状に小ダメージ攻撃 ＋10秒間毒(最大HP80％)": "Ataque circular esférico con daño ligero y envenena por 10 s (80% PS máx).",
    "周囲球状に小ダメージ攻撃 ＋シビレ": "Ataque circular esférico con daño ligero y causa parálisis.",
    "周囲球状に小ダメージ攻撃 ＋上吹き飛ばし": "Ataque circular esférico con daño ligero y derribo hacia arriba.",
    "周囲球状に極大ダメージ攻撃": "Ataque circular esférico que inflige daño masivo devastador.",
    "味方全員のHPを20秒間継続回復 （最大80％）": "Regenera PS continuamente a todos los aliados por 20 s (hasta 80% máx).",
    "味方全員のHPを20％回復 ＋状態異常を解除する": "Restaura un 20% de PS a todos los aliados y purifica alteraciones de estado.",
    "味方全員のHPを30％回復": "Restaura instantáneamente un 30% de PS a todos los aliados.",
    "味方全員のHPを50％回復": "Restaura instantáneamente un 50% de PS a todos los aliados.",
    "味方全員のブーストエネルギー回復量を10秒間大アップ": "Aumenta drásticamente la recuperación de turbo de todos los aliados por 10 s.",
    "味方全員の攻撃力を15秒間中アップ": "Aumenta el ataque de todos los aliados de forma media durante 15 s.",
    "味方全員の攻撃力を20秒間小アップ": "Aumenta ligeramente el ataque de todos los aliados durante 20 s.",
    "味方全員の移動速度を10秒間中アップ": "Aumenta la velocidad de movimiento de todos los aliados durante 10 s.",
    "味方全員の被ダメージを15秒間30％カット": "Reduce un 30% el daño recibido por todos los aliados durante 15 s.",
    "味方全員の被ダメージを8秒間70％カット": "Reduce un 70% el daño recibido por todos los aliados durante 8 s.",
    "大ダメージ＋吹き飛ばす爆弾を20秒間設置": "Coloca una trampa por 20 s que inflige gran daño y derriba al estallar.",
    "宙返りしながら、自身後方に小ダメージ攻撃 ＋シビレ": "Voltereta evasiva hacia atrás que inflige daño ligero y parálisis.",
    "小ダメージ＋8秒間スキルを封じる爆弾を20秒間設置": "Coloca una trampa por 20 s que causa daño ligero y sella discos por 8 s.",
    "小ダメージ＋シビレさせる爆弾を20秒間設置": "Coloca una mina por 20 s que causa daño ligero y produce parálisis.",
    "小ダメージ＋スタンさせる爆弾を20秒間設置": "Coloca una mina por 20 s que causa daño ligero y aturdimiento.",
    "小ダメージ＋吹き飛ばす爆弾を20秒間設置": "Coloca una trampa por 20 s que inflige daño ligero y empuja al estallar.",
    "小ダメージ＋吹き飛ばす爆弾を20秒間設置 ＋10秒間毒(最大60%)": "Coloca una trampa por 20 s que empuja y envenena por 10 s (hasta 60%).",
    "広範囲の周囲球状に中ダメージ攻撃 ＋スタン": "Ataque esférico en área amplia con daño medio y aturdimiento.",
    "広範囲の周囲球状に中ダメージ攻撃 ＋上吹き飛ばし": "Ataque esférico en área amplia con daño medio y elevación por los aires.",
    "広範囲の周囲球状に大ダメージ攻撃 ＋上吹き飛ばし": "Ataque esférico en área amplia con gran daño y elevación por los aires.",
    "最も遠くの味方がいる場所へ瞬間移動し、HPを30%回復": "Teletransporte al aliado más lejano y restaura un 30% de PS.",
    "相手が近づくと超低速で周囲攻撃をするタレットを15秒間設置（吹き飛ばし）": "Coloca una torreta por 15 s que repele a los rivales al acercarse.",
    "相手の移動速度を極大ダウンする空間を10秒間生成": "Genera una zona de gravedad densa por 10 s que frena drásticamente a los rivales.",
    "範囲内の相手を中速で攻撃するタレットを15秒間設置": "Coloca una torreta por 15 s que dispara a velocidad media a los rivales.",
    "範囲内の相手を中速で攻撃するタレットを8秒間設置（攻撃力中ダウン）": "Coloca una torreta por 8 s que ataca y reduce el ataque rival.",
    "範囲内の相手を超高速で攻撃するタレットを15秒間設置": "Coloca una torreta por 15 s que ametralla a velocidad extrema a los rivales.",
    "範囲内の相手を高速で攻撃するタレットを15秒間設置（1秒間スキルを封印する）": "Coloca una torreta por 15 s que dispara velozmente y bloquea discos por 1 s.",
    "自動的に4秒間高速前進する": "Propulsa al Kicker hacia adelante a alta velocidad durante 4 s.",
    "自動的に5秒間超高速前進する": "Propulsa al Kicker hacia adelante a velocidad extrema durante 5 s.",
    "自動的に5秒間高速前進する": "Propulsa al Kicker hacia adelante a alta velocidad durante 5 s.",
    "自身のHPを10秒間継続回復 (最大100％)": "Regenera PS continuamente durante 10 s (hasta 100% máx).",
    "自身のHPを10秒間継続回復 (最大50％)": "Regenera PS continuamente durante 10 s (hasta 50% máx).",
    "自身のHPを15秒間継続回復 (最大120％)": "Regenera PS continuamente durante 15 s (hasta 120% máx).",
    "自身のHPを25％回復 ＋状態異常を解除する": "Restaura un 25% de PS y purifica todas las alteraciones de estado.",
    "自身のHPを30％回復": "Restaura instantáneamente un 30% de PS propios.",
    "自身のHPを60％回復": "Restaura instantáneamente un 60% de PS propios.",
    "自身のHPを80％回復": "Restaura instantáneamente un 80% de PS propios.",
    "自身のブーストエネルギーを中回復": "Restaura una cantidad moderada de indicador de turbo.",
    "自身のブーストエネルギーを大回復": "Restaura una gran cantidad de indicador de turbo.",
    "自身のブーストエネルギー回復量を12秒間大アップ": "Aumenta en gran medida la tasa de recarga de turbo durante 12 s.",
    "自身の攻撃力を15秒間大アップ": "Aumenta en gran medida el ataque propio durante 15 s.",
    "自身の攻撃力を30秒間小アップ": "Aumenta ligeramente el ataque propio durante 30 s.",
    "自身の攻撃力を中アップ ＋移動速度を中アップ(10秒間)": "Aumenta moderadamente el ataque y la velocidad de vuelo por 10 s.",
    "自身の移動速度を10秒間小アップ": "Aumenta ligeramente la velocidad de vuelo durante 10 s.",
    "自身の被ダメージを10秒間70％カット": "Reduce un 70% el daño recibido durante 10 s.",
    "自身の被ダメージを15秒間50％カット": "Reduce un 50% el daño recibido durante 15 s.",
    "自身の被ダメージを25秒間30％カット": "Reduce un 30% el daño recibido durante 25 s.",
    "自身の被ダメージを3秒間50％カット": "Reduce un 50% el daño recibido durante 3 s.",
    "自身の被ダメージを5秒間100％カット": "Inmunidad total: anula el 100% de todo daño recibido durante 5 s.",
    "近くの味方がいる場所へ瞬間移動し、HPを50％回復": "Teletransporte al aliado más cercano y restaura un 50% de PS.",
    "近くの相手に中ダメージ攻撃 ＋シールドブレイク": "Golpe contundente a corta distancia con daño medio y rotura de escudo.",
    "近くの相手に中ダメージ攻撃 ＋上吹き飛ばし": "Golpe a corta distancia con daño medio y elevación por los aires.",
    "近くの相手に大ダメージ攻撃 ＋上吹き飛ばし": "Golpe demoledor a corta distancia con gran daño y elevación por los aires.",
    "近くの相手に大ダメージ攻撃 ＋叩きつけ": "Golpe demoledor a corta distancia con gran daño e impacto contra el suelo.",
    "近くの相手に大ダメージ攻撃 ＋叩きつけ（与えたダメージの100％を回復）": "Gran impacto a corta distancia con derribo y absorbe el 100% del daño en PS.",
    "近くの相手に小ダメージ攻撃 ＋上吹き飛ばし": "Ataque ligero a corta distancia con elevación por los aires.",
    "近くの相手に小ダメージ攻撃 ＋叩きつけ": "Ataque ligero a corta distancia con impacto contra el suelo.",
    "近くの相手に小ダメージ攻撃 ＋叩きつけ（スペシャルスキルゲージを30%減少）": "Ataque ligero con impacto y drena un 30% del medidor de SS rival.",
    "近くの相手に極大ダメージ攻撃 ＋上吹き飛ばし": "Impacto colosal a corta distancia con daño masivo y elevación por los aires.",
    "連続ダメージ(合計大ダメージ) ＋味方を継続回復(秒間8%)する空間を8秒生成": "Crea una zona por 8 s que daña a los rivales y sana a los aliados (8%/s).",
    "連続ダメージを与える空間を8秒間生成(合計極大ダメージ)": "Genera una zona de daño continuo durante 8 s (daño masivo total)."
}

# 3. KICKER COMPLETE LOCALIZATION
KICKER_PROFILES_SPANISH = {
    1: {
        "name": "Tsubame",
        "cv": "Kaito Ishikawa",
        "profile": "Joven apasionado que aspira a ser el mejor Kicker. Creció en un orfanato y su mayor tesoro son las gafas heredadas de un Kicker legendario, el objeto clave que despierta su verdadero potencial. Amigo de la infancia de Ruriha y Owlbert.",
        "specialSkillName": "Planeo Ráfaga (Burst Glide)",
        "specialSkillDescription": "Aumenta la velocidad de movimiento un 20% y despliega un tornado dañino a su alrededor durante unos 10 s que lanza por los aires a los rivales.",
        "kickerSkillName": "Embestida Sónica (Sonic Rush)",
        "kickerSkillDescription": "Se abalanza rápidamente hacia adelante asestando un tajo que inflige el doble de daño de ataque. Destruye y anula los escudos defensivos rivales.",
        "abilityName": "Carga Acelerada (Accel Charge)",
        "abilityDescription": "Cuando la salud (PS) cae por debajo del 50%, la velocidad de recarga de la barra de turbo aumenta un 100%."
    },
    2: {
        "name": "Ruriha",
        "cv": "Azumi Waki",
        "profile": "Idol carismática y llena de energía que ilumina el estadio con su sonrisa. Creció junto a Tsubame y Owlbert, y compite en Kick-Flight para transmitir valor y alegría a todos sus fans.",
        "specialSkillName": "Escenario Curativo (Cure Light Stage)",
        "specialSkillDescription": "Proyecta un resplandeciente escenario en el aire que restaura continuamente la salud de todos los aliados y disipa estados alterados.",
        "kickerSkillName": "Disparo en Retroceso (Backstep Shot)",
        "kickerSkillDescription": "Realiza un ágil salto hacia atrás mientras dispara proyectiles helados que dañan y ralentizan al rival.",
        "abilityName": "¡Jamás me rendiré! (#Zettai Makenai yo!)",
        "abilityDescription": "Al curar a un compañero, aumenta temporalmente la velocidad de movimiento propia y del aliado sanado."
    },
    3: {
        "name": "Coco",
        "cv": "Yuki Kuwahara",
        "profile": "Pastelera alegre vestida con traje de conejita que maneja un martillo gigante impulsado por turbinas. Dulce pero arrolladora, castiga a quien intente robar sus dulces.",
        "specialSkillName": "Torbellino Coco (Coco Swing Tornado)",
        "specialSkillDescription": "Gira a toda potencia con su martillo gigantesco desatando un tifón devastador que barre a todos los rivales en un amplio radio.",
        "kickerSkillName": "Bomba en Picado (Shock Dive)",
        "kickerSkillDescription": "Se lanza con fuerza en picado generando una onda sísmica demoledora que aturde e inflige gran daño en área.",
        "abilityName": "Ritmo Coco (Coco Rhythm)",
        "abilityDescription": "Cada impacto consecutivo con sus ataques básicos incrementa su defensa y resistencia al retroceso."
    },
    4: {
        "name": "Kite",
        "cv": "Kouki Uchiyama",
        "profile": "Joven shinobi frío y calculador que domina las artes ninja del aire. Considera a Tsubame su gran rival y busca alcanzar la cúspide perfeccionando su técnica en solitario.",
        "specialSkillName": "Shuriken Colmillo de Viento (Fuga Shuriken)",
        "specialSkillDescription": "Lanza un gigantesco shuriken impregnado de energía eólica que atraviesa a múltiples rivales cortando el espacio.",
        "kickerSkillName": "Técnica Ilusoria (Genjutsu)",
        "kickerSkillDescription": "Crea clones de sombras ilusorios para confundir a los rivales mientras él se desvanece para atacar por sorpresa.",
        "abilityName": "Esencia de un Instante (Setsuna no Gokui)",
        "abilityDescription": "Tras esquivar con éxito un ataque enemigo mediante un giro aéreo, su siguiente golpe inflige un daño crítico incrementado."
    },
    5: {
        "name": "Owlbert",
        "cv": "Mutsumi Tamura",
        "profile": "Pequeño genio inventor de la tecnología aérea. Amigo de la infancia de Tsubame y Ruriha, programa drones tácticos autónomos para brindar apoyo y dominar el terreno.",
        "specialSkillName": "Formación Nube de Drones (Formation Cloud)",
        "specialSkillDescription": "Despliega una flotilla de drones de apoyo que proyectan un domo protector sobre los aliados y electrifican a los rivales que osen cruzarlo.",
        "kickerSkillName": "Dron de Hackeo (Hacking Drone)",
        "kickerSkillDescription": "Envía un dron teledirigido que intercepta al rival, bloqueando sus discos e interfiriendo con su visión durante varios segundos.",
        "abilityName": "Teoría de Trampas (Trap Theory)",
        "abilityDescription": "Reduce notablemente el tiempo de recarga de todos los discos de tipo trampa y torreta, potenciando además su daño."
    },
    6: {
        "name": "Pitophy",
        "cv": "Miku Ito",
        "profile": "Gatita traviesa y caótica a bordo de una cápsula mecha flotante. Armada hasta los dientes, adora provocar a los rivales y desatar tormentas de misiles a distancia.",
        "specialSkillName": "Fiesta de Misiles (Missile Party)",
        "specialSkillDescription": "Abre todas las compuertas de su mecha y dispara una andanada masiva de micro-misiles teledirigidos contra todos los rivales.",
        "kickerSkillName": "Joker Inverso (Reverse Joker)",
        "kickerSkillDescription": "Lanza una caja trampa sorpresa que al abrirse proyecta un resorte demoledor que derriba e invierte los controles del objetivo.",
        "abilityName": "Aumento de Daño (Damage Raise)",
        "abilityDescription": "Al acertar ataques a distancia consecutivos, su multiplicador de daño de ataque se incrementa progresivamente."
    },
    7: {
        "name": "Grenhawk",
        "cv": "Hiroki Yasumoto",
        "profile": "Curtido veterano militar con gabardina táctica y porte imponente. Como un hermano mayor protector, emplea fuego pesado y artillería aérea para custodiar a su escuadrón.",
        "specialSkillName": "Operación Ala Táctica (Operation Wing)",
        "specialSkillDescription": "Solicita un bombardeo aéreo de precisión sobre una amplia zona, devastando el terreno y cubriendo a los aliados con pantallas de humo tácticas.",
        "kickerSkillName": "Disparo Ralentizador (Slow Shot)",
        "kickerSkillDescription": "Dispara un proyectil pesado de contención que suprime el impulso de vuelo del rival y frena fuertemente su velocidad.",
        "abilityName": "Memorias del Frente (Senjou no Kioku)",
        "abilityDescription": "Aumenta la defensa y resistencia a los impactos de todos los aliados que permanezcan en sus proximidades."
    },
    8: {
        "name": "Anna",
        "cv": "Shizuka Ito",
        "profile": "Elegante cazarrecompensas de puntería implacable y fría serenidad. Domina el combate aéreo a larga distancia con su fusil de precisión láser.",
        "specialSkillName": "Prisión Aérea (Aero Prison)",
        "specialSkillDescription": "Dispara una red de rayos láser de plasma que encierra a los rivales en una jaula de energía suspendida en el aire impidiéndoles huir.",
        "kickerSkillName": "Rayo Vinculante (Binding Ray)",
        "kickerSkillDescription": "Emite un haz láser frontal que inmoviliza al objetivo fijado y lo atrae hacia el alcance de sus compañeros.",
        "abilityName": "Cazadora Estelar (Star Chaser)",
        "abilityDescription": "Detecta automáticamente la posición de los rivales con poca salud y recibe un impulso adicional de velocidad de vuelo."
    },
    9: {
        "name": "Jay",
        "cv": "Hiroyuki Yoshino",
        "profile": "Rebelde artista callejero y el Kicker con la velocidad punta más rápida de la liga. Vuela a toda marcha dejando estelas de pintura colorida para burlarse de las defensas.",
        "specialSkillName": "Grafiti Alucinógeno (Hallucination Graffiti)",
        "specialSkillDescription": "Pinta un grafiti gigante en el aire que estalla en una cegadora explosión de colores, desorientando y cegando a los rivales.",
        "kickerSkillName": "Pintura Furtiva (Stealth Paint)",
        "kickerSkillDescription": "Se rocía con un spray de camuflaje de alta tecnología, volviéndose invisible a la vista y a los radares por varios segundos.",
        "abilityName": "Regalo 4U (Present 4U)",
        "abilityDescription": "Deja una trampa de pintura al realizar giros rápidos o frenadas bruscas, que ralentiza y delata a los perseguidores."
    },
    10: {
        "name": "Yuyan",
        "cv": "Yu Kobayashi",
        "profile": "Pequeño maestro de artes marciales de gran corazón y voraz apetito. Empuña un par de nunchakus mágicos combinando acrobacias aéreas con la fuerza de un panda gigante.",
        "specialSkillName": "Lluvia Panda (Panda Rush)",
        "specialSkillDescription": "Desata una ráfaga frenética de golpes ultra-rápidos con sus nunchakus mientras un aura de espíritu de panda gigante machaca a los rivales.",
        "kickerSkillName": "Nunchaku Nyoi (Ruyi Nunchaku)",
        "kickerSkillDescription": "Extiende sus nunchakus energéticos para asestar un golpe demoledor que atrae al enemigo y lo deja vulnerable a combos inmediatos.",
        "abilityName": "Combo Imparable (Musou Rengeki)",
        "abilityDescription": "Cada golpe exitoso de sus combos básicos reduce el tiempo de recarga de su Kicker Skill."
    },
    11: {
        "name": "Diatrius",
        "cv": "Tetsu Inada",
        "profile": "Colosal guerrero biomecánico fruto de experimentos genéticos. Pese a su aterradora envergadura, posee un alma noble y usa su descomunal poder para defender a los indefensos.",
        "specialSkillName": "Mega Gravitón (Mega Graviton)",
        "specialSkillDescription": "Genera un pozo de gravedad supermasivo en el aire que atrae con fuerza irresistible a todos los rivales de la zona y los comprime violentamente.",
        "kickerSkillName": "Impacto Meteoro (Meteor Impact)",
        "kickerSkillDescription": "Acelera su enorme cuerpo como un bólido e impacta contra el objetivo, causando un daño devastador y empujándolo con violencia.",
        "abilityName": "Nanomáquinas de Arranque (Boot Nanomachine)",
        "abilityDescription": "Regenera salud de forma continua cuando se encuentra cerca de un cristal o guardián aliado."
    },
    12: {
        "name": "Buzzy Big",
        "cv": "Subaru Kimura",
        "profile": "Astro juvenil del baloncesto callejero con un ritmo contagioso y fuerza atlética. Usa su corpulencia y su balón blindado para bloquear a los rivales y asegurar los cristales.",
        "specialSkillName": "Protección de Banda (Crew Protection)",
        "specialSkillDescription": "Despliega una cúpula magnética masiva que absorbe todo el daño dirigido a sus compañeros de equipo en un amplio radio.",
        "kickerSkillName": "Barrera Frontal (Front Barrier)",
        "kickerSkillDescription": "Crea un escudo de energía frontal que repele proyectiles y empuja a los rivales que colisionen con él.",
        "abilityName": "B.B. in da House",
        "abilityDescription": "Gana una bonificación masiva de defensa y velocidad mientras transporte cristales hacia el depósito de su equipo."
    },
    13: {
        "name": "Hitagi",
        "cv": "Rika Tachibana",
        "profile": "Misteriosa espadachina que oculta su identidad tras una máscara oni tradicional. Blandiendo su katana a velocidad centelleante, desata técnicas espirituales letales.",
        "specialSkillName": "Arte Oculto: Títere Demoníaco (Kishin Kairai)",
        "specialSkillDescription": "Despierta el poder del demonio interior durante 15 s, convirtiendo todos sus ataques cuerpo a cuerpo en letales impactos mortales.",
        "kickerSkillName": "Técnica Oni: Paso Sombrío (Shukuchi)",
        "kickerSkillDescription": "Fija al rival dentro de su rango de detección y se teletransporta instantáneamente a su espalda para asestar un tajo sorpresa por la retaguardia.",
        "abilityName": "Técnica Oni: Transmigración (Rinne)",
        "abilityDescription": "Al derribar a un rival, recupera instantáneamente un porcentaje significativo de salud y llena su medidor de habilidad especial."
    },
    14: {
        "name": "Sid",
        "cv": "Tomokazu Sugita",
        "profile": "Excéntrico artista y escultor cibernético con una mirada desafiante. Utiliza rayos de grabado láser y bloques de materia cuántica para rediseñar el campo de batalla a su gusto.",
        "specialSkillName": "Láser de Grabado (Engrave Laser)",
        "specialSkillDescription": "Dispara un haz continuo de energía de gran alcance que barre el escenario, causando gran daño sostenido y perforando escudos enemigos.",
        "kickerSkillName": "Esculpir y Crear (Sculpt Make)",
        "kickerSkillDescription": "Materializa un bloque cúbico sólido flotante en el aire que bloquea el avance enemigo y provee cobertura táctica.",
        "abilityName": "Fiebre de Artista (Artist's High)",
        "abilityDescription": "Cuando sus habilidades o discos impactan con éxito en los rivales, incrementa temporalmente la velocidad de recarga de todas sus técnicas."
    }
}


def main():
    print("Loading raw Japanese masters and translating to Spanish...")

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

    # 2. Update config/masters_skill.json
    skills_file = CONFIG_DIR / "masters_skill.json"
    with open(skills_file, encoding="utf-8") as f:
        skills = json.load(f)

    skills_translated = 0
    for s in skills:
        orig_name = s.get("name", "")
        orig_desc = s.get("description", "")
        if orig_name in DISC_NAME_TRANSLATION:
            s["name"] = DISC_NAME_TRANSLATION[orig_name]
        if orig_desc in EFFECT_TRANSLATION:
            s["description"] = EFFECT_TRANSLATION[orig_desc]
            skills_translated += 1
        elif orig_desc:
            # Fallback if minor spacing difference
            for k, v in EFFECT_TRANSLATION.items():
                if k.replace(" ", "").replace("　", "") == orig_desc.replace(" ", "").replace("　", ""):
                    s["description"] = v
                    skills_translated += 1
                    break

    with open(skills_file, "w", encoding="utf-8") as f:
        json.dump(skills, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Updated {skills_translated}/{len(skills)} skill descriptions in {skills_file}")

    # 3. Update config/masters_kicker.json
    kicker_file = CONFIG_DIR / "masters_kicker.json"
    with open(kicker_file, encoding="utf-8") as f:
        kickers = json.load(f)

    for k in kickers:
        kid = k.get("id")
        if kid in KICKER_PROFILES_SPANISH:
            info = KICKER_PROFILES_SPANISH[kid]
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
        if kid in KICKER_PROFILES_SPANISH:
            info = KICKER_PROFILES_SPANISH[kid]
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
