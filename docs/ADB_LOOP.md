# Contrato del loop ADB

Este repositorio contiene scripts de servidor, proxy y captura Android, pero no
un driver de decisiones del loop. Cualquier harness externo que ejecute el loop
debe cumplir este contrato.

## Ruteo

- El hilo primario usa Sol para planeacion, arquitectura, decisiones ambiguas,
  conflictos, verificacion y sintesis final.
- Cada turno repetible del loop va a un subagente Luna con `max`.
- Cada turno debe declarar un criterio de aceptacion. Dos fallos consecutivos
  contra ese criterio escalan al hilo primario con un resumen breve, sin copiar
  el historial completo.

## Una iteracion

1. Capturar la pantalla con ADB.
2. Reducirla a aproximadamente 720 px de ancho antes de adjuntarla. En macOS,
   `sips --resampleWidth 720` evita enviar la resolucion nativa.
3. Leer solo el delta relevante de logcat.
4. Pedir a Luna una decision con criterio de aceptacion explicito.
5. Ejecutar un tap o swipe por ADB.
6. Registrar el resultado y actualizar las notas.

## Presupuesto de contexto

- El contexto activo no debe superar 250000 tokens.
- Configurar la compactacion automatica para disparar antes de 240000 tokens.
- Conservar el system prompt y los primeros turnos fijos para mantener el
  prefijo cacheable.
- Podar solo la cola mutable de la ventana deslizante. Nunca eliminar turnos
  de en medio.
- No insertar el estado completo de iteraciones anteriores en el historial.
  El subagente relee las notas persistentes en cada iteracion.

## Estado persistente

La ruta predeterminada es `.local/adb-loop-notes.md`. El archivo debe contener
solo el resumen operativo actual:

- pantallas ya visitadas;
- acciones que fallaron y el motivo;
- aprendizajes relevantes de logcat;
- ultima accion ejecutada y su resultado;
- siguiente accion propuesta y su criterio de aceptacion.

Las capturas y los logs crudos permanecen fuera del prompt salvo el artefacto
escalado y el delta estrictamente necesario para la iteracion actual.
