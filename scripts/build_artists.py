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

import enrichment_state as es

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "artists.json"
GALLERIES = ROOT / "data" / "galleries.json"
ALBUM_ART = ROOT / "data" / "album_art.json"
ARTIST_REVIEW = ROOT / "data" / "artist_review_overrides.json"
IDENTITY_ENRICHMENT = ROOT / "data" / "identity_enrichment.json"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"
GSC_VERIFY_DIR = ROOT / "search-console"
PUBLIC_ARTISTS_ORIGIN = "https://artistas.loudermx.com"


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def artist_key(value: str) -> str:
    raw = str(value or "").strip()
    normal = norm(raw)
    if normal:
        return normal
    # Preserve legitimate punctuation-only artist names such as !!!.
    return "symbol:" + "-".join(f"{ord(ch):x}" for ch in raw)


def slugify(value: str) -> str:
    normal = norm(value).replace(" ", "-").strip("-")
    if normal:
        return normal
    raw = str(value or "").strip()
    return "artist-" + "-".join(f"{ord(ch):x}" for ch in raw) if raw else "artista"


def load_artist_review() -> dict[str, Any]:
    if not ARTIST_REVIEW.exists():
        return {"aliases": {}, "exclude": {}, "preserve_exact": [], "collaborations": []}
    try:
        data = json.loads(ARTIST_REVIEW.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {"aliases": {}, "exclude": {}, "preserve_exact": [], "collaborations": []}


ARTIST_REVIEW_DATA = load_artist_review()
ARTIST_ALIASES = {
    str(k).strip(): str(v).strip()
    for k, v in (ARTIST_REVIEW_DATA.get("aliases") or {}).items()
    if str(k).strip() and str(v).strip()
}
ARTIST_EXCLUDES = {
    artist_key(str(k)): str(v)
    for k, v in (ARTIST_REVIEW_DATA.get("exclude") or {}).items()
    if str(k).strip()
}


def public_artist_name(value: str) -> str:
    """Apply only reviewed identity corrections; never guess from punctuation."""
    raw = re.sub(r"\s{2,}", " ", str(value or "").strip())
    if not raw:
        return ""
    return ARTIST_ALIASES.get(raw, raw)


NON_ARTIST_LABELS = {
    "mordaz",
    "the british corner",
    "louder radio",
    "louder mx",
    "loudermx",
    "louder",
    "louder station id",
    "station id",
    "promo louder",
    "promos louder",
    "jingle louder",
}


def is_public_artist_candidate(value: str) -> bool:
    raw = re.sub(r"\s{2,}", " ", str(value or "").strip())
    if not raw:
        return False
    key = artist_key(raw)
    if key in ARTIST_EXCLUDES:
        return False
    normalized = norm(raw)
    if normalized in NON_ARTIST_LABELS:
        return False
    # The British Corner is a Louder programme; historical playout metadata
    # produced several variants that must never become public artist profiles.
    if normalized.startswith("the british corner"):
        return False
    # Reject obvious import artifacts. Numeric-only names are allowed only
    # when explicitly reviewed as real artists in Louder's catalog.
    numeric_allowlist = {"424"}
    if re.fullmatch(r"\\d+", raw) and raw not in numeric_allowlist:
        return False
    # Corrupt playlist rows frequently arrive with a leading dot.
    if raw.startswith("."):
        return False
    # Filename/track-number artifacts such as 01_3_Doors_Down_ are not artists.
    if re.match(r"^\\d{1,3}_.+_?$", raw):
        return False
    return True


SPANISH_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def history_date_key(value: Any) -> tuple[int, int, int, int, int, int]:
    raw = str(value or "").strip().lower()
    if not raw:
        return (9999, 12, 31, 23, 59, 59)

    iso = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})(?:[t\s](\d{2}):(\d{2})(?::(\d{2}))?)?",
        raw,
    )
    if iso:
        return tuple(int(x or 0) for x in iso.groups(default="0"))  # type: ignore[return-value]

    es = re.search(
        r"(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s+(\d{4})"
        r"(?:\s*[·|-]\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
        raw,
    )
    if es:
        day, month, year, hour, minute, second = es.groups()
        return (
            int(year), SPANISH_MONTHS[month], int(day),
            int(hour or 0), int(minute or 0), int(second or 0),
        )

    return (9998, 12, 31, 23, 59, 59)


def earliest_date(values: list[Any]) -> str:
    rows = [str(v) for v in values if v]
    if not rows:
        return ""
    return min(rows, key=history_date_key)


