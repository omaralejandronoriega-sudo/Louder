# Radar Louder 2026

Panel interno para detectar y controlar **únicamente canciones cuya primera publicación registrada sea de 2026**.

## Regla dura

Una entrada sólo puede permanecer en `data/radar_2026.json` cuando:

- `original_release_year == 2026`
- `original_release_date` empieza con `2026`
- no es una reedición/remaster claramente identificada; esos casos pasan a revisión o se descartan.

Esto evita contaminar el radar con catálogo histórico relanzado durante 2026.

## Flujo

1. `scripts/update_radar_2026.py` recorre por lotes los artistas ya presentes en Louder y consulta MusicBrainz por grabaciones cuya `first-release-date` sea 2026.
2. También ejecuta búsquedas acotadas por etiquetas afines a Louder para descubrir artistas nuevos.
3. Lo que ya pertenece al catálogo de Louder entra con `louder_fit=yes`; descubrimientos externos quedan en `review`.
4. El estado operativo se conserva entre actualizaciones:
   - `pending`
   - `downloaded`
   - `programmed`
   - `discarded`
5. `scripts/build_radar_2026.py` genera el panel estático en `docs/radar-2026/`.
6. El workflow `radar-2026.yml` actualiza el radar cada 6 horas y permite cambiar estado/criterio manualmente desde GitHub Actions.

## Fuentes

- **MusicBrainz:** fuente canónica inicial para validar la primera fecha registrada de una grabación.
- **Discogs:** se añadirá como segunda validación de edición/tracklist; su fecha de una edición no sustituye la fecha original de la canción.
- **Sitios de noticias / New Album Releases:** sirven como señales de descubrimiento; una noticia por sí sola no supera la regla 2026.
- **Spotify:** sólo como referencia/enlace de comprobación. No se usa para descargar audio ni como base persistente del radar.

## WordPress

El panel y los procesos viven en GitHub/GitHub Actions. WordPress no ejecuta el descubrimiento, no almacena el catálogo y no hace cron.
