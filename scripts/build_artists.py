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
ALBUM_ART = ROOT / "data" / "album_art.json"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def public_artist_name(value: str) -> str:
    """Remove obvious track-number pollution without touching legitimate names.

    Examples fixed: "04 Swimwear" -> "Swimwear", "05 Van She" -> "Van She".
    We deliberately only strip zero-padded numeric prefixes, so real names such
    as "4 The Cause", "2 Door Cinema Club" or "10 Years" remain untouched.
    """
    raw = str(value or "").strip()
    cleaned = re.sub(r"^0\d{1,2}[\s._-]+(?=\S)", "", raw).strip()
    return cleaned or raw


def canonical_track_title(value: str) -> str:
    raw = str(value or "").strip()
    patterns = [
        r"\s*[\-–—]\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?\s*$",
        r"\s*\((?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?\)\s*$",
        r"\s*\[(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?\]\s*$",
    ]
    out = raw
    for pattern in patterns:
        out = re.sub(pattern, "", out, flags=re.I).strip()
    return out or raw


def canonical_album(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return raw
    out = re.sub(r"\s*[\[(](?:remaster(?:ed)?(?:\s+\d{4})?|\d{4}\s+remaster(?:ed)?|deluxe(?:\s+edition)?|expanded(?:\s+edition)?)[\])]\s*$", "", raw, flags=re.I).strip()
    out = re.sub(r"\s*[\-–—]\s*(?:remaster(?:ed)?(?:\s+\d{4})?|\d{4}\s+remaster(?:ed)?|deluxe(?:\s+edition)?|expanded(?:\s+edition)?)\s*$", "", out, flags=re.I).strip()
    return out or raw


def merge_public_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for original in tracks or []:
        if not isinstance(original, dict) or not original.get("title"):
            continue
        track = dict(original)
        clean_title = canonical_track_title(str(track.get("title") or ""))
        key = norm(clean_title)
        if not key:
            continue
        track["title"] = clean_title
        if track.get("album"):
            track["album"] = canonical_album(str(track.get("album") or ""))
        current = merged.get(key)
        if current is None:
            merged[key] = track
            continue

        current["plays"] = int(current.get("plays") or 0) + int(track.get("plays") or 0)
        dates_first = [str(x or "") for x in (current.get("first_played"), track.get("first_played")) if x]
        dates_last = [str(x or "") for x in (current.get("last_played"), track.get("last_played")) if x]
        if dates_first:
            current["first_played"] = min(dates_first)
        if dates_last:
            current["last_played"] = max(dates_last)
        if not current.get("artwork") and track.get("artwork"):
            current["artwork"] = track.get("artwork")
        if (not current.get("album") or current.get("album") == "Programación YesStreaming") and track.get("album"):
            current["album"] = track.get("album")
        current["sources"] = sorted(set((current.get("sources") or []) + (track.get("sources") or [])))

    return sorted(merged.values(), key=lambda t: (-int(t.get("plays") or 0), norm(str(t.get("title") or ""))))


def prepare_public_artists(artists: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Create a cleaned public view while preserving raw historical data."""
    buckets: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}

    for original in artists:
        if not isinstance(original, dict) or not original.get("name"):
            continue
        raw_name = str(original.get("name") or "").strip()
        clean_name = public_artist_name(raw_name)
        key = norm(clean_name)
        if not key:
            continue
        candidate = dict(original)
        candidate["name"] = clean_name
        candidate["tracks"] = merge_public_tracks(candidate.get("tracks") or [])
        current = buckets.get(key)
        if current is None:
            buckets[key] = candidate
        else:
            current["plays"] = max(int(current.get("plays") or 0), int(candidate.get("plays") or 0))
            current["tracks"] = merge_public_tracks((current.get("tracks") or []) + (candidate.get("tracks") or []))
            if not current.get("image") and candidate.get("image"):
                current["image"] = candidate.get("image")
            if not current.get("bio") and candidate.get("bio"):
                current["bio"] = candidate.get("bio")
            current["sources"] = sorted(set((current.get("sources") or []) + (candidate.get("sources") or [])))
        aliases[norm(raw_name)] = key
        aliases[norm(clean_name)] = key

    used: set[str] = set()
    key_to_slug: dict[str, str] = {}
    for key, artist in buckets.items():
        base = slugify(str(artist.get("name") or ""))
        slug = base
        n = 2
        while slug in used:
            slug = f"{base}-{n}"
            n += 1
        used.add(slug)
        artist["slug"] = slug
        key_to_slug[key] = slug

    alias_to_slug = {alias: key_to_slug[target] for alias, target in aliases.items() if target in key_to_slug}
    public = sorted(buckets.values(), key=lambda a: norm(str(a.get("name") or "")))
    return public, alias_to_slug


def number(value: Any) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except Exception:
        return "0"


def source_stats_html(artist: dict[str, Any]) -> str:
    stats = artist.get("source_stats") or {}
    chips: list[str] = []

    lastfm = stats.get("lastfm") or {}
    if lastfm:
        chips.append(
            f'<div class="source-chip"><strong>Last.fm</strong><span>{number(lastfm.get("plays"))} scrobbles</span></div>'
        )

    megaseg = stats.get("megaseg") or {}
    if megaseg:
        chips.append(
            f'<div class="source-chip"><strong>MegaSeg</strong><span>{number(megaseg.get("plays"))} registros</span></div>'
        )

    yesstreaming = stats.get("yesstreaming") or {}
    if yesstreaming:
        chips.append(
            f'<div class="source-chip"><strong>YesStreaming</strong><span>{number(yesstreaming.get("catalog_tracks"))} canciones en servidor</span></div>'
        )

    live = stats.get("yesstreaming_live") or {}
    if live:
        chips.append(
            f'<div class="source-chip"><strong>YesStreaming live</strong><span>+{number(live.get("plays_after_baseline"))} nuevas</span></div>'
        )

    if not chips:
        return ""
    return f'''<section class="source-stats" aria-label="Fuentes del histórico">
 <div class="source-stats-title">Fuentes del histórico</div>
 <div class="source-chips">{"".join(chips)}</div>
 <p>Los registros por fuente pueden solaparse; el total principal usa el contador canónico y no una suma ciega.</p>
</section>'''


def gallery_images(gallery: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(gallery, dict):
        return []
    images = gallery.get("images") or []
    return [x for x in images if isinstance(x, dict) and x.get("url")][:5]


def preferred_image(artist: dict[str, Any], gallery: dict[str, Any] | None = None) -> str:
    # Preserve the image already used by Louder/WordPress whenever available.
    # External gallery imagery is enrichment, not a replacement for approved art.
    existing = str(artist.get("image") or "").strip()
    if existing:
        return existing
    images = gallery_images(gallery)
    if images:
        return str(images[0].get("preview") or images[0].get("url") or "")
    return ""


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


def album_art_key(artist: str, album: str) -> str:
    return norm(artist) + "|" + norm(album)


def tracks_html(artist: dict[str, Any], album_art: dict[str, Any]) -> str:
    tracks = artist.get("tracks") or []
    if not tracks:
        return '<div class="note">Todavía no hay canciones consolidadas para esta ficha.</div>'

    out: list[str] = ['<div class="track-list" data-track-list>']
    for track in tracks:
        album = str(track.get("album") or "")
        cached = album_art.get(album_art_key(str(artist.get("name") or ""), album), {})
        artwork = str(track.get("artwork") or cached.get("url") or "")
        cover = (
            f'<img src="{esc(artwork)}" alt="" loading="lazy" decoding="async">'
            if artwork
            else (
                f'<span class="cover-fallback" data-missing-cover '
                f'data-artist="{esc(artist.get("name"))}" data-title="{esc(track.get("title"))}">Louder</span>'
            )
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
    canonical = "https://artistas.loudermx.com" + canonical_path
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
 <a class="brand" href="https://loudermx.com/" aria-label="Louder"><img src="{asset_prefix}logo_louder.png" alt="Louder"><small>LA ÚNICA ALTERNATIVA</small></a>
 <button class="nav-toggle" type="button" aria-label="Abrir menú" data-nav-toggle>☰</button>
 <nav data-main-nav>
  <a href="https://loudermx.com/">Inicio</a>
  <a href="https://loudermx.com/noticias/">Noticias</a>
  <a href="https://loudermx.com/nosotros/">Nosotros</a>
  <a href="https://loudermx.com/radio/">Radio</a>
  <a class="active" href="{("../" if depth > 1 else "./")}">Artistas</a>
  <a href="https://loudermx.com/playlist/">Playlist</a>
  <a href="https://loudermx.com/contacto/">Contacto</a>
  <a href="https://loudermx.com/louderplus/">Louder+</a>
 </nav>
</header>
{body}
<footer class="site-footer">
 <div class="footer-inner">
  <div class="footer-brand"><img src="{asset_prefix}logo_louder.png" alt="Louder"><p>La única alternativa</p></div>
  <div><strong>Ubicación</strong><span>San Luis Potosí, México</span></div>
  <div><strong>Contacto</strong><a href="mailto:socialmedia@loudermx.com">socialmedia@loudermx.com</a></div>
  <div><strong>Louder+</strong><span>Ayuda a mantener Louder Radio, la web y nuestra cobertura musical.</span></div>
 </div>
 <div class="footer-links">
  <a href="https://loudermx.com/">Inicio</a><a href="https://loudermx.com/category/noticias/">Noticias</a>
  <a href="https://loudermx.com/nosotros/">Nosotros</a><a href="https://loudermx.com/radio/">Radio</a>
  <a href="/artistas/">Artistas</a><a href="https://loudermx.com/playlist/">Playlist</a>
  <a href="https://loudermx.com/contacto/">Contacto</a><a href="https://loudermx.com/louderplus/">Louder+</a>
 </div>
 <small>Louder Media © 2026.</small>
</footer>
<div class="louder-player" id="louder-static-player">
 <button class="player-play" type="button" data-radio-play aria-label="Reproducir Louder Radio">▶</button>
 <div class="player-cover"><img data-radio-art alt="" hidden><span data-radio-fallback>LOUDER</span></div>
 <div class="player-copy"><strong>Louder Radio LIVE</strong><span class="player-live">En vivo</span><div data-radio-track>Cargando canción actual…</div></div>
 <a class="player-artist-link" data-radio-artist-link href="/artistas/" hidden>Ver artista</a>
 <audio data-radio-audio preload="none" src="https://ec1.yesstreaming.net:2725/stream"></audio>
</div>
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
 data-plays="{int(artist.get("plays") or 0)}"
 data-first="{esc(artist.get("first_played") or "")}"
 data-last="{esc(artist.get("last_played") or "")}">
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
 <p>Bandas, solistas y colaboraciones reunidas desde Last.fm, MegaSeg y la programación de YesStreaming.</p>
 <div class="archive-actions">
  <label class="search"><span>Buscar</span><input type="search" data-artist-search placeholder="Buscar banda o artista" autocomplete="off"></label>
  <button class="button primary" type="button" data-shuffle>⤨ Otro artista</button>
  <select class="select" data-artist-sort aria-label="Ordenar artistas">
   <option value="az">A–Z</option>
   <option value="plays">Más reproducidos</option>
   <option value="first">Primera aparición</option>
   <option value="last">Última aparición</option>
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
    album_art: dict[str, Any],
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
   {source_stats_html(artist)}
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
 {tracks_html(artist, album_art)}
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
    raw_artists = [a for a in data.get("artists", []) if a.get("name")]
    artists, aliases = prepare_public_artists(raw_artists)
    by_slug = {a["slug"]: a for a in artists}
    gallery_store = {"artists": {}}
    if GALLERIES.exists():
        try:
            gallery_store = json.loads(GALLERIES.read_text(encoding="utf-8"))
        except Exception:
            gallery_store = {"artists": {}}
    galleries = gallery_store.get("artists") or {}

    art_store = {"albums": {}}
    if ALBUM_ART.exists():
        try:
            art_store = json.loads(ALBUM_ART.read_text(encoding="utf-8"))
        except Exception:
            art_store = {"albums": {}}
    album_art = art_store.get("albums") or {}

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
    shutil.copy2(ASSETS / "logo_louder.png", DOCS / "artistas" / "_assets" / "logo_louder.png")

    build_index(artists, galleries)
    for artist in artists:
        build_artist(artist, by_slug, galleries, album_art)

    index_payload = {
        "version": 1,
        "base_url": "https://artistas.loudermx.com/artistas/",
        "artists": [
            {"name": a.get("name", ""), "slug": a.get("slug", "")}
            for a in artists
        ],
        "aliases": aliases,
    }
    (DOCS / "artists-index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    (DOCS / "CNAME").write_text("artistas.loudermx.com\n", encoding="utf-8")
    (DOCS / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=./artistas/">'
        '<title>Louder</title><a href="./artistas/">Artistas Louder</a>',
        encoding="utf-8",
    )
    print(f"built {len(artists)} artists")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
