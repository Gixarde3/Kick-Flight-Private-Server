# Reglas de Agentes

## Ruteo de modelos

- Sol se queda en el hilo primario: planeacion, arquitectura, decisiones ambiguas, resolucion de conflictos, verificacion y sintesis final.
- Luna se usa en subagentes: paquetes acotados, repetibles o de alto volumen con criterios de exito explicitos. Todo turno del loop ADB cae aqui.
- Escalar a Sol unicamente cuando un subagente falle dos veces seguidas contra su criterio de aceptacion explicito, y enviar un resumen, no el historial.

## Higiene de contexto del loop ADB

- Escalar cada screenshot a aproximadamente 720 px de ancho antes de enviarlo. Nunca enviar la resolucion nativa del emulador.
- Mantener un techo duro de 250000 tokens y compactar automaticamente antes de 240000.
- Conservar el system prompt y los primeros turnos fijos. Podar solo la cola mutable; nunca borrar turnos de en medio.
- Mantener el estado persistente en `.local/adb-loop-notes.md`. El subagente debe releerlo en cada turno para conocer pantallas visitadas, acciones fallidas y aprendizajes de logcat; no arrastrar ese estado como historial de conversacion.

El contrato operativo completo esta en [docs/ADB_LOOP.md](docs/ADB_LOOP.md).

## Builds DIAG del cliente (trazas KFDIAG en logcat)

Un build DIAG es la misma APK parcheada de siempre más `DIAG_PATCHES_ARM64` de `scripts/patch-il2cpp-endpoints.py`:
sondas ("caves") que escriben enteros en logcat con el tag `KFDIAG` (`v=N`). Jugabilidad y datos son los de
producción; solo sirve para leer qué hace el cliente por dentro. Documentación de referencia: `scripts/re/README.md`
(herramientas de RE estático, reglas de las caves, mapa de cuerpos muertos) y la cabecera de cada
`scripts/re/*_diag_caves.py` (qué significa cada valor).

### Construirlo en otra máquina

1. Requisitos: los de `scripts/build-direct-apk.ps1` / `.sh` (Python 3.10+, Java, apktool 3.0.3, build-tools 35.0.0,
   `base.apk` con el SHA conocido) más `pip install keystone-engine capstone` solo si vas a **generar** sondas nuevas
   (para construir con las existentes no hace falta: los bytes ya están en la tabla del script).
2. Las variables de entorno las lee el script de parches, así que funcionan con cualquiera de los dos builders:
   - `KF_DIAG=1` incluye las sondas (dry-run: 141 parches de producción → ~245 en DIAG);
   - `KF_NRE_LR=1` añade además la cave H: cada `NullReferenceException` imprime los 32 bits bajos de la dirección
     de retorno del sitio que la lanzó (ver "localizar una NRE" abajo);
   - `KF_UNLOAD_BYPASS=1` reactiva un bypass viejo del `_isUnloading` de `LoadManager.Enqueue` (solo comparación, provoca
     el SIGSEGV intermitente en el hilo UnityPreload).
   ```powershell
   $env:KF_DIAG = "1"; .\scripts\build-direct-apk.ps1 -OutputPath .local\KickFlight-2.11.0-DIAG.apk
   ```
   ```bash
   KF_DIAG=1 SERVER_BASE_URL=http://<ip-servidor>:18080 OUTPUT_APK=.local/KickFlight-2.11.0-DIAG.apk scripts/build-direct-apk.sh
   ```
   Verificación sin construir: `KF_DIAG=1 python scripts/patch-il2cpp-endpoints.py --dry-run --arm64 <libil2cpp.so pristino>`.
3. Instalar (`adb install -r`) y arrancar el cliente como siempre (`start-client-diag.bat` en la máquina de Tanuki
   hace `APK_OVERRIDE=.local\KickFlight-2.11.0-DIAG.apk`). El servidor no cambia: mismo `start-server.bat`.
