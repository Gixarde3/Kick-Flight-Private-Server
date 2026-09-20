# Discos y Vuelo de banderas: diagnóstico v32

## Estado

Trabajo en curso. La APK v32 es una candidata de diagnóstico, no una versión
validada contra todos los criterios. No se ha demostrado todavía daño bilateral,
pickup bilateral de bandera, entrega, puntuación ni respawn.

Control confirmado por el usuario el 17 de septiembre: avanzar con un clic
en cualquier punto de pantalla. Auto67 llegó al HUD bilateral pero sus gestos
flick/drag no demostraron desplazamiento XZ; no repetirlos para iniciar avance.
`FlightDiagnostic` ahora pulsa un punto libre y conserva capturas antes/después.

Un prototipo opcional de traza de resultados fue rechazado durante la validación
estática: GetMenuType contiene una cueva de producción usada por otra ruta en
0x1570EF8. No se integró ni se compiló en una APK; la supuesta inactividad del
cuerpo completo no permite usarlo como espacio libre. Las APK v32/v33 no cambiaron.

La rebatalla auto64 dejó emulator-5554 en Cargando y emulator-5556 en DRAW /
bonus al recuperar la sesión a las 21:50 locales. Ambos conservaron los PIDs
6305/6249. El backend registra `/battle/end` a las 19:33:29 UTC; el buffer
logcat recuperado horas después no conserva la transición de Unity, por lo
que la causa del bloqueo todavía no está identificada. Evidencia en
`v32-flags-auto64/blocked-state.txt`, capturas `blocked-*-720.png` y registros
por PID. Esto impide dar por aprobada la repetición dentro del mismo proceso.

## Cambio acotado

La APK v31 anulaba `PlayerStateSkill.UpdateActionTargeting` (0x17F31FC) con
`mov w0, 0; ret`. El binario original llama `SkillActionBase.UpdateTargeting` y
procesa Ready (+0x7C) y Cancel (+0x7D). El stub elimina esas transiciones además
de evitar las excepciones históricas. Esto es evidencia estática de una ruta
suprimida; su contribución al síntoma necesita comparación en partida.

`scripts/patch-il2cpp-endpoints.py` restaura la función y sustituye únicamente
tres ramas de excepción por guardas nulas hacia su epílogo existente (0x17F32C4):
0x17F3214, 0x17F3260 y 0x17F327C. El epílogo conserva `GetPlayerActionInfo`.
No se usan caves ni se anula `LoadDeckSummonModel`.

APK: `.local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080-v32-disc-targeting-guards.apk`

SHA-256: `D43F7CDBAB30FD00E874984AC309F43CB41425CB2BB05A145D7B00F3D0287994`.

La comparación de bibliotecas v31/v32 confirma que sólo cambia la entrada y las
tres guardas de esta función; `libunity.so` es idéntica.

## Recursos verificados

El deck actual contiene 3010001/3010002/3010003/3010004, nivel 10. Se extrajeron
los árboles reales de `aed_001` y `aed_master` mediante UnityPy. Geckosaurus
(3010002, skill 10002) tiene tipo ShotAttack, dos efectos, un collider, bullet
101 (distancia 40, velocidad 50), collision 169 (esfera radio 0.75) y hit 177.
Los efectos referenciados por los cuatro discos existen en catálogo y disco.
Su presencia en archivos no prueba por sí sola que el cliente los haya cargado.

## Baseline reproducible

`v31-disk-baseline-auto61-entry` falló antes de lanzar la app por readiness HTTP.
`v31-disk-baseline-auto61-entry2` pasó GameScene en emulator-5554 y emulator-5556.
En `v31-disk-baseline-auto61-manual`, el gesto de slot 2 quedó registrado a
19:16:26 UTC. El actor muestra cooldown 28 y una estela azul; las capturas del
observador no demuestran proyectil ni HP distinto. El tiempo restante y la falta
de un objetivo controlado hacen inconclusa la prueba de impacto.

## Comparación v32 observada

`v32-disc-baseline-auto62-entry` pasó en ambos clientes. Activación temprana del
mismo slot, aproximadamente 2:09 restantes, en `v32-disc-baseline-auto62-manual`:
`slot2-015-emulator-5554-720.png` muestra el efecto del disparo. La captura de red
registra `ReceiveAddBullet` enviado a 19:20:40.980898 UTC y retransmitido a ambos
puertos cliente a 19:20:40.981242 / 19:20:41.000999. También registra creación de
efecto sincronizado. El observador permanece en su base y no permite confirmar
visualmente el disparo remoto o un impacto; HP sigue 11656.

`photon-settings.json` contiene los 71 nombres de RpcList extraídos del objeto
PhotonServerSettings de `assets/bin/Data/data.unity3d` de la APK. Shortcut 8 es
ReceiveAction, 9 ReceiveAddBullet. `rpc-events.jsonl` conserva la correlación.

## Cadena original de banderas