def latest_date(values: list[Any]) -> str:
    rows = [str(v) for v in values if v]
    if not rows:
        return ""
    valid = [v for v in rows if history_date_key(v)[0] < 9998]
    if valid:
        return max(valid, key=history_date_key)
    return max(rows)



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

    out = raw
    qualifier = (
        r"(?:\d{4}\s+)?(?:remaster(?:ed)?|deluxe(?:\s+edition)?|"
        r"expanded(?:\s+edition)?|special(?:\s+edition)?|anniversary(?:\s+edition)?|"
        r"super\s+deluxe(?:\s+edition)?|reissue|remixed)"
        r"(?:\s+\d{4})?"
    )

    # Remove one or more edition/remaster suffixes, including combined forms
    # such as "(Deluxe Edition Remastered)".
    out = re.sub(
        r"\s*[\[(][^\])]*(?:remaster|deluxe|expanded|special edition|anniversary|reissue|remixed)[^\])]*[\])]\s*$",
        "",
        out,
        flags=re.I,
    ).strip()
    out = re.sub(rf"\s*[\-–—]\s*{qualifier}\s*$", "", out, flags=re.I).strip()
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

        current["plays"] = max(int(current.get("plays") or 0), int(track.get("plays") or 0))
        dates_first = [current.get("first_played"), track.get("first_played")]
        dates_last = [current.get("last_played"), track.get("last_played")]
        first = earliest_date(dates_first)
        last = latest_date(dates_last)
        if first:
            current["first_played"] = first
        if last:
            current["last_played"] = last
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

    # Historical playlist imports sometimes prefixed the artist with a two-digit
    # track number ("03 Haim", "09 The New Division"). Only strip that prefix
    # when the clean artist also exists independently in the catalog. This keeps
    # legitimate numeric names such as 30 Seconds to Mars or 31 Minutos intact.
    exact_names: dict[str, str] = {}
    for original in artists:
        if not isinstance(original, dict) or not original.get("name"):
            continue
        raw_name = str(original.get("name") or "").strip()
        if not is_public_artist_candidate(raw_name):
            continue
        reviewed_name = public_artist_name(raw_name)
        if re.match(r"^\d{2}\s+.+$", reviewed_name):
            continue
        exact_names.setdefault(artist_key(reviewed_name), reviewed_name)

    for original in artists:
        if not isinstance(original, dict) or not original.get("name"):
            continue
        raw_name = str(original.get("name") or "").strip()
        if not is_public_artist_candidate(raw_name):
            continue
        clean_name = public_artist_name(raw_name)
        numbered = re.match(r"^\d{2}\s+(.+)$", clean_name)
        if numbered:
            stripped_name = public_artist_name(numbered.group(1).strip())
            canonical_name = exact_names.get(artist_key(stripped_name))
            if canonical_name:
                clean_name = canonical_name
        key = artist_key(clean_name)
        candidate = dict(original)
        candidate["name"] = clean_name
        candidate["tracks"] = merge_public_tracks(candidate.get("tracks") or [])
        candidate["_canonical_exact"] = (raw_name == clean_name)
        if candidate["_canonical_exact"] and candidate.get("slug"):
            candidate["_canonical_slug"] = candidate.get("slug")
        current = buckets.get(key)
        if current is None:
            buckets[key] = candidate
        else:
            current["plays"] = max(int(current.get("plays") or 0), int(candidate.get("plays") or 0))
            current["tracks"] = merge_public_tracks((current.get("tracks") or []) + (candidate.get("tracks") or []))
            first = earliest_date([current.get("first_played"), candidate.get("first_played")])
            last = latest_date([current.get("last_played"), candidate.get("last_played")])
            if first:
                current["first_played"] = first
            if last:
                current["last_played"] = last
            if not current.get("image") and candidate.get("image"):
                current["image"] = candidate.get("image")
            if not current.get("bio") and candidate.get("bio"):
                current["bio"] = candidate.get("bio")
            current["sources"] = sorted(set((current.get("sources") or []) + (candidate.get("sources") or [])))
            if candidate.get("_canonical_exact"):
                current["_canonical_exact"] = True
                if candidate.get("slug"):
                    current["_canonical_slug"] = candidate.get("slug")
                if candidate.get("image"):
                    current["image"] = candidate.get("image")
                if candidate.get("bio"):
                    current["bio"] = candidate.get("bio")
        aliases[artist_key(raw_name)] = key
        aliases[artist_key(clean_name)] = key

    used: set[str] = set()
    key_to_slug: dict[str, str] = {}
    for key, artist in buckets.items():
        existing_slug = str(artist.get("_canonical_slug") or artist.get("slug") or "").strip()
        base = existing_slug or slugify(str(artist.get("name") or ""))
        slug = base
        n = 2
        while slug in used:
            slug = f"{base}-{n}"
            n += 1
        used.add(slug)
        artist["slug"] = slug
        artist.pop("_canonical_exact", None)
        artist.pop("_canonical_slug", None)
        key_to_slug[key] = slug

    alias_to_slug = {alias: key_to_slug[target] for alias, target in aliases.items() if target in key_to_slug}
    public = sorted(buckets.values(), key=lambda a: norm(str(a.get("name") or "")))
    return public, alias_to_slug


def number(value: Any) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except Exception:
        return "0"


def plays_label(value: Any) -> str:
    try:
        count = int(value or 0)
    except Exception:
        count = 0
    noun = "reproducción" if count == 1 else "reproducciones"
    return f"{number(count)} {noun}"


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


def apply_identity_fallbacks(galleries: dict[str, Any]) -> dict[str, Any]:
    """Merge conservative MusicBrainz/Wikipedia fallback data into gallery metadata.

    Existing Louder/TheAudioDB/fanart data always wins. The fallback only fills
    empty image, bio, genre, official-site and social fields and never renames an
    artist automatically.
    """
    if not IDENTITY_ENRICHMENT.exists():
        return galleries
    try:
        store = json.loads(IDENTITY_ENRICHMENT.read_text(encoding="utf-8"))
    except Exception:
        return galleries
    rows = store.get("artists") or {}
    if not isinstance(rows, dict):
        return galleries

    for slug, fallback in rows.items():
        if not isinstance(fallback, dict) or not fallback.get("verified"):
            continue
        gallery = galleries.setdefault(slug, {})
        image = str(fallback.get("image") or "").strip()
        if image and not gallery_images(gallery):
            gallery["images"] = [{
                "url": image,
                "preview": image,
                "source": str(fallback.get("image_source") or "MusicBrainz/Wikipedia"),
                "kind": "portrait",
                "valid": True,
                "validated_at": str(fallback.get("checked_at") or fallback.get("profile_checked_at") or ""),
            }]
            gallery["image_count"] = 1

        if not str(gallery.get("bio_es") or gallery.get("bio_en") or "").strip():
            bio = str(fallback.get("bio_en") or "").strip()
            if bio:
                gallery["bio_en"] = bio

        if not str(gallery.get("official_url") or "").strip():
            gallery["official_url"] = str(fallback.get("official_url") or "").strip()

        social = gallery.setdefault("social", {})
        fallback_social = fallback.get("social") or {}
        for key in ("facebook", "twitter", "instagram"):
            if not str(social.get(key) or "").strip():
                social[key] = str(fallback_social.get(key) or "").strip()

        if not str(gallery.get("genre") or "").strip():
            gallery["genre"] = str(fallback.get("genre") or "").strip()
        if not str(gallery.get("wikipedia_url") or "").strip():
            gallery["wikipedia_url"] = str(fallback.get("wikipedia_url") or "").strip()

        if fallback.get("verified") and not gallery.get("verified"):
            gallery["verified"] = True
            gallery["verification_source"] = str(fallback.get("verification_source") or "MusicBrainz")
            gallery["verification_title"] = str(fallback.get("canonical_name") or fallback.get("name") or "")
    return galleries


