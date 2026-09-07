# Estado de reconstrucción de Home y cuenta demo

## Confirmado por análisis estático de la APK 2.11.0

Después de `TAP START`, el cliente contiene contratos para esta cadena:

1. `auth/prepare`
2. `auth/create` para una instalación sin usuario, o `auth/index` para una
   instalación ya registrada
3. `tutorial/start` para el alta inicial
4. `startup/index`
5. `home/index`

La ejecución dinámica todavía debe confirmar cuáles de estas rutas se llaman,
su orden exacto y los headers de sesión utilizados por esta instalación.

Los DTO recuperados de IL2CPP muestran:

- `AuthPrepareRequestData`: `packageName`, `userUniqueId`.
- `AuthPrepareResponseData`: `apiKey`, `nonce`.
- `AuthCreateRequestData`: `uuid`, `hash`; respuesta sin campos.
- `AuthRequestData`: `uuid`, `hash` y campos de integridad/dispositivo;
  respuesta sin campos.
- `StartupRequestData` y `HomeRequestData`: sin campos.
- `StartupResponseData`: inventario de kickers/discs/items, misiones y
  `tutorialProgressStatus`.
- `HomeResponseData`: `userPlayer`, decks, cápsulas, gacha, rangos, misiones,
  productos y notificaciones, entre otros.
- `ResponseUserPlayer`: `userId`, `displayUserId`, `name`, `exp`, `honorId`,
  `kickerId`, `kickerCostumeId`, `discDeckNumber` y flags de cuenta.

`TutorialProgressStatus` incluye `Start = 1` y `End = 207`. Esto permite diseñar
dos estados reproducibles una vez confirmado el intercambio real: alta/tutorial
con Tsubame y cuenta demo ya terminada que entra a Home.

## Tsubame

Los assets extraídos identifican al kicker inicial como la familia `pc_001`.
La miniatura base `ui/kicker/thumbnail_pc_001_001.unity3d` muestra al personaje
esperado. Por tanto, la hipótesis de fixture es `kickerId = 1` y costume base
`1`, pero el valor de costume y los campos mínimos deben validarse en ejecución
antes de marcarlos como contrato aceptado.

El pipeline completo produjo 2,374 bundles, 108,069 objetos Unity y cero errores.
No conviene publicar de golpe todos los bundles de `pc_001`: el cliente debe
indicar mediante sus solicitudes Octo/CDN el subconjunto exacto de Home y del
tutorial.

## Bloqueo dinámico actual

No hay ningún Android visible en `adb devices -l`. Para continuar hacen falta:

1. Un emulador o dispositivo de pruebas con la APK instalada.
2. La APK directa apuntando a la IP actual de este Mac.
3. Pulsar `TAP START` mientras el backend guarda la secuencia.

La respuesta D2C posterior a autenticación no debe inventarse: el cliente cambia
del `ParallelCode` de arranque a un hash de sesión. La captura permite recuperar
la transición y construir fixtures cifrados reproducibles para la cuenta demo.