4. Antes de cada prueba `adb logcat -c`; después `adb logcat -d -v time > .local/run/logcat-<nombre>.txt`.
   Lectores: `python scripts/re/attack_diag_read.py <archivo>` (ataques básicos/combos, línea de tiempo legible),
   `adb logcat -d -s KFDIAG` para todo lo demás (tabla de valores en `scripts/re/README.md` y las cabeceras de
   `attack_diag_caves.py` / `warp_diag_caves.py`).

### Sondas actuales (2026-09-20)

| Valores | Qué dicen | Fuente |
| --- | --- | --- |
| 1xx/2xx/3xx/4xx, 6xx, 700 | handshake de inicio de batalla, `_enableAi`, AIPlayerEngine | tabla inline en `patch-il2cpp-endpoints.py` |
| 940+n | `PlayerCharacter.SetState(n)` | idem |
| 950–973, 1000–3999 | IA: rutas, PerformMove, sub-estados, take-off | idem (regiones D/E) |
| 6200–6421 | fin de skill, CrossFade, nunchaku, acople de armas, PlayIdle | idem (región F) |
| 7700–7830 | warp de Hitagi (KS sin objetivo), `SetVisible` | `scripts/re/warp_diag_caves.py` |
| 8100–8823 | bucle de ataque básico: combo, `IsUpdateAction` con motivos (`87x0/87x1`) y estado actual (`8790+n`), alcance, ángulos, `IsAttack`, `Play*AttackIn`, destrucción de colisiones (`8800+tipo`, `8810+impactos`) | `scripts/re/attack_diag_caves.py` |
| LR crudo | origen de cada NRE (`KF_NRE_LR=1`) | cave H |

### Añadir o cambiar una sonda

- Escribe el cuerpo en `scripts/re/attack_diag_caves.py` (o un archivo hermano) y ejecuta el script: imprime las
  entradas `DIAG cave`/`DIAG hook` listas para pegar en `patch-il2cpp-endpoints.py` antes de `# ---- END DIAGNOSTIC ----`
  (reemplaza el bloque anterior completo: las caves se re-empaquetan y cambian de dirección).
- Reglas que costaron crashes: nunca `UnityEngine.Debug.Log` desde código parcheado (muere en `libunity+0x34426c`);
  hook de entrada de función = `b` + salto de vuelta, nunca `bl` (pisa el LR del llamador); nada de hooks en
  funciones hoja ni sobre `bl`/saltos; la cave pierde NZCV (si el hook cae sobre un `fcmp`, repítelo al final);
  no asumas que un registro sigue teniendo `this` (`IsUpdateAction` reutiliza x19: la primera sonda 8230 crasheó en
  la pantalla de carga 5/5 veces); solo cuerpos muertos verificados (entrada stub a `ret` en producción y ningún
  salto entrante, comprobado con un barrido de `b/bl/b.cond/cbz/tbz` sobre todo el .so).
- Cuerpos muertos en uso y libres: ver "Dead bodies" en `scripts/re/README.md` (`UpdateIdleTypeRate` tiene ~1 KB libre).
- Reubicar un bloque de caves entero a otro cuerpo: `scripts/re/relocate_diag_region.py` (relinka `bl`/`adrp` externos
  y los hooks entrantes; así salieron las regiones D/E de `LoadDeckSummonModel`, que el DIAG tenía que stubear y por
  eso ningún summon cargaba en DIAG).

### Localizar una NRE con `KF_NRE_LR=1`

`KFDIAG v=<n>` justo antes de la excepción en logcat es `LR & 0xFFFFFFFF` (puede salir negativo). Base del módulo:
`adb shell run-as jp.grenge.kickflight cat /proc/$(pidof jp.grenge.kickflight)/maps | grep libil2cpp | head -1`.
RVA = `(base & ~0xFFFFFFFF | n) - base` (si sale negativo, suma `0x100000000`). Ese RVA es la instrucción siguiente
al `bl 0x12141ec` (helper de NRE) y `python scripts/re/a64dis.py <rva-0x20> 12` enseña qué comprobación de nulo era.
Ejemplo real: `0x13C74CC` = `FieldManager.FieldInfo == null` en `PlayerCharacter.Initialize` → faltaba la fila 801 del
master `Field` (string inline en `DemoSessionApi.cs`), no era el cliente.