def apply_reviewed_profile_overrides(galleries: dict[str, Any]) -> dict[str, Any]:
    """Apply human-reviewed profile fields after automatic enrichment."""
    profiles = ARTIST_REVIEW_DATA.get("profiles") or {}
    if not isinstance(profiles, dict):
        return galleries
    for slug, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        gallery = galleries.setdefault(str(slug), {})
        bio_es = str(profile.get("bio_es") or "").strip()
        if bio_es:
            gallery["bio_es"] = bio_es
        image = str(profile.get("image") or "").strip()
        if image.startswith("https://"):
            gallery["images"] = [{
                "url": image,
                "preview": image,
                "source": "Louder reviewed override",
                "kind": "portrait",
            }]
            gallery["image_count"] = 1
        for key in ("official_url", "genre", "style", "country", "wikipedia_url"):
            value = str(profile.get(key) or "").strip()
            if value:
                gallery[key] = value
        social = profile.get("social") or {}
        if isinstance(social, dict):
            target = gallery.setdefault("social", {})
            for key in ("facebook", "twitter", "instagram"):
                value = str(social.get(key) or "").strip()
                if value:
                    target[key] = value
        gallery["verified"] = True
        gallery["verification_source"] = "Louder reviewed override"
        gallery["verification_title"] = str(profile.get("canonical_name") or slug)
    return galleries


def gallery_images(gallery: dict[str, Any] | None) -> list[dict[str, Any]]:
    return es.usable_gallery_images(gallery)


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


def social_links(artist: dict[str, Any], gallery: dict[str, Any] | None = None) -> str:
    gallery = gallery or {}
    links: list[str] = []
    seen: set[str] = set()

    official = str(artist.get("official_url") or gallery.get("official_url") or "").strip()
    if official:
        if not official.startswith(("http://", "https://")):
            official = "https://" + official.lstrip("/")
        links.append(f'<a href="{esc(official)}" target="_blank" rel="noopener">Web oficial</a>')
        seen.add(official)

    for item in artist.get("social") or []:
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if name and url and url not in seen:
            links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(name)}</a>')
            seen.add(url)

    fallback_social = gallery.get("social") or {}
    labels = {"facebook": "Facebook", "twitter": "X", "instagram": "Instagram"}
    for key, label in labels.items():
        url = str(fallback_social.get(key) or "").strip()
        if not url or url in seen:
            continue
        if not url.startswith(("http://", "https://")):
            url = "https://" + url.lstrip("/")
        links.append(f'<a href="{esc(url)}" target="_blank" rel="noopener">{label}</a>')
        seen.add(url)

    return "".join(links)


def album_art_key(artist: str, album: str) -> str:
    return norm(artist) + "|" + norm(album)


def track_artwork_key(artist: str, track: dict[str, Any]) -> str:
    album = str(track.get("album") or "").strip()
    placeholder = {
        "", "album no identificado", "album desconocido", "unknown album",
        "recien incorporada al historial", "sin album", "no album",
        "programacion yesstreaming", "yesstreaming", "programacion", "programming",
    }
    if norm(album) in placeholder:
        return "track|" + norm(artist) + "|" + norm(str(track.get("title") or ""))
    return album_art_key(artist, album)


def track_album_bucket(track: dict[str, Any]) -> tuple[str, str]:
    """Return a clean album bucket; singles/placeholders/technical labels go to Otras."""
    title = canonical_track_title(str(track.get("title") or "")).strip()
    album_raw = str(track.get("album") or "").strip()

    # Collapse common edition suffixes so one album does not appear several times.
    album_raw = re.sub(
        r"\s*[\[(](?:bonus tracks?|deluxe(?: edition)?|expanded(?: edition)?|"
        r"special(?: edition)?|anniversary(?: edition)?|remaster(?:ed)?(?: \d{4})?|"
        r"super deluxe(?: edition)?)[^\])]*[\])]\s*$",
        "",
        album_raw,
        flags=re.I,
    ).strip()
    album_raw = re.sub(
        r"\s*[-–—]\s*(?:bonus tracks?|deluxe(?: edition)?|expanded(?: edition)?|"
        r"special(?: edition)?|anniversary(?: edition)?|remaster(?:ed)?(?: \d{4})?)\s*$",
        "",
        album_raw,
        flags=re.I,
    ).strip()

    raw = canonical_album(album_raw).strip()
    normalized = norm(raw)
    title_norm = norm(title)

    other_labels = {
        "", "album no identificado", "album desconocido", "unknown album",
        "recien incorporada al historial", "sin album", "no album",
        "single", "sencillo", "otros", "otras", "programacion yesstreaming",
        "yesstreaming", "programacion", "programming", "radio edit",
    }
    if normalized in other_labels:
        return ("__other__", "Otras")

    # If the release field is effectively the song title, it is usually a single,
    # not a parent album. Keep the song, but group it under Otras.
    if title_norm and normalized == title_norm:
        return ("__other__", "Otras")

    # Covers/promotional containers and technical release labels are not useful
    # as album navigation.
    non_album_patterns = (
        r"\bcovered\b",
        r"\bcover version\b",
        r"\btribute\b",
        r"\bpromo\b",
        r"\bprogramacion\b",
        r"\byesstreaming\b",
        r"\bradio edit\b",
        r"\bsingle version\b",
    )
    if any(re.search(pattern, normalized, flags=re.I) for pattern in non_album_patterns):
        return ("__other__", "Otras")

    return (normalized or "__other__", raw or "Otras")


