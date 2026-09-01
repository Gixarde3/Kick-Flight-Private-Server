# Flujo de arranque descubierto

## Secuencia confirmada

1. Unity 2018.4.11f1 inicia correctamente mediante traducción NDK ARM64 en Android 15.
2. SDKs de terceros intentan conectarse; el proxy local-only los responde con 451 o su TLS no confía en la CA. No bloquean la inicialización del proceso Unity.
3. El cliente abre TLS hacia `kickflight-api.grenge.jp`.
4. Tras instalar la CA local aparece la petición descifrada `POST /boot/index`.
5. La petición usa `Content-Type: application/octet-stream`, mide 32 bytes y cambia de SHA-256 entre ejecuciones, coherente con un vector/transformación no determinista. Sus identificadores publicitarios se registran sólo como presencia, longitud y hash corto.
6. Un 404 local y una sonda JSON plana producen el error inicial.
7. La inspección dirigida confirmó que GRE/D2C usa AES-256-CBC con PKCS7: 16 bytes de vector seguidos del ciphertext. `D2CParallelInfo.SetInfo(2, 1, 256, 128)` corresponde a PKCS7, CBC, clave de 256 bits y bloque de 128 bits.
8. Boot se envía y recibe con `ParallelCode`. HTTP 200 sólo es éxito cuando `x-app-status-code` vale `0`; el valor `200` se clasifica como `ResponseStatus.Failed` antes del descifrado.
9. La respuesta binaria aceptada contiene `assetVersion: 12345`, `smartBeatAvailableFlag: false` y `rebateUrl: ""`.
10. El cliente solicita después `GET kickflight-resource-api.grenge.jp/v1/list/12345/0` con `X-OCTO-KEY` redactado.
11. Un mensaje protobuf `Database` mínimo (`revision = 1`, sin assets) es aceptado y lleva a la pantalla `TAP START`.

## DTO recuperado

`Colorful.Networking.BootResponseData` contiene:

```text
int assetVersion
bool smartBeatAvailableFlag
string rebateUrl
```

La sonda negativa mantuvo exactamente esos nombres, pero usó JSON plano y `x-app-status-code: 200`. Ambos eran incompatibles: el contrato requiere D2C binario y el status de aplicación exitoso es `0`.

## Contrato wire confirmado

La inspección dirigida del ARM64, no un desensamblado masivo, confirmó esta cadena en `NetworkManager.GetToData<T>` (RVA `0x1991360`): serialización JSON → construcción de `D2CParallelInfo` → `D2CManager.ToParallel` (RVA `0x1A6E0D8`) → vector de 16 bytes concatenado con ciphertext AES. `FromParallel` realiza la operación inversa.

El catálogo Octo vacío es intencional y suficiente para la frontera de Fase 1. No representa el catálogo histórico ni sirve assets descargables. La siguiente fase debe empezar al tocar `TAP START` y observar la ruta real de autenticación, sin implementar candidatos preventivamente.