### Aprendizajes del 2026-09-20 (ronda 7)

- La regresión "Leorex congela al kicker y no reaparece" era solo DIAG: `LoadDeckSummonModel` estaba stubeado porque
  sus bytes alojaban las regiones D/E → ningún modelo de summon cargado → NRE en `SummonCharacter.InitializeAsync` y
  en cada `ApplyForcedAction → PlayerStateSkill.End → ForceFinishSummon`. Resuelto reubicando las regiones.
- La pantalla de selección de kicker en blanco: `kickerCostumeId` es el **id de fila** de `KickerCostume` (110 = Hitagi
  color estándar, 64 = Owlbert), no la columna `costumeId`. El servidor ahora sirve ids de fila y normaliza un
  costume que no sea del kicker actual.
- El botón de prueba (Trial, campo 801) nunca había cargado: fila 801 del master `Field` ausente (ver arriba).
- Combos cuerpo a cuerpo 1-1-1: cada golpe **conectaba** pero el collider llegaba al fin de su vida útil
  (`CollisionDestroyType.LifeTime`) porque `masters_weapon_attack_collision.json` tenía `collisionHitType = All`;
  `WeaponAttackActionBase.CallbackAttackCollisionDestroy(LifeTime)` marca el golpe como fallo, anula el objetivo y
  `ResetComboCount()`. Con `One` el primer impacto destruye el collider con tipo `Hit` y el combo encadena.
  Cambiado en el generador y en el JSON (pendiente de verificar en juego).
- Los CRASH de logcat bajo ndk_translation siempre muestran `libunity+0x34426c`: solo valen `fault addr` y el nombre
  del hilo. `UnityPreload` + fault 0 ~6-12 s después de `D/Unity: GameScene` es la carrera intermitente del loader.
- Los masters `Field`, `BattleRule` (fallback) y otros son strings inline en `DemoSessionApi.InitializeMasters`;
  `python scripts/re/served_master.py <Tabla>` enseña lo que realmente recibe el cliente.

### Aprendizajes del 2026-09-20 (ronda 8: pasivas, KS y efectos de discos)

- Todos los efectos de discos y KS van ahora en `DISC_EFFECTS` / `KICKER_SKILL_EXTRAS` de
  `scripts/generate_combat_masters.py` (curas, condiciones, blow-off, pull-in) y se regeneran con
  `python scripts/generate_combat_masters.py --only masters_skill_condition,masters_skill_heal,masters_skill_blow_off,masters_skill_pull_in,masters_skill_trap`
  (ojo: `--only skill_condition` a secas también reescribe `masters_special_skill_*`). Semántica verificada de cada
  columna en `docs/COMBAT_MASTERS_FILL_IN.md` §2 (curas = fracción de MaxHP, HpDrain/SpDrain se leen en
  `ApplyHealOnDamage`, DamageRate = daño recibido, Poison = MaxHP del objetivo por tick, Dot = ataque del emisor…).
- Blow-off: sin fila `SkillBlowOff` un `FrontAttack` golpea hacia **abajo** (`FrontAttackSkillAction.get_BlowOffDirectionType`
  → 2); por eso Blox y compañía "slammeaban" en vez de lanzar. En un `MoveAttack` la fila convierte la embestida en
  "pursuit" (arrastra al golpeado, `MoveAttackSkillAction.HitCallback`) y sin fila es "pierce" + shield break
  (`DiscSkillParameter..ctor` solo marca `IsShieldBreak` si no hay blow-off ni cura). Dirección 4 = víctima − atacante,
  así que en bombas/torretas (atacante = quien la puso) se usa Up.
