# Louder Edge

Worker de Cloudflare que conecta secciones estáticas de Louder con GitHub Pages
sin trasladar procesamiento a WordPress.

Rutas actuales:

- `/artistas*`
- `/radar-2026*`

Si GitHub Pages devuelve 404/5xx, el Worker conserva el origen de Louder como
fallback. El despliegue se realiza con el workflow `deploy-artistas-edge.yml`.
