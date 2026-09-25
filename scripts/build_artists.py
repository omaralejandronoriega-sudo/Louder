#!/usr/bin/env python3
"""Build the Louder Artistas static site into docs/ for GitHub Pages."""

from __future__ import annotations

import html
import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "artists.json"
GALLERIES = ROOT / "data" / "galleries.json"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def number(value: Any) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except Exception:
        return "0"


def gallery_images(gallery: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(gallery, dict):
        return []
    images = gallery.get("images") or []
    return [x for x in images if isinstance(x, dict) and x.get("url")][:5]


def preferred_image(artist: dict[str, Any], gallery: dict[str, Any] | None = None) -> str:
    images = gallery_images(gallery)
    if images:
        return str(images[0].get("preview") or images[0].get("url") or "")
    return str(artist.get("image") or "")


def gallery_html(name: str, gallery: dict[str, Any] | None) -> str:
    images = gallery_images(gallery)
    if len(images) < 2:
        return ""
    items: list[str] = []
    for index, item in enumerate(images, start=1):
        full = esc(item.get("url"))
        preview = esc(item.get("preview") or item.get("url"))
        source = esc(item.get("source") or "Fuente externa")
        kind = esc(item.get("kind") or "foto")
        items.append(
            f'''<button class="gallery-item" type="button"
 data-gallery-image data-full="{full}" data-caption="{esc(name)} · {source}">
 <img src="{preview}" alt="{esc(name)} — imagen {index}" loading="lazy" decoding="async">
 <span>{kind}</span>
</button>'''
        )
    return f'''<section class="section gallery-section">
 <div class="section-title">
  <div><h2>Galería</h2><p>{len(items)} imágenes · servidas fuera del hosting de Louder</p></div>
 </div>
 <div class="artist-gallery">{"".join(items)}</div>
 <p class="gallery-credit">Imágenes suministradas por sus respectivas fuentes; Louder conserva únicamente las referencias en GitHub.</p>
</section>'''


def social_links(artist: dict[str, Any]) -> str:
    links: list[str] = []
    if artist.get("official_url"):
        links.append(
            f'<a href="{esc(artist["official_url"])}" target="_blank" rel="noopener">Web oficial</a>'
        )
    for item in artist.get("social") or []:
        name = esc(item.get("name"))
        url = esc(item.get("url"))
        if name and url:
            links.append(f'<a href="{url}" target="_blank" rel="noopener">{name}</a>')
    return "".join(links)


def tracks_html(artist: dict[str, Any]) -> str:
    tracks = artist.get("tracks") or []
    if not tracks:
        return '<div class="note">Todavía no hay canciones consolidadas para esta ficha.</div>'

    out: list[str] = ['<div class="track-list" data-track-list>']
    for track in tracks:
        cover = (
            f'<img src="{esc(track.get("artwork"))}" alt="" loading="lazy" decoding="async">'
            if track.get("artwork")
            else '<span class="cover-fallback">Louder</span>'
        )
        out.append(
            f'''<article class="track-row" data-track
 data-title="{esc(track.get("title"))}"
 data-first="{esc(track.get("first_played"))}"
 data-last="{esc(track.get("last_played"))}"
 data-plays="{int(track.get("plays") or 0)}">
 <div class="track-cover">{cover}</div>
 <div class="track-main">
  <div class="track-title">{esc(track.get("title"))}</div>
  <div class="track-album">{esc(track.get("album") or "Álbum no identificado")}</div>
 </div>
 <div class="track-dates">
  <div><span>Primera</span><strong>{esc(track.get("first_played") or "—")}</strong></div>
  <div><span>Última</span><strong>{esc(track.get("last_played") or "—")}</strong></div>
 </div>
 <div class="track-plays"><strong>{number(track.get("plays"))}</strong><span>plays</span></div>
</article>'''
        )
    out.append("</div>")
    return "".join(out)


def related_html(
    artist: dict[str, Any],
    by_slug: dict[str, dict[str, Any]],
    galleries: dict[str, Any],
) -> str:
    items: list[str] = []
    for rel in (artist.get("related") or [])[:10]:
        slug = rel.get("slug", "")
        target = by_slug.get(slug, {})
        image = preferred_image(target, galleries.get(slug))
        media = (
            f'<img src="{esc(image)}" alt="{esc(rel.get("name"))}" loading="lazy">'
            if image
            else f'<span>{esc((rel.get("name") or "?")[:2])}</span>'
        )
        items.append(
            f'''<a class="related-card" href="../{esc(slug)}/">
<div class="related-img">{media}</div>
<div class="related-name">{esc(rel.get("name"))}</div>
</a>'''
        )
    if not items:
        return '<div class="note">Todavía no hay coincidencias suficientes para mostrar artistas relacionados.</div>'
    return '<div class="related">' + "".join(items) + "</div>"


def page_shell(
    title: str,
    body: str,
    depth: int = 1,
    description: str = "",
    canonical_path: str = "/artistas/",
    social_image: str = "",
) -> str:
    asset_prefix = "_assets/" if depth == 1 else "../_assets/"
    desc = description or "Archivo de artistas programados en Louder Radio."
    canonical = "https://loudermx.com" + canonical_path
    return f'''<!doctype html>
<html lang="es-MX">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="theme-color" content="#080808">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(canonical)}">
{f'<meta property="og:image" content="{esc(social_image)}">' if social_image else ''}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{asset_prefix}artistas.css">
<script defer src="{asset_prefix}artistas.js"></script>
</head>
<body>
<header class="site-header">
 <a class="brand" href="https://loudermx.com/" aria-label="Louder"><span>LOUDER</span><small>LA ÚNICA ALTERNATIVA</small></a>
 <nav><a href="https://loudermx.com/">Inicio</a><a class="active" href="{("../" if depth > 1 else "./")}">Artistas</a></nav>
</header>
{body}
<footer class="site-footer">Louder · Archivo musical independiente</footer>
</body>
</html>'''


def build_index(artists: list[dict[str, Any]], galleries: dict[str, Any]) -> None:
    cards: list[str] = []
    for artist in artists:
        name = artist.get("name", "")
        image = preferred_image(artist, galleries.get(artist.get("slug", "")))
        media = (
            f'<img src="{esc(image)}" alt="{esc(name)}" loading="lazy" decoding="async">'
            if image
            else f'<span>{esc(name[:2])}</span>'
        )
        cards.append(
            f'''<a class="artist-card" href="./{esc(artist.get("slug"))}/"
 data-artist-card data-name="{esc(norm(name))}"
 data-letter="{esc(norm(name)[:1].upper())}"
 data-plays="{int(artist.get("plays") or 0)}">
 <div class="artist-card-media">{media}</div>
 <div class="artist-card-body">
  <h2>{esc(name)}</h2>
  <p>{number(artist.get("plays"))} reproducciones · última aparición {esc(artist.get("last_played") or "—")}</p>
 </div>
</a>'''
        )

    body = f'''<main class="wrap">
<section class="archive-hero">
 <div class="eyebrow">Archivo Louder</div>
 <h1>Artistas</h1>
 <p>Bandas, solistas y colaboraciones registradas en el histórico de Louder Radio.</p>
 <div class="archive-actions">
  <label class="search"><span>Buscar</span><input type="search" data-artist-search placeholder="Buscar banda o artista" autocomplete="off"></label>
  <button class="button primary" type="button" data-shuffle>⤨ Otro artista</button>
  <select class="select" data-artist-sort aria-label="Ordenar artistas">
   <option value="az">A–Z</option>
   <option value="plays">Más reproducidos</option>
  </select>
 </div>
 <div class="letters" data-letter-filter>
  <button class="letter active" data-letter="">Todos</button>
  {"".join(f'<button class="letter" data-letter="{c}">{c}</button>' for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")}
 </div>
 <p class="count"><strong data-visible-count>{len(artists)}</strong> de {len(artists)} artistas</p>
</section>
<section class="artist-grid" data-artist-grid>
{"".join(cards)}
</section>
<div class="empty-state" data-empty hidden>No encontramos artistas con ese filtro.</div>
</main>'''

    out = DOCS / "artistas" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        page_shell("Artistas | Louder", body, depth=1, canonical_path="/artistas/"),
        encoding="utf-8",
    )