Entrada runtime confirmada a las 04:01:30 UTC (17 de septiembre): ambos
usuarios solicitaron rule=2 y quedaron en battle-789585934. A las 04:01:45
se crearon dos ítems tipo 2, equipos 0/1, posiciones (70,18,26) y
(-70,18,-26), propietario 0, retransmitidos a ambos clientes. El prefijo
de propiedades real es genérico `Crystal0.*` / `Crystal1.*` incluso en
banderas: `.1` es tipo, `.2` equipo y `.3` propietario. No se debe inferir
Cristalmanía por ese prefijo ni buscar un supuesto `FlagN.3`.

`ItemManager.UpdateCheckOwnership` filtra propietario, visibilidad, movimiento,
equipo, estados del jugador y distancia. `Flag.GetItemSqrDistance` devuelve
42.25 (radio 6.5). `SetOwnerToPlayer` (0x1517350) escribe OwnerObjectId, índice
3 de ItemInitializeInfo, con CAS esperado owner 0 mediante SetProperties.
`PlayerCharacter.UpdateFlagBattle` (0x13E1E08) llama
`FlagCarriedPlayer.SetVisible` para la representación del portador.
`PlayerStateFlagStand.FlagStandEvent` (0x17D87BC) llama
`FlagGoalRequest` (0x1515540) y `SetRespawnWaitFlag` (0x151B040).
Estas rutas no fueron modificadas. Las reglas de equipo y entrega todavía
requieren confirmación visual y de propiedades durante una partida de banderas.

El asset real `field/itemdata/ite00101_2` contiene dos posiciones iniciales:
(70,18,26) y (-70,18,-26). `GetItemInitializeProperties` (0x15F5164)
asigna Team = índice % 2; TeamType Blue = 0, Red = 1. Las banderas están en
plataformas laterales elevadas. La selección de objetivos no debe tratar una
bandera enemiga en posición inicial como una bandera propia recogible.
Árbol preservado en `flag-field-items.json` y desensamblado en
`flag-create-props.txt`.

El asset `field/fielddata/fld00101_2` fija bases de aparición en (0,6.6,-91)
y (0,6.6,91), pero las zonas de entrega son Blue (-71.3,15,26.5) y
Red (71.3,15,-26.5), radio 4. `PlayerStateNormal.IsFlagStand` verifica que se
porta un ítem del mismo equipo del jugador y pasa ese equipo a
`FieldManager.IsInGoalArea`; este método usa la posición XZ del centro correspondiente.
No se debe probar entrega caminando únicamente hasta el spawn enemigo.
Evidencia: `flag-field-data.json`, `flag-stand-eligibility.txt`, `flag-goal-area.txt`.

## Evidencia y herramientas

### Candidata v33: puntuación personal ausente

Los logs nuevos de auto64 registran NRE reiterada en
`FlagFlightRuleController.GetScore`, tanto desde `PlayerParameterModel.UpdateParameter`
como desde `BattleEnd/CreateResultInfo/CreateBattleResult`. El manifiesto del backend
omite `BattleRuleFlagFlightScore`; el código original consulta esa tabla y su fila
de fallback id2. Se conserva `flag-score-pristine.txt`.

v33 sustituye únicamente las rutas de excepción por retorno 0 para puntuación
personal cuando falta esa tabla/fila (0x15F24D8, 0x15F2518, 0x15F27B0). La ruta
válida conserva sus coeficientes. Los goles de equipo, pickup y respawn permanecen
originales. El 0 es una salida defensiva ante datos ausentes; no representa pesos
de bonificación oficiales verificados.

Auto65 entró en rule2 con ambos clientes (battle-789585935, PIDs16155/16278).
Los logs de v33 ya no contienen GetScore NRE en ninguno; el backend recibió
`/battle/end` a 04:16:18 UTC y `/battle/result` a 04:16:20 con HTTP200.
5556 mostró DRAW con personajes animados; 5554 quedó en Cargando. Esto valida
la desaparición de esa excepción, pero no la navegación bilateral posterior.
El flick se ejecutó demasiado tarde para demostrar vuelo o pickup.

Auto66 usó `-FlightDiagnostic`, que espera HUD real y ejecuta flick80ms,
captura, drag400ms y captura sin revisión manual entre gestos. Falló antes
de esa secuencia: 5556 agotó 150s en MatchingScene; no existen baseline ni
capturas de vuelo. Ambos procesos siguieron vivos (17304/17425). 5554 registró
una ArgumentException `SetActiveScene: FLD00101 no cargada` a 04:21:49.393 UTC;
la misma excepción apareció en auto65, donde luego sí hubo HUD. No se atribuye
el fallo de pickup a ese stack. Evidencia en `v33-flags-flight-auto65` y
`v33-flags-flight-auto66[-entry]`, bajo `.local/gameplay-evidence/automated/`.

