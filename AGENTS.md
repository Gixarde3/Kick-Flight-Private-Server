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