def build_artist(
    artist: dict[str, Any],
    by_slug: dict[str, dict[str, Any]],
    galleries: dict[str, Any],
) -> None:
    name = artist.get("name", "")
    gallery = galleries.get(artist.get("slug", ""), {})
    image = preferred_image(artist, gallery)
    hero_image = (
        f'<img src="{esc(image)}" alt="{esc(name)}" fetchpriority="high" decoding="async">'
        if image
        else f'<span>{esc(name[:2])}</span>'
    )
    backdrop = (
        f'<div class="artist-backdrop" style="background-image:url(&quot;{esc(image)}&quot;)"></div>'
        if image
        else ""
    )
    genres = "".join(
        f'<span class="genre">{esc(g)}</span>' for g in (artist.get("genres") or [])[:8]
    )
    bio = artist.get("bio") or ""
    bio_html = "".join(
        f"<p>{esc(p)}</p>" for p in re.split(r"\n\s*\n", bio) if p.strip()
    )
    if not bio_html:
        bio_html = '<div class="note">Biografía en preparación. Los datos de programación ya forman parte del Archivo Louder.</div>'

    body = f'''<main class="wrap">
<div class="eyebrow">Archivo Louder</div>
<section class="artist-hero">
 {backdrop}
 <div class="artist-hero-inner">
  <div class="artist-art">{hero_image}</div>
  <div class="artist-copy">
   <div class="artist-kicker"><i></i>Artista en Louder</div>
   <h1>{esc(name)}</h1>
   <div class="genres">{genres}</div>
   <div class="artist-actions">
    <button class="button primary" type="button" data-shuffle-from="{esc(artist.get("slug"))}">⤨ Otro artista</button>
    <a class="button" href="../">Todos los artistas</a>
   </div>
   <div class="metrics">
    <div><strong>{number(artist.get("plays"))}</strong><span>reproducciones</span></div>
    <div><strong>{esc(artist.get("first_played") or "—")}</strong><span>primera vez</span></div>
    <div><strong>{esc(artist.get("last_played") or "—")}</strong><span>última vez</span></div>
   </div>
   <div class="social">{social_links(artist)}</div>
  </div>
 </div>
</section>

<section class="about">
 <span>Sobre {esc(name)}</span>
 <div class="bio">{bio_html}</div>
</section>

{gallery_html(name, gallery)}

<section class="section">
 <div class="section-title">
  <div><h2>Canciones en Louder</h2><p>{len(artist.get("tracks") or [])} canciones registradas</p></div>
  <div class="sort">
   <button class="button active" data-track-sort="plays">Más reproducidas</button>
   <button class="button" data-track-sort="title">A–Z</button>
   <button class="button" data-track-sort="first">Primera vez</button>
   <button class="button" data-track-sort="last">Última vez</button>
  </div>
 </div>
 {tracks_html(artist)}
</section>

<section class="section">
 <div class="section-title"><h2>Artistas relacionados</h2></div>
 {related_html(artist, by_slug, galleries)}
</section>
</main>'''

    out = DOCS / "artistas" / artist["slug"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    description = bio[:155] if bio else f"{name} en el Archivo Louder."
    out.write_text(
        page_shell(
            f"{name} | Louder",
            body,
            depth=2,
            description=description,
            canonical_path=f"/artistas/{artist['slug']}/",
            social_image=image,
        ),
        encoding="utf-8",
    )


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    artists = [a for a in data.get("artists", []) if a.get("slug") and a.get("name")]
    artists.sort(key=lambda a: norm(a.get("name", "")))
    by_slug = {a["slug"]: a for a in artists}
    gallery_store = {"artists": {}}
    if GALLERIES.exists():
        try:
            gallery_store = json.loads(GALLERIES.read_text(encoding="utf-8"))
        except Exception:
            gallery_store = {"artists": {}}
    galleries = gallery_store.get("artists") or {}

    if DOCS.exists():
        keep_media = DOCS / "media"
        tmp_media = ROOT / ".media-preserve"
        if keep_media.exists():
            if tmp_media.exists():
                shutil.rmtree(tmp_media)
            shutil.move(str(keep_media), str(tmp_media))
        shutil.rmtree(DOCS)
        if tmp_media.exists():
            DOCS.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_media), str(DOCS / "media"))

    (DOCS / "artistas" / "_assets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ASSETS / "artistas.css", DOCS / "artistas" / "_assets" / "artistas.css")
    shutil.copy2(ASSETS / "artistas.js", DOCS / "artistas" / "_assets" / "artistas.js")

    build_index(artists, galleries)
    for artist in artists:
        build_artist(artist, by_slug, galleries)

    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    (DOCS / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=./artistas/">'
        '<title>Louder</title><a href="./artistas/">Artistas Louder</a>',
        encoding="utf-8",
    )
    print(f"built {len(artists)} artists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
