# Edge routing for `loudermx.com/artistas/`

The public URL stays on **loudermx.com** while the HTML/CSS/JS is fetched from
the GitHub Pages build.

Route:

```
loudermx.com/artistas* -> Cloudflare Worker -> GitHub Pages
everything else       -> existing WordPress origin
```

The Worker is fail-safe: a GitHub 404/5xx or fetch error falls back to the
current WordPress request, so enabling the route does not delete the existing
Artistas section.

## Deployment

Cloudflare must already be authoritative/proxying `loudermx.com`. Deploy the
Worker and attach only the route `loudermx.com/artistas*`.

This repo intentionally contains no Cloudflare account token or secret.