Revisión offline de auto64: GetScore aparece 6132/6258 veces, incluyendo
7/900 llamadas desde BattleEnd. También existen 12/6 excepciones de
`SkillParameterBase.GetSkillCategoryType` al inicializar habilidades de bots
(`CollectSkillsForAI`); no se atribuye pickup a ese stack. No se registró una
excepción específica de pickup. El reloj visible se reinició entre capturas,
pero los logs no contienen su transición: ese gesto no valida una sesión
activa ni desplazamiento reproducible.

APK: `.local/artifacts/KickFlight-2.11.0-direct-10.0.2.2-18080-v33-flag-score-null-guards.apk`.
SHA-256: `CFABF8C6D6F650E0AE0014C8CE2D931080510FF38712BA831F95FCEFBEEC87A5`.
Comparación v32/v33: sólo esas tres rutas, libunity idéntica; `v33-apk-delta.json`.

`.local/gameplay-evidence/diagnostic/discs-flags-v32/` conserva árboles de assets,
desensamblados, comparación de APK y captura `photon.pcap`.
`scripts/re/read-photon-pcap.py` decodifica ENet y Photon Protocol18 siguiendo
el código local de Luxon, con reensamblado de fragmentos y errores explícitos
para mensajes cifrados/tipos no soportados. La captura baseline decodifica miles
de mensajes y SetProperties aceptados; no se infiere ausencia de eventos a
partir de mensajes que no se pueden decodificar.

Comando: `python scripts/re/read-photon-pcap.py trace.pcap > trace.jsonl`.

### Control y disparo del 17 de septiembre: auto70/71

El usuario confirmó que un clic inicia el avance. Auto70 lo reprodujo en ambos
clientes: la posición sincronizada pasó de z≈±90 a z≈±20 y cruzó el centro.
Las horas de los comandos son locales UTC−6; el tap 09:21:06 corresponde a
15:21:06 UTC. La batalla auto70 fue rule1, no una prueba de banderas.

Auto71 usa `-DiscImpactDiagnostic`: tap bilateral, espera de 2.7 s y slot2
Geckosaurus en **Cristalmanía (rule1)**. No valida Vuelo de banderas. Los comandos se ejecutaron a 15:27:50.27/50.34 UTC y los swipes
a 15:27:53.55/54.04 UTC. Ambos muestran la mascota y cooldown, y Photon
registró proyectiles y efectos sincronizados; las capturas todavía muestran
HP 11656. No se ha demostrado impacto ni ralentización. La distancia entre
jugadores estaba dentro de 40 unidades, pero eso no garantiza orientación,
selección de objetivo ni una trayectoria libre alrededor del pilar central.
No se atribuye el resultado a una causa sin comprobar esos factores.

Evidencia: `.local/gameplay-evidence/automated/v33-disc-impact-auto71/`, PIDs
4702/5081; `probe-summary.json` sólo valida la ejecución del harness.
La captura `photon-tap-20260917.pcap` y el parser
`scripts/re/read-transform-sync.py` permiten correlacionar posiciones y RPC.

Tras la corrección del usuario, el foco inmediato es exclusivamente Vuelo de
banderas. Antes de cualquier prueba de recogida, portador o entrega se exige
selección visible de ese modo en ambos clientes y una entrada nueva con
`RuleId=2` confirmada en el backend; las pruebas rule1 quedan excluidas.
El harness admite `-ExpectedBattleRuleId 2`: comprueba los registros nuevos
de entrada de ambos usuarios y aborta antes de los inputs de gameplay si el
modo difiere o no puede verificarse. Este parámetro verifica el modo; no lo
selecciona. La comprobación fue validada rechazando los dos registros rule1
reales de auto71. La selección sigue realizándose en la interfaz del cliente.

Auto73 conservó PIDs 4702/5081 desde auto71: DRAW → Aceptar → bonus →
Volver a Inicio → Home visible en ambos (`home-wait-20-*`, 17 de septiembre).
La pantalla Home seguía mostrando Cristalmanía; la selección de Flags es el
siguiente paso y no se considera confirmada por haber vuelto a Home.
Las capturas posteriores `flags-home-emulator-5554-720.png` y
`flags-home-emulator-5556-720.png` confirman selección de **Vuelo de banderas**
en ambos. Los procesos siguen siendo 4702/5081. Falta confirmar la nueva
entrada rule2 antes de intentar recogida.
Tras cerrar el tutorial, el backend registró una entrada nueva a
**2026-09-17 15:46:11 UTC**, `rule=2`, para **1000003 y 1000004**.
Esto confirma el modo solicitado en la nueva partida; recogida, portador y
entrega siguen pendientes de prueba runtime.

Instrucción operativa confirmada por el usuario: **antes de entrar a batalla,
cambiar el modo con el botón negro de la esquina de la tarjeta Home**
(720: 645,531; raw: 968,797). Seleccionar Vuelo de banderas y confirmar con
Aceptar en ambos clientes antes de Combate. No usar las flechas laterales ni
dar por persistida la selección de una sesión anterior.

`scripts/re/a64dis.py --all` permite continuar tras retornos internos para
inspeccionar toda una función con ramas múltiples.
