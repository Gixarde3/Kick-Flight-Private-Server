#!/usr/bin/env python3
"""Patch placeholders and residual untranslated keys in config/masters_translation.json."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANS_FILE = REPO_ROOT / "config/masters_translation.json"

CUSTOM_TRANSLATIONS = {
    "common.rankUpDiscCountDescriptionFormat": "Disponibles: {0}",
    "common.kickerTicket": "Tickets de Kicker",
    "common.possession": "En posesión: {0}",
    "common.all": "Todos",
    "common.pickup": "Destacados",
    "common.enableGetDiscRank": "Rango necesario: {0}",
    "common.rankFormat": "Rango {0}",
    "common.purchase": "Comprar",
    "common.paidFree": "Gratis / De pago",
    "common.discForce": "DiscForce",
    "common.secondsAgo": "Hace {0} s",
    "common.ability": "Habilidad",
    "common.show": "Mostrar",
    "common.hide": "Ocultar",
    "common.on": "Activado",
    "common.off": "Sin filtro",
    "common.sortTypeId": "Nº de ID",
    "common.sortTypeGet": "Obtención",
    "common.sortTypeRarity": "Rareza",
    "common.sortTypeLevel": "Nivel",
    "common.sortTypeAttack": "Ataque",
    "common.sortTypeHp": "Salud",
    "common.sortTypeCoolTime": "Tiempo de recarga",
    "common.sort": "Ordenar",
    "common.filter": "Filtrar",
    "common.filterAll": "Todos",
    "common.filterOff": "Sin filtro",
    "common.filterOn": "Con filtro",
    "common.filterRarity": "Rareza",
    "common.filterAttribute": "Elemento",
    "common.filterSkillType": "Tipo de habilidad",
    "attackType.default": "Ataque normal",
    "attackType.skill": "Técnica / Habilidad",
    "tutorial.defaultPlayerName": "Piloto",
    "game.crystalDeposite": "Depósito de Cristales",
    "disc.set": "Equipar",
    "disc.sort": "Ordenar",
    "disc.drawFreeTitle": "Tirada gratuita de discos",
    "disc.nextDropRewardTitleFormat": "Próxima recompensa en: {0}",
    "shop.purchaseDiscForce": "Comprar DiscForce",
    "inApp.discLevelUpTitle": "Mejora de Disco",
    "skillActionType.shotAttackDetail": "Disparo a distancia guiado.",
    "skillActionType.aroundAttackDetail": "Ataque radial en área de impacto circular.",
    "skillActionType.moveAttackDetail": "Embestida rápida con desplazamiento frontal.",
    "skillActionType.frontAttackDetail": "Ataque frontal cuerpo a cuerpo contundente.",
    "inGameTutorial.autoAttackTitle": "Ataque Automático",
    "inGameTutorial.autoAttackDescription": "Vuela cerca de un rival fijado para atacarlo automáticamente.",
    "inGameTutorial.boostDashTitleFormat": "Aceleración Boost",
    "inGameTutorial.boostDashDescription": "Mantén pulsado con dos dedos o botón para acelerar a máxima velocidad.",
    "inGameTutorial.boostDashSubDescription": "Consume barra de boost mientras aceleras.",
    "inGameTutorial.catchCrystalTitleFormat": "Recolección de Cristales",
    "inGameTutorial.crysrtalUnit": "cristales",
    "inGameTutorial.catchCrystalSubDescription": "Toca los cristales flotantes para recogerlos.",
    "inGameTutorial.depositCrystalTitle": "Depósito de Cristales",
    "inGameTutorial.depositCrystalDescription": "Lleva los cristales al guardián de tu equipo para sumar puntos.",
    "inGameTutorial.depositCrystalDescription2": "Deposita cristales antes de que te derriben.",
    "inGameTutorial.depositCrystalDescription3": "El equipo con más cristales al expirar el tiempo gana.",
    "inGameTutorial.flipTurnTitleFormat": "Giro Rápido (Flip Turn)",
    "inGameTutorial.turnAvoidTitleFormat": "Evasión Rápida",
    "inGameTutorial.underFlickTitleFormat": "Flick Hacia Abajo",
    "inGameTutorial.moveTitleFormat": "Vuelo Tridimensional",
    "inGameTutorial.moveDistanceUnit": "m",
    "inGameTutorial.moveSubDescription": "Desliza para moverte libremente por el espacio aéreo 3D.",
    "inGameTutorial.hitDiscSkillTitleFormat": "Uso de Discos",
    "inGameTutorial.hitDiscSkillDescription": "Desliza el disco equipado hacia arriba para desatar su habilidad.",
    "inGameTutorial.hitKickerSkillTitleFormat": "Técnica de Kicker",
    "inGameTutorial.hitKickerSkillDescription": "Toca el icono de técnica especial para usar tu habilidad característica.",
    "inGameTutorial.specialSkillTitleFormat": "Habilidad Especial",
    "inGameTutorial.specialSkillDescription": "Desliza el botón de Habilidad Especial cuando el medidor esté lleno.",
    "inGameTutorial.enemyUserName": "Rival de Práctica",
    "inGameTutorial.countDownMessage": "¡Comienza el combate!",
    "outGameTutorial.capsule1": "¡Has conseguido una cápsula de combate!",
    "outGameTutorial.capsule2": "Abre cápsulas para obtener nuevos discos y DiscForce.",
    "outGameTutorial.growDisc1": "Puedes subir de nivel tus discos usando DiscForce.",
    "outGameTutorial.growDisc2": "Mejora los discos para potenciar tu salud y daño de ataque.",
    "outGameTutorial.discGacha1": "Usa la ruleta de discos para expandir tu colección.",
    "outGameTutorial.discGacha2": "¡Obtén discos de rareza superior con habilidades devastadoras!",
    "outGameTutorial.discGacha3": "Configura tus mazos para adaptarte a cada modo de combate.",
    "outGameTutorial.kickerScout1": "Recluta nuevos Kickers usando Tickets de Kicker.",
    "outGameTutorial.changeKicker1": "Cambia de Kicker según tu estilo de juego favorito.",
    "outGameTutorial.inputName1": "Introduce tu nombre de piloto:",
    "outGameTutorial.inputName2": "Puedes cambiar tu nombre más tarde en ajustes.",
    "premium.description": "Pase Premium Kick-Flight",
    "premium.missionDescription": "Misiones exclusivas con recompensas adicionales diarias.",
    "premium.capsuleSlotDescription": "Ranuras de cápsulas ampliadas para investigar más botín a la vez.",
    "premium.discForceDescription": "Multiplicador del 50% de ganancia de DiscForce en todas las batallas.",
    "battleDisconnect.warningTitle": "Aviso de Desconexión",
    "battleDisconnect.warningText1": "Abandonar un combate en curso perjudica a tu equipo.",
    "battleDisconnect.warningText2": "Las desconexiones intencionadas pueden conllevar penalizaciones temporales.",
    "battleDisconnect.penaltyText1": "Penalización de puntos de batalla aplicada.",
    "battleDisconnect.penaltyText2": "Espera unos momentos antes de volver a buscar partida.",
    "battleDisconnect.resultText": "Resultado del combate",
    "gacha.discPurchaseConfirm": "¿Deseas realizar esta tirada de discos?",
    "gachaDetail.getDiscRank": "Disponible a partir de {0}",
    "gachaDetail.unlockRank": "Desbloqueo en {0}",
    "shop.unlockRankFormat": "Disponible en {0}",
    "battleSummary.rankFormat": "Rango {0}",
    "battleSummary.usedDiscSkillCount": "Discos usados: {0}",
    "battleSummary.usedKickerSkillCount": "Técnicas usadas: {0}",
    "battleSummary.usedSpecialSkillCount": "Habilidades especiales: {0}",
    "battleSummary.battleCount": "Combates: {0}",
    "battleSummary.winCount": "Victorias: {0}",
    "battleSummary.mvpCount": "MVP: {0}",
    "battleSummary.killCount": "Derribos: {0}",
    "battleSummary.killAssistCount": "Asistencias: {0}",
    "battleSummary.movingDistance": "Distancia volada: {0} m",
    "battle.backHome": "Volver a Inicio"
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
