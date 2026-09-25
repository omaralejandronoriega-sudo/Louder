# Louder

Infraestructura desacoplada de WordPress para Louder MX.

## Artistas

La sección **Artistas** se migra a GitHub para que catálogo, fichas, búsqueda, ordenamientos y frontend no dependan del procesamiento de WordPress.

### Arquitectura

- `data/artists.json`: snapshot normalizado del catálogo.
- `scripts/migrate_from_wp.py`: migración inicial, leyendo el frontend público actual con ritmo conservador.
- `scripts/build_artists.py`: genera el sitio estático en `docs/artistas/`.
- `assets/`: CSS y JavaScript del frontend.
- `.github/workflows/artistas.yml`: migración/build automatizado.

La versión de WordPress debe mantenerse activa hasta validar la copia estática.
