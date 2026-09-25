# Louder

Infraestructura desacoplada de WordPress para Louder MX.

## Artistas

La sección **Artistas** se está migrando a una arquitectura estática para que
catálogo, fichas, búsqueda, imágenes, galerías, portadas y actualizaciones no
dependan del procesamiento PHP/MySQL del hosting.

### Arquitectura

- `data/artists.json`: snapshot normalizado del catálogo actual.
- `data/galleries.json`: hasta ~5 imágenes por artista, guardando URLs y fuente.
- `data/album_art.json`: cache de portadas resueltas con MusicBrainz + Cover Art Archive.
- `scripts/migrate_from_wp.py`: migración inicial conservadora.
- `scripts/enrich_galleries.py`: galerías desde TheAudioDB y opcionalmente fanart.tv.
- `scripts/enrich_album_art.py`: portadas faltantes vía MusicBrainz/CAA.
- `live/sync_history.py`: incorpora el historial externo sin consultar WordPress.
- `scripts/build_artists.py`: genera el sitio estático.
- `docs/artistas/`: salida de GitHub Pages.
- `edge/cloudflare-worker.js`: proxy fail-safe para conservar `loudermx.com/artistas/*`.

### Imágenes

Las fotografías grandes no se almacenan masivamente en GitHub: GitHub conserva
los manifiestos y la web estática, mientras las imágenes se entregan desde los
CDN de sus fuentes. Esto evita consumir recursos de WordPress y evita superar
el límite de tamaño de GitHub Pages.

El logo oficial de Louder sí se conserva dentro del repo porque es un recurso
pequeño y propio.

### Corte público

La versión de WordPress permanece intacta como respaldo. El Worker sólo se
habilita cuando la copia estática ha sido validada. Si GitHub devuelve 404/5xx
o falla una petición, el Worker cae automáticamente al origen actual.


## Radar 2026

El repositorio también contiene un radar desacoplado para lanzamientos del
universo Louder. Su regla principal es estricta: sólo conserva canciones cuya
primera publicación registrada corresponde a **2026**.

- `data/radar_2026.json`: estado editorial y operativo.
- `scripts/update_radar_2026.py`: descubrimiento 2026 con MusicBrainz.
- `scripts/mark_radar_2026.py`: control de pendiente/descargada/programada/descartada.
- `scripts/build_radar_2026.py`: panel estático.
- `.github/workflows/radar-2026.yml`: actualización periódica y control manual.

El panel se genera junto con Artistas y no ejecuta procesos en WordPress.
