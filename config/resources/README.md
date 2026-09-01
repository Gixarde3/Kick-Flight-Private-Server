# Catálogo local de recursos

`catalog.json` es el diccionario entre una URL solicitada por el cliente y el
archivo preservado que debe devolver el servidor. Una entrada contiene:

- `id`: identificador técnico estable.
- `logicalName`: nombre humano que iremos completando durante la identificación.
- `description`: qué representa el recurso dentro del juego.
- `host` y `requestPath`: URL original observada.
- `sourcePath`: archivo local; puede estar fuera de este repositorio.
- `contentType` y `sha256`: contrato de entrega y verificación de integridad.

La pantalla de título usa el subconjunto documentado en `title-minimum.json`.
El generador reconstruye tanto el protobuf Octo como las rutas del CDN local:

```powershell
.\scripts\build-title-resource-catalog.ps1
```

El formato local es `http://IP:18080/cdn/{o}`. `{o}` es el nombre opaco que
Octo conserva para cada objeto; el cliente sustituye esa variable de forma
nativa. El generador toma la IP de `apk-direct-server.local.json`, calcula
tamaño, CRC32, MD5 y SHA-256 y conserva las demás entradas del catálogo.

En los nombres preservados, el primer carácter decodificado (`A` para bundles
o `R` para recursos) identifica el tipo y no pertenece a `{o}`. El campo
`objectName` de Octo siempre mide exactamente seis caracteres.

El encoder sigue los números observados en `OCTProtoSerializer.Write(Data)`;
en particular, `state`, `md5`, `objectName`, `generation` y
`uploadVersionId` ocupan los campos 9 a 13. El orden de las propiedades en el
dump IL2CPP no coincide con esos números de campo.

Para registrar un archivo sin copiarlo:

```powershell
.\scripts\add-resource.ps1 -Id ejemplo -RequestPath /cdn/ejemplo.bundle `
  -FilePath C:\ruta\ejemplo.bundle -LogicalName "Recurso por identificar" `
  -Description "Descripción aportada durante la identificación"
```

Añade `-Copy` para conservar una copia dentro de `content/resources/`.