- Pull-in (KS de Yuyan/Anna): fila `SkillPullIn` → `PlayerStatePullIn`; una fila de blow-off en el mismo skill la anula.
- Bomba de Jay: `DiscSkillParameter..ctor` solo rellena `TrapInfo.CollisionMasterId/Radius/LifeTime/EffectPath` desde un
  clip sensor del timeline `aed_NNN`, y ningún bundle tiene grupo 40001 → la explosión pedía la colisión 0 (null) y nunca
  estallaba. Cave de producción en la cola de `BatAbilityParameter..ctor` (cuerpo de `UpdateIdleTypeRate`, 0x13CE500):
  colisión 198 de `skill_40001`, radio 2 → `SkillTrap.radius`, vida `interval`, efecto `effectPath` con trigger 1 (sin
  trigger `SyncEffect.PlayStartEffect` no arranca los `effect/cm`); `duration` = 2 s hasta estallar; daño = ataque ×
  `Skill.coefficient` (10). Segunda cave (`SetModel` 0x159DA48): `DiscSkillParameter.HitInfo` solo lo asigna
  `SetSkillActionHitData` desde un clip de colisión con daño del timeline → para 40001 era null y cada impacto de la
  explosión moría con NRE en `PlayerCharacter.AcceptDamageInfo`; la cave toma `_hitInfos[207]`. Verificado en emulador
  (KFDIAG 9001-9041 + 8811 = 1 impacto, 0 excepciones). Regla nueva: una cave que hace `bl` tiene que guardar/restaurar
  x30 antes de su `ret` (la primera versión se colgaba en bucle = "Cargando" eterno con Jay).
- Carga de la Special Skill: `PlayerCharacter.CalcChargeSP` caso 2 suma `distancia volada × addMoveSpecialSkillPoint`
  (MaxSP = 100), caso 3 `addWeaponAttackSpecialSkillPoint` por golpe. `masters_kicker_parameter.json` lleva ahora
  `100 / distancia` con las distancias por kicker de Appliv 431798 (Jay 550 … Anna 1500 unidades); antes era 1.0 (la barra
  se llenaba en 100 unidades).
- El `effectPath` de una trampa/explosión tiene que ser un bundle cargado en la partida: `EffectManager.InstantiateEffect`
  devuelve null sin error para lo que `LoadManager` no cacheó (los `effect/ds/` solo se cargan para los discos equipados);
  `effect/cm/ef_cm_001..036` (orden del enum `EffectManager.Effect`, 006 = Dead) siempre están.
- Textos de la UI: `masters_translation.json` es el master `Translation`; cada `LocalizeText` de los prefabs y
  `LocalizeManager.GetText(enum)` (`skillCategoryType.attack` → "ATK", etc.) buscan su clave ahí y una clave ausente se
  pinta vacía. `scripts/generate_translations.py` genera todas las claves (prefabs `docs/localize_keys.json` + enums +
  literales); `scripts/extract_localize_layout.py` saca la posición de cada texto (`docs/localize_layout.json`) para la
  pestaña **Text** del WebUI de balance (wireframe por pantalla + edición).
- Velocidad de ataque básico: constantes en el cliente (`XxxAttackAction..cctor`), no es dato de master;
  `RANGED_ATTACK_INTERVALS` en `patch-il2cpp-endpoints.py` (rebuild con `build-all-apks.bat`).
- Tiempos de casteo por kicker y categoría (Appliv 431798) → `CAST_TIMES` en `scripts/build-action-asset-bundles.py`,
  que desplaza `_compatibilityTime` y los `_startTime` de cada disco en los nueve bundles generados (revisión Octo 26).
  Rehacer bundles = `python scripts/build-action-asset-bundles.py`, subir `revision` en `title-minimum.json` **y añadir
  el nuevo número a `fromRevisions`** (el cliente al día pide `/v1/list/12345/<revision>` y sin ese fixture recibe 404 =
  "error de comunicación"), `python scripts/build-title-resource-catalog.py`.
