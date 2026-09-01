# Preparación y restauración de Android

## Entorno validado

La prueba reproducible usó un AVD Android 15 / API 35 `google_apis` x86_64. La imagen ofrece traducción NDK para `arm64-v8a`, necesaria porque la APK sólo contiene ARM. API 29 x86_64 rechazó la APK con `INSTALL_FAILED_NO_MATCHING_ABIS`; una imagen ARM64 no puede ejecutarse con este emulador sobre un host x86_64.

## Aplicar proxy local

Con Kestrel en 18080 y el proxy TLS local en 8080:

```powershell
.\scripts\configure-android-proxy.ps1 -ServerAddress 10.0.2.2 -Port 8080 -Apply
```

El script guarda el valor anterior en `.local/android-proxy-state.json`. Validación sin cambios:

```powershell
.\scripts\restore-android-network.ps1
```

Restauración efectiva:

```powershell
.\scripts\restore-android-network.ps1 -Apply
```

## CA de desarrollo

La primera ejecución de `run-android-capture-proxy.ps1` crea la CA bajo `certs/mitmproxy/`, carpeta ignorada. En el AVD de prueba:

1. Copiar `mitmproxy-ca-cert.cer` a `/sdcard/Download/`.
2. Abrir Settings → Security & privacy → More security & privacy → Encryption & credentials → Install a certificate → CA certificate.
3. Aceptar el aviso e instalar el archivo. Android 15 exige crear temporalmente un PIN de pantalla.

En la ejecución validada el nombre hash de la CA fue `c8750f0d.0`. Retirada, limitada por diseño a un emulador:

```powershell
.\scripts\remove-android-test-ca.ps1 -CertificateFileName c8750f0d.0 -ClearTestPin -Apply
```

También puede retirarse desde Trusted credentials → User. Nunca instales esta CA en un dispositivo personal.

## Lanzar la APK inmutable

```powershell
.\scripts\launch-and-capture.ps1 -AdbPath .\.local\android-sdk\platform-tools\adb.exe -Install
```

El script verifica el hash antes de instalar y redacta los identificadores conocidos de logcat. Las capturas crudas permanecen ignoradas.