def track_album_filters(tracks: list[dict[str, Any]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    albums: list[tuple[str, str]] = []
    has_other = False
    for track in tracks:
        key, label = track_album_bucket(track)
        if key == "__other__":
            has_other = True
            continue
        if key in seen:
            continue
        seen.add(key)
        albums.append((key, label))
    albums.sort(key=lambda item: norm(item[1]))
    if has_other:
        albums.append(("__other__", "Otras"))
    return albums


def tracks_html(artist: dict[str, Any], album_art: dict[str, Any]) -> str:
    tracks = artist.get("tracks") or []
    if not tracks:
        return '<div class="note">Todavía no hay canciones consolidadas para esta ficha.</div>'

    out: list[str] = ['<div class="track-list" data-track-list>']
    for track_index, track in enumerate(tracks):
        album = str(track.get("album") or "")
        album_key, album_label = track_album_bucket(track)
        cached = album_art.get(track_artwork_key(str(artist.get("name") or ""), track), {})
        # Never render an unvalidated remote cover. Historical track artwork is
        # validated by enrich_album_art.py and copied into this cache first.
        artwork = ""
        if (
            isinstance(cached, dict)
            and cached.get("status") == "complete"
            and cached.get("validated") is True
            and cached.get("url")
        ):
            artwork = str(cached.get("url") or "")
        fallback_cover = (
            f'<span class="cover-fallback" data-missing-cover '
            f'data-artist="{esc(artist.get("name"))}" data-title="{esc(track.get("title"))}">Louder</span>'
        )
        cover = (
            f'<img src="{esc(artwork)}" alt="" loading="lazy" decoding="async" '
            f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'grid\'">'
            f'<span class="cover-fallback" style="display:none" data-missing-cover '
            f'data-artist="{esc(artist.get("name"))}" data-title="{esc(track.get("title"))}">Louder</span>'
            if artwork
            else fallback_cover
        )
        hidden = " hidden" if track_index >= 10 else ""
        out.append(
            f'''<article class="track-row" data-track{hidden}
 data-title="{esc(track.get("title"))}"
 data-first="{esc(track.get("first_played"))}"
 data-last="{esc(track.get("last_played"))}"
 data-plays="{int(track.get("plays") or 0)}"
 data-album="{esc(album_key)}">
 <div class="track-cover">{cover}</div>
 <div class="track-main">
  <div class="track-title">{esc(track.get("title"))}</div>
  <div class="track-album">{esc(album_label)}</div>
 </div>
 <div class="track-dates">
  <div><span>Primera</span><strong>{esc(track.get("first_played") or "—")}</strong></div>
  <div><span>Última</span><strong>{esc(track.get("last_played") or "—")}</strong></div>
 </div>
 <div class="track-plays"><strong>{number(track.get("plays"))}</strong><span>plays</span></div>
</article>'''
        )
    out.append("</div>")
    if len(tracks) > 10:
        pages = (len(tracks) + 9) // 10
        page_buttons = "".join(
            f'<button class="lmx-track-page{" active" if page == 1 else ""}" type="button" data-page="{page}">{page}</button>'
            for page in range(1, min(pages, 5) + 1)
        )
        out.append(
            '<nav class="lmx-track-pagination" data-track-pagination aria-label="Paginación de canciones">'
            f'<div class="lmx-track-pagination-info">1–10 de {len(tracks)} canciones</div>'
            '<div class="lmx-track-pagination-buttons">'
            '<button class="lmx-track-page" type="button" data-page="0" disabled aria-label="Página anterior">←</button>'
            + page_buttons +
            f'<button class="lmx-track-page" type="button" data-page="2" aria-label="Página siguiente">→</button>'
            '</div></nav>'
        )
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
    structured_data: dict[str, Any] | None = None,
) -> str:
    asset_prefix = ("../" * max(depth - 1, 0)) + "_assets/"
    desc = description or "Archivo de artistas programados en Louder Radio."
    canonical = PUBLIC_ARTISTS_ORIGIN + canonical_path
    structured_json = (
        '<script type="application/ld+json">' +
        json.dumps(structured_data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") +
        "</script>"
        if structured_data else ""
    )
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
<meta property="og:site_name" content="Louder">
{f'<meta property="og:image" content="{esc(social_image)}">' if social_image else ''}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
{f'<meta name="twitter:image" content="{esc(social_image)}">' if social_image else ''}
{structured_json}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{asset_prefix}artistas.css">
<script defer src="{asset_prefix}artistas.js"></script>
</head>
<body>
<header class="site-header">
 <div class="header-inner">
  <a class="brand" href="https://loudermx.com/" aria-label="Louder"><img src="{asset_prefix}logo_louder.png" alt="Louder"></a>
  <button class="nav-toggle" type="button" aria-label="Abrir menú" aria-expanded="false" data-nav-toggle>☰</button>
  <nav class="main-nav" data-main-nav aria-label="Navegación principal">
   <a href="https://loudermx.com/">Inicio</a>
   <a href="https://loudermx.com/noticias/">Noticias</a>
   <a href="https://loudermx.com/nosotros/">Nosotros</a>
   <a href="https://loudermx.com/radio/">Radio</a>
   <a class="active" href="{("../" if depth > 1 else "./")}">Artistas</a>
   <a href="https://loudermx.com/playlist/">Playlist</a>
   <a href="https://loudermx.com/contacto/">Contacto</a>
   <a href="https://loudermx.com/louderplus/">Louder+</a>
  </nav>
  <div class="header-actions">
   <div class="header-social" aria-label="Redes de Louder">
    <a href="https://www.facebook.com/LouderMx" target="_blank" rel="noopener" aria-label="Facebook">f</a>
    <a href="https://twitter.com/mxlouder" target="_blank" rel="noopener" aria-label="X">𝕏</a>
    <a href="https://www.instagram.com/loudermx/" target="_blank" rel="noopener" aria-label="Instagram">◎</a>
    <a href="https://www.tiktok.com/@loudermx" target="_blank" rel="noopener" aria-label="TikTok">♪</a>
    <a href="https://www.youtube.com/@ldrmx" target="_blank" rel="noopener" aria-label="YouTube">▶</a>
   </div>
   <button class="header-search" type="button" aria-label="Buscar en Louder" data-site-search>⌕</button>
  </div>
 </div>
 <form class="site-search-panel" action="https://loudermx.com/" method="get" data-site-search-panel hidden>
  <label><span>Buscar en Louder</span><input type="search" name="s" placeholder="Buscar en Louder…" autocomplete="off"></label>
  <button type="submit">Buscar</button>
 </form>
</header>
{body}
<footer class="site-footer">
 <div class="footer-inner">
  <div class="footer-brand">
   <img src="{asset_prefix}logo_louder.png" alt="Louder">
   <h2>La única alternativa</h2>
  </div>
  <div class="footer-column"><strong>Ubicación</strong><span>San Luis Potosí,<br>San Luis Potosí,<br>México</span></div>
  <div class="footer-column"><strong>Contacto</strong><a href="mailto:socialmedia@loudermx.com">socialmedia@loudermx.com</a></div>
  <div class="footer-column footer-plus"><a href="https://loudermx.com/louderplus/"><strong>Louder+</strong></a><span>Ayuda a mantener Louder Radio, la web y nuestra cobertura musical.</span></div>
 </div>
 <div class="footer-bottom">
  <nav class="footer-links" aria-label="Navegación de pie">
   <a href="https://loudermx.com/">Inicio</a><a href="https://loudermx.com/noticias/">Noticias</a>
   <a href="https://loudermx.com/nosotros/">Nosotros</a><a href="https://loudermx.com/radio/">Radio</a>
   <a href="/artistas/">Artistas</a><a href="https://loudermx.com/playlist/">Playlist</a>
   <a href="https://loudermx.com/contacto/">Contacto</a><a href="https://loudermx.com/louderplus/">Louder+</a>
  </nav>
  <small>Louder Media © 2026.</small>
 </div>
</footer>
<div class="louder-player" id="persistent-louder-radio" aria-label="Louder Radio">
 <button class="player-play" type="button" data-radio-play aria-label="Reproducir Louder Radio">▶</button>
 <div class="player-cover"><img data-radio-art alt="" hidden><span data-radio-fallback>LOUDER</span></div>
 <div class="player-copy">
  <div class="player-title"><strong>Louder Radio LIVE</strong><span class="player-live">En vivo</span></div>
  <div class="player-track" data-radio-track>Cargando canción actual…</div>
 </div>
 <a class="player-artist-link" data-radio-artist-link href="/artistas/" hidden>Ver artista</a>
 <a class="player-donate" href="https://ko-fi.com/loudermx" target="_blank" rel="noopener">Donar</a>
 <label class="player-volume" aria-label="Volumen"><span>VOL</span><input type="range" min="0" max="1" step="0.05" value="0.8" data-radio-volume></label>
 <audio data-radio-audio preload="none" src="https://ec1.yesstreaming.net:2725/stream"></audio>
</div></body>
</html>'''


def build_index(artists: list[dict[str, Any]], galleries: dict[str, Any]) -> None:
    cards: list[str] = []
    initial = artists[:120]
    for artist in initial:
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
 <p>Bandas, solistas y colaboraciones que han pasado por la programación de Louder, reunidas en un solo archivo.</p>
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
 <p class="count"><strong data-visible-count>{len(initial)}</strong> de <span data-total-count>{len(artists)}</span> artistas</p>
</section>
<section class="artist-grid" data-artist-grid>
{"".join(cards)}
</section>
<div class="archive-more"><button class="button" type="button" data-load-more>Mostrar más artistas</button></div>
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
    initials = str(name[:2] or "?").upper()
    hero_fallback = f'<span class="artist-art-fallback">{esc(initials)}</span>'
    hero_image = (
        f'<img src="{esc(image)}" alt="{esc(name)}" fetchpriority="high" decoding="async" '
        f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'grid\'">'
        f'<span class="artist-art-fallback" style="display:none">{esc(initials)}</span>'
        if image
        else hero_fallback
    )
    backdrop = (
        f'<div class="artist-backdrop" style="background-image:url(&quot;{esc(image)}&quot;)"></div>'
        if image
        else ""
    )
    genre_values = list(artist.get("genres") or [])
    if not genre_values:
        for value in (gallery.get("genre"), gallery.get("style")):
            value = str(value or "").strip()
            if value and value not in genre_values:
                genre_values.append(value)
    genres = "".join(f'<span class="genre">{esc(g)}</span>' for g in genre_values[:8])
    bio = str(artist.get("bio") or gallery.get("bio_es") or gallery.get("bio_en") or "").strip()
    bio_html = "".join(
        f"<p>{esc(p)}</p>" for p in re.split(r"\n\s*\n", bio) if p.strip()
    )
    if not bio_html:
        tracks = [t for t in (artist.get("tracks") or []) if isinstance(t, dict) and t.get("title")]
        track_count = len(tracks)
        plays = int(artist.get("plays") or 0)
        first = str(artist.get("first_played") or "").strip()
        last = str(artist.get("last_played") or "").strip()
        pieces = [f"{name} forma parte del Archivo Louder"]
        if first:
            pieces[0] += f" desde {first}"
        pieces[0] += "."
        if track_count:
            noun = "una canción" if track_count == 1 else f"{track_count} canciones"
            sentence = f"En el histórico registra {noun} y {plays_label(plays)}"
            if last:
                sentence += f"; su aparición más reciente fue {last}"
            sentence += "."
            pieces.append(sentence)
            titles = [str(t.get("title") or "").strip() for t in tracks[:3] if str(t.get("title") or "").strip()]
            if titles:
                quoted = ", ".join(f"“{title}”" for title in titles)
                pieces.append(("La canción registrada es " if len(titles) == 1 else "Entre las canciones registradas están ") + quoted + ".")
        elif last:
            pieces.append(f"Su aparición más reciente registrada fue {last}.")
        if genre_values:
            pieces.append("Etiquetas disponibles: " + ", ".join(str(g) for g in genre_values[:4]) + ".")
        bio_html = "<p>" + esc(" ".join(pieces)) + "</p>"

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
   <div class="social">{social_links(artist, gallery)}</div>
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
  <label class="album-filter">
   <span>Álbum</span>
   <select data-track-album-filter>
    <option value="__all__">Todos los álbumes</option>
    {"".join(f'<option value="{esc(key)}">{esc(label)}</option>' for key, label in track_album_filters(artist.get("tracks") or []))}
   </select>
  </label>
 </div>
 {tracks_html(artist, album_art)}
</section>

<section class="section">
 <div class="section-title"><h2>Artistas relacionados</h2></div>
 {related_html(artist, by_slug, galleries)}
</section>
</main>'''

    out = DOCS / "artistas" / "musica" / artist["slug"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    track_count = len(artist.get("tracks") or [])
    track_label = "1 canción" if track_count == 1 else f"{track_count} canciones"
    description = (
        f"Archivo de {name} en Louder: {track_label}, {plays_label(artist.get('plays'))}; "
        "primera y última aparición, biografía y artistas relacionados."
    )
    breadcrumbs = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Artistas",
                "item": PUBLIC_ARTISTS_ORIGIN + "/artistas/",
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": name,
            },
        ],
    }
    out.write_text(
        page_shell(
            f"{name}: canciones e historial | Louder",
            body,
            depth=3,
            description=description,
            canonical_path=f"/artistas/musica/{artist['slug']}/",
            social_image=image,
            structured_data=breadcrumbs,
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
    galleries = apply_identity_fallbacks(galleries)
    galleries = apply_reviewed_profile_overrides(galleries)

    art_store = {"albums": {}}
    if ALBUM_ART.exists():
        try:
            art_store = json.loads(ALBUM_ART.read_text(encoding="utf-8"))
        except Exception:
            art_store = {"albums": {}}
    album_art = art_store.get("albums") or {}

    public_track_count = sum(len(a.get("tracks") or []) for a in artists)
    missing_artist_images = sum(
        1 for a in artists if not preferred_image(a, galleries.get(a.get("slug", "")))
    )
    missing_bios = 0
    verified_artists = 0
    for a in artists:
        gallery = galleries.get(a.get("slug", "")) or {}
        if not str(a.get("bio") or gallery.get("bio_es") or gallery.get("bio_en") or "").strip():
            missing_bios += 1
        if gallery.get("verified"):
            verified_artists += 1
    rejected_nonartists = sum(
        1 for a in raw_artists
        if not is_public_artist_candidate(str(a.get("name") or ""))
    )
    suspicious_prefixes = [
        a.get("name", "") for a in artists
        if re.match(r"^[\s._·•?¿!¡–—-]+", str(a.get("name") or ""))
    ]
    missing_track_art = 0
    for a in artists:
        artist_name = str(a.get("name") or "")
        for track in a.get("tracks") or []:
            album = str(track.get("album") or "").strip()
            cached = album_art.get(track_artwork_key(artist_name, track), {})
            if not (
                isinstance(cached, dict)
                and cached.get("status") == "complete"
                and cached.get("validated") is True
                and cached.get("url")
            ):
                missing_track_art += 1
    print(
        "public_audit "
        f"raw_artists={len(raw_artists)} public_artists={len(artists)} "
        f"collapsed={len(raw_artists)-len(artists)} tracks={public_track_count} "
        f"missing_artist_images={missing_artist_images} missing_bios={missing_bios} "
        f"missing_track_art={missing_track_art} verified_artists={verified_artists} "
        f"rejected_nonartists={rejected_nonartists} suspicious_prefixes={len(suspicious_prefixes)}"
    )

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
    if GSC_VERIFY_DIR.exists():
        for verify_file in GSC_VERIFY_DIR.glob("google*.html"):
            shutil.copy2(verify_file, DOCS / verify_file.name)
    shutil.copy2(ASSETS / "artistas.css", DOCS / "artistas" / "_assets" / "artistas.css")
    shutil.copy2(ASSETS / "artistas.js", DOCS / "artistas" / "_assets" / "artistas.js")
    shutil.copy2(ASSETS / "logo_louder.png", DOCS / "artistas" / "_assets" / "logo_louder.png")

    # Build the public artist archive and each canonical artist profile.
    build_index(artists, galleries)
    for artist in artists:
        build_artist(artist, by_slug, galleries, album_art)

    index_payload = {
        "version": 2,
        "base_url": PUBLIC_ARTISTS_ORIGIN + "/artistas/musica/",
        "artists": [
            {
                "name": a.get("name", ""),
                "slug": a.get("slug", ""),
                "plays": int(a.get("plays") or 0),
                "first": a.get("first_played") or "",
                "last": a.get("last_played") or "",
                "image": preferred_image(a, galleries.get(a.get("slug", ""))),
            }
            for a in artists
        ],
        "aliases": aliases,
    }
    (DOCS / "artists-index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    link_map = {
        artist_key(a.get("name", "")): {
            "name": a.get("name", ""),
            "slug": a.get("slug", ""),
            "plays": int(a.get("plays") or 0),
        }
        for a in artists
        if a.get("name") and a.get("slug")
    }
    (DOCS / "artist-links.js").write_text(
        "window.LMX_ARTIST_LINKS=" +
        json.dumps(link_map, ensure_ascii=False, separators=(",", ":")) +
        ";window.dispatchEvent(new Event('lmx:artist-links-ready'));\n",
        encoding="utf-8",
    )

    def home_item(a: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": a.get("name", ""),
            "slug": a.get("slug", ""),
            "plays": int(a.get("plays") or 0),
            "first": a.get("first_played") or "",
            "last": a.get("last_played") or "",
            "image": preferred_image(a, galleries.get(a.get("slug", ""))),
        }

    eligible_home = [
        a for a in artists
        if is_public_artist_candidate(str(a.get("name") or ""))
    ]

    # "En rotación" must reflect the actual latest YesStreaming playout order,
    # not the artist's latest date in the consolidated historical archive.
    public_by_name = {
        norm(str(a.get("name") or "")): a
        for a in eligible_home
        if norm(str(a.get("name") or ""))
    }
    recent_home: list[dict[str, Any]] = []
    recent_slugs: set[str] = set()
    for event in data.get("live_recent_rotation") or []:
        live_name = norm(str(event.get("artist") or ""))
        artist = public_by_name.get(live_name)
        if not artist:
            continue
        slug = str(artist.get("slug") or "")
        if not slug or slug in recent_slugs:
            continue
        # Only show fully usable cards on the landing page.
        if not preferred_image(artist, galleries.get(slug)):
            continue
        recent_home.append(artist)
        recent_slugs.add(slug)
        if len(recent_home) == 3:
            break

    # Safe fallback while the first live-sync run after deployment is pending.
    if len(recent_home) < 3:
        for artist in sorted(
            eligible_home,
            key=lambda a: history_date_key(a.get("last_played")),
            reverse=True,
        ):
            slug = str(artist.get("slug") or "")
            if not slug or slug in recent_slugs:
                continue
            if not preferred_image(artist, galleries.get(slug)):
                continue
            recent_home.append(artist)
            recent_slugs.add(slug)
            if len(recent_home) == 3:
                break

    popular_home = sorted(
        eligible_home,
        key=lambda a: (int(a.get("plays") or 0), history_date_key(a.get("last_played"))),
        reverse=True,
    )[:18]
    new_home = sorted(
        eligible_home,
        key=lambda a: history_date_key(a.get("first_played")),
        reverse=True,
    )[:12]
    home_payload = {
        "version": 1,
        "total": len(artists),
        "recent": [home_item(a) for a in recent_home],
        "popular": [home_item(a) for a in popular_home],
        "new": [home_item(a) for a in new_home],
    }
    track_pager_js = r"""
;(() => {
  if (!window.LMX_NATIVE_DETAIL_UX_READY) {
    window.LMX_NATIVE_DETAIL_UX_READY = true;

    const style = document.createElement("style");
    style.id = "lmx-native-detail-ux-style";
    style.textContent = `
      body.lmx-artist-detail-open #lmx-native-artists > .lmxn-hero{display:none!important}
      body.lmx-artist-detail-open #lmx-native-artists{width:100%!important;max-width:none!important;margin:0!important;padding:12px 0 120px!important}

      body.lmx-artist-detail-open #lmx-native-artists [data-lmxn-detail]{width:100%!important;max-width:none!important;margin:0!important;padding:0!important}
      body.lmx-artist-detail-open #lmx-native-artists [data-lmxn-detail] > .lmxn-back{margin:0 clamp(18px,3vw,42px) 18px!important}

      body.lmx-artist-detail-open #lmx-native-artists [data-lmxn-detail] main.wrap{
        width:100%!important;
        max-width:none!important;
        margin:0!important;
        padding:0!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .artist-hero{
        width:100%!important;
        margin:0!important;
        padding:0!important;
        border:0!important;
        border-radius:0!important;
        background:transparent!important;
        overflow:visible!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .artist-backdrop{display:none!important}

      body.lmx-artist-detail-open #lmx-native-artists .artist-hero-inner{
        display:flex!important;
        flex-direction:column!important;
        width:100%!important;
        gap:0!important;
        padding:0!important;
        margin:0!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .artist-art{
        order:1!important;
        display:block!important;
        width:100%!important;
        max-width:none!important;
        height:auto!important;
        aspect-ratio:16/7!important;
        margin:0!important;
        border-radius:0!important;
        overflow:hidden!important;
        background:#111!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .artist-art img{
        width:100%!important;
        height:100%!important;
        display:block!important;
        object-fit:cover!important;
        object-position:center!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .artist-copy{
        order:2!important;
        align-self:stretch!important;
        width:100%!important;
        max-width:none!important;
        box-sizing:border-box!important;
        margin:0!important;
        padding:30px clamp(18px,4vw,56px) 0!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .artist-copy h1{
        margin:8px 0 18px!important;
        padding:0!important;
        max-width:none!important;
        font-size:clamp(48px,8vw,96px)!important;
        line-height:.92!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .genres,
      body.lmx-artist-detail-open #lmx-native-artists .artist-actions,
      body.lmx-artist-detail-open #lmx-native-artists .social{
        width:100%!important;
        max-width:none!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .metrics{
        width:100%!important;
        max-width:900px!important;
        grid-template-columns:repeat(3,minmax(0,1fr))!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .about,
      body.lmx-artist-detail-open #lmx-native-artists .section,
      body.lmx-artist-detail-open #lmx-native-artists .source-stats{
        width:auto!important;
        max-width:none!important;
        margin-left:clamp(18px,4vw,56px)!important;
        margin-right:clamp(18px,4vw,56px)!important;
      }

      body.lmx-artist-detail-open #lmx-native-artists .bio{max-width:980px!important}

      @media(max-width:760px){
        body.lmx-artist-detail-open #lmx-native-artists .artist-art{aspect-ratio:16/9!important}
        body.lmx-artist-detail-open #lmx-native-artists .artist-copy{padding:22px 18px 0!important}
        body.lmx-artist-detail-open #lmx-native-artists .metrics{grid-template-columns:1fr!important;max-width:none!important}
        body.lmx-artist-detail-open #lmx-native-artists .about,
        body.lmx-artist-detail-open #lmx-native-artists .section,
        body.lmx-artist-detail-open #lmx-native-artists .source-stats{margin-left:18px!important;margin-right:18px!important}
      }
    `;
    document.head.appendChild(style);

    const syncDetailState = () => {
      const detail = document.querySelector("#lmx-native-artists [data-lmxn-detail]");
      document.body.classList.toggle("lmx-artist-detail-open", !!detail && !detail.hidden);
    };

    new MutationObserver(syncDetailState).observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["hidden", "class"]
    });
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", syncDetailState, { once: true });
    } else {
      syncDetailState();
    }
  }

  if (window.LMX_TRACK_PAGER_READY) return;
  window.LMX_TRACK_PAGER_READY = true;
  const PER_PAGE = 10;

  function ensureStyle() {
    if (document.getElementById("lmx-track-pagination-style")) return;
    const style = document.createElement("style");
    style.id = "lmx-track-pagination-style";
    style.textContent = `
      [data-track][hidden]{display:none!important}
      .album-filter{display:flex!important;align-items:center!important;gap:10px!important;min-width:300px!important}
      .album-filter span{display:block!important;font-size:11px!important;color:#777!important;text-transform:uppercase!important;letter-spacing:.08em!important;white-space:nowrap!important}
      .album-filter select,[data-track-album-filter]{
        display:block!important;
        visibility:visible!important;
        opacity:1!important;
        position:static!important;
        appearance:auto!important;
        -webkit-appearance:menulist!important;
        width:260px!important;
        min-width:220px!important;
        max-width:360px!important;
        height:42px!important;
        border:1px solid #343434!important;
        border-radius:999px!important;
        background:#111!important;
        color:#f3f3f3!important;
        padding:0 14px!important;
        font:inherit!important;
        font-size:12px!important;
        line-height:42px!important;
        cursor:pointer!important;
        pointer-events:auto!important;
      }
      .album-filter select option,[data-track-album-filter] option{background:#111!important;color:#f3f3f3!important}
      .lmx-track-pagination{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:18px;flex-wrap:wrap}
      .lmx-track-pagination-info{color:#777;font-size:11px}
      .lmx-track-pagination-buttons{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
      .lmx-track-page{min-width:36px;height:36px;padding:0 11px;border:1px solid #2b2b2b;border-radius:999px;background:#0d0d0d;color:#ccc;font:inherit;font-size:11px;font-weight:800;cursor:pointer}
      .lmx-track-page:hover{border-color:#666;color:#fff}
      .lmx-track-page.active{background:#f2f2f2;border-color:#f2f2f2;color:#050505}
      .lmx-track-page:disabled{opacity:.35;cursor:default}
      @media(max-width:560px){.lmx-track-pagination{align-items:flex-start;flex-direction:column}.lmx-track-pagination-buttons{width:100%;overflow-x:auto;flex-wrap:nowrap;padding-bottom:4px}}
    `;
    document.head.appendChild(style);
  }

  function setup(list) {
    if (!list || list.dataset.lmxPaged === "1") return;
    const initialRows = Array.from(list.querySelectorAll("[data-track]"));
    if (initialRows.length <= PER_PAGE) return;
    list.dataset.lmxPaged = "1";
    ensureStyle();

    let page = 1;
    let nav = list.nextElementSibling?.matches?.("[data-track-pagination]") ? list.nextElementSibling : null;
    if (!nav) {
      nav = document.createElement("nav");
      nav.className = "lmx-track-pagination";
      nav.dataset.trackPagination = "1";
      nav.setAttribute("aria-label", "Paginación de canciones");
      nav.innerHTML = '<div class="lmx-track-pagination-info"></div><div class="lmx-track-pagination-buttons"></div>';
      list.insertAdjacentElement("afterend", nav);
    }
    const info = nav.querySelector(".lmx-track-pagination-info");
    const buttons = nav.querySelector(".lmx-track-pagination-buttons");

    function render() {
      const allRows = Array.from(list.querySelectorAll("[data-track]"));
      const section = list.closest(".section") || list.parentElement;
      const albumFilter = section.querySelector("[data-track-album-filter]");
      const selectedAlbum = albumFilter?.value || "__all__";
      const rows = allRows.filter((row) => selectedAlbum === "__all__" || row.dataset.album === selectedAlbum);
      const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
      page = Math.min(Math.max(1, page), pages);
      const start = (page - 1) * PER_PAGE;
      const end = Math.min(start + PER_PAGE, rows.length);
      allRows.forEach((row) => { row.hidden = true; });
      rows.forEach((row, i) => { row.hidden = i < start || i >= end; });
      info.textContent = rows.length ? `${start + 1}–${end} de ${rows.length} canciones` : "0 canciones";

      const items = [];
      if (pages > 1) {
        items.push(`<button class="lmx-track-page" type="button" data-page="${page - 1}" ${page === 1 ? "disabled" : ""} aria-label="Página anterior">←</button>`);
        const windowSize = 5;
        let from = Math.max(1, page - 2);
        let to = Math.min(pages, from + windowSize - 1);
        from = Math.max(1, to - windowSize + 1);
        for (let n = from; n <= to; n++) {
          items.push(`<button class="lmx-track-page ${n === page ? "active" : ""}" type="button" data-page="${n}">${n}</button>`);
        }
        items.push(`<button class="lmx-track-page" type="button" data-page="${page + 1}" ${page === pages ? "disabled" : ""} aria-label="Página siguiente">→</button>`);
      }
      buttons.innerHTML = items.join("");
      nav.hidden = pages <= 1;
    }

    nav.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-page]");
      if (!btn || btn.disabled) return;
      page = Number(btn.dataset.page || 1);
      render();
      const top = list.getBoundingClientRect().top + window.scrollY - 120;
      window.scrollTo({ top, behavior: "smooth" });
    });

    const section = list.closest(".section") || list.parentElement;
    const albumFilter = section.querySelector("[data-track-album-filter]");
    albumFilter?.addEventListener("change", () => {
      page = 1;
      render();
      const top = list.getBoundingClientRect().top + window.scrollY - 140;
      window.scrollTo({ top, behavior: "smooth" });
    });

    render();
  }

  function scan() {
    document.querySelectorAll(".lmx-native-detail [data-track-list], main.wrap [data-track-list], #lmx-native-artists [data-track-list]").forEach(setup);
  }

  document.addEventListener("change", (event) => {
    const select = event.target.closest?.("[data-track-album-filter]");
    if (!select) return;
    const section = select.closest(".section") || select.parentElement?.parentElement;
    const list = section?.querySelector?.("[data-track-list]");
    if (!list) return;
    // Re-run setup if the profile was injected after the first scan.
    if (list.dataset.lmxPaged !== "1") setup(list);
    const nav = list.nextElementSibling?.matches?.("[data-track-pagination], .lmx-track-pagination")
      ? list.nextElementSibling
      : null;
    // Trigger the component's own change handler if already attached.
    if (!nav && list.querySelectorAll("[data-track]").length > PER_PAGE) setup(list);
  }, true);

  new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", scan, { once: true });
  else scan();
})();
"""
    (DOCS / "artists-home.js").write_text(
        "window.LMX_ARTISTS_HOME=" +
        json.dumps(home_payload, ensure_ascii=False, separators=(",", ":")) +
        ";window.dispatchEvent(new Event('lmx:artists-home-ready'));\n" +
        track_pager_js,
        encoding="utf-8",
    )

    sitemap_urls = []
    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(
        f"  <url><loc>{esc(url)}</loc></url>\n" for url in sitemap_urls
    ) + "</urlset>\n"
    (DOCS / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (DOCS / "artistas" / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (DOCS / "robots.txt").write_text(
        "User-agent: *\\nAllow: /\\n" +
        f"Sitemap: {PUBLIC_ARTISTS_ORIGIN}/sitemap.xml\\n",
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
