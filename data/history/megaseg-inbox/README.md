# MegaSeg inbox

Esta carpeta recibe exportaciones nuevas de historial de MegaSeg sin pasar por
WordPress ni por el hosting de loudermx.com.

Formatos admitidos: CSV, TSV, TXT y LOG. El importador busca columnas comunes
como `date/time`, `artist`, `title/song/track` y `album`.

El proceso es incremental e idempotente: una reproducción sólo se agrega si su
fecha/hora es posterior a la última reproducción ya conocida para esa canción.
Volver a subir el mismo archivo no duplica conteos.

El histórico consolidado se guarda en:
`data/history/history_megaseg.json`.

Después GitHub mezcla MegaSeg + Last.fm + YesStreaming y vuelve a construir
Artistas. WordPress no procesa estos archivos.
