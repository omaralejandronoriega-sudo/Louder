#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import build_artists as ba
import enrichment_state as es

ROOT = Path(__file__).resolve().parents[1]
ARTISTS = ROOT / "data" / "artists.json"
GALLERIES = ROOT / "data" / "galleries.json"
ALBUM_ART = ROOT / "data" / "album_art.json"
OUT_JSON = ROOT / "diagnostics" / "artistas-audit.json"
OUT_MD = ROOT / "diagnostics" / "artistas-audit.md"


def load(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def gallery_for(galleries: dict[str, Any], artist: dict[str, Any]) -> dict[str, Any]:
    row = galleries.get(str(artist.get("slug") or ""))
    return row if isinstance(row, dict) else {}


def effective_bio(artist: dict[str, Any], gallery: dict[str, Any]) -> str:
    return str(artist.get("bio") or gallery.get("bio_es") or gallery.get("bio_en") or "").strip()


def effective_image(artist: dict[str, Any], gallery: dict[str, Any]) -> str:
    return ba.preferred_image(artist, gallery)


def effective_social(artist: dict[str, Any], gallery: dict[str, Any]) -> bool:
    if has_text(artist.get("official_url")) or has_text(gallery.get("official_url")):
        return True
    for item in artist.get("social") or []:
        if isinstance(item, dict) and has_text(item.get("url")):
            return True
    gs = gallery.get("social") or {}
    return any(has_text(gs.get(k)) for k in ("facebook", "twitter", "instagram"))


def effective_genre(artist: dict[str, Any], gallery: dict[str, Any]) -> bool:
    if any(has_text(x) for x in (artist.get("genres") or [])):
        return True
    return has_text(gallery.get("genre")) or has_text(gallery.get("style"))


def track_has_artwork(artist_name: str, track: dict[str, Any], album_cache: dict[str, Any]) -> bool:
    album = str(track.get("album") or "").strip()
    if not album:
        return False
    cached = album_cache.get(ba.album_art_key(artist_name, album)) or {}
    return bool(
        isinstance(cached, dict)
        and cached.get("status") == "complete"
        and cached.get("validated") is True
        and has_text(cached.get("url"))
    )


def artist_case(artist: dict[str, Any], gallery: dict[str, Any], album_cache: dict[str, Any]) -> dict[str, Any]:
    tracks = [t for t in (artist.get("tracks") or []) if isinstance(t, dict) and has_text(t.get("title"))]
    covered = sum(track_has_artwork(str(artist.get("name") or ""), t, album_cache) for t in tracks)
    other = sum(1 for t in tracks if ba.track_album_bucket(t)[0] == "__other__")
    missing = []
    if not effective_image(artist, gallery):
        missing.append("image")
    if not effective_bio(artist, gallery):
        missing.append("bio")
    if not tracks:
        missing.append("tracks")
    if not has_text(artist.get("first_played")):
        missing.append("first_played")
    if not has_text(artist.get("last_played")):
        missing.append("last_played")
    profile_missing = es.profile_missing_fields(artist, gallery)
    stored_profile_status = str(gallery.get("profile_status") or "")
    effective_profile_status = (
        stored_profile_status
        if stored_profile_status in es.STATUSES
        else ("complete" if not profile_missing else "legacy")
    )
    return {
        "name": artist.get("name"),
        "slug": artist.get("slug"),
        "plays": int(artist.get("plays") or 0),
        "first_played": artist.get("first_played") or "",
        "last_played": artist.get("last_played") or "",
        "catalog_status": artist.get("catalog_status") or "",
        "sources": artist.get("sources") or [],
        "tracks": len(tracks),
        "tracks_with_artwork": covered,
        "tracks_missing_artwork": len(tracks) - covered,
        "tracks_in_otras": other,
        "has_image": bool(effective_image(artist, gallery)),
        "image_source": "artist" if has_text(artist.get("image")) else ("gallery" if effective_image(artist, gallery) else ""),
        "has_bio": bool(effective_bio(artist, gallery)),
        "bio_source": "artist" if has_text(artist.get("bio")) else (
            "gallery_es" if has_text(gallery.get("bio_es")) else (
                "gallery_en" if has_text(gallery.get("bio_en")) else ""
            )
        ),
        "gallery_checked": bool(gallery.get("profile_checked_at")),
        "gallery_images": len(ba.gallery_images(gallery)),
        "has_social": effective_social(artist, gallery),
        "has_genre": effective_genre(artist, gallery),
        "related": len(artist.get("related") or []),
        "missing_core": missing,
        "core_complete": not missing,
        "profile_status": effective_profile_status,
        "profile_missing_fields": profile_missing,
        "profile_complete": not profile_missing,
    }


def main() -> int:
    artist_store = load(ARTISTS, {"artists": []})
    gallery_store = load(GALLERIES, {"artists": {}})
    art_store = load(ALBUM_ART, {"albums": {}})

    raw = [a for a in (artist_store.get("artists") or []) if isinstance(a, dict)]
    public, aliases = ba.prepare_public_artists(raw)
    galleries = gallery_store.get("artists") or {}
    galleries = ba.apply_identity_fallbacks(galleries)
    galleries = ba.apply_reviewed_profile_overrides(galleries)
    album_cache = art_store.get("albums") or {}

    rows = []
    total_tracks = 0
    tracks_with_art = 0
    tracks_other = 0
    tracks_with_both_dates = 0

    image_direct = image_gallery = 0
    bio_direct = bio_es = bio_en = 0
    gallery_checked = gallery_with_images = 0
    with_social = with_genre = with_related = 0
    core_complete = 0
    with_tracks = 0
    with_history = 0

    status_counts = Counter()
    source_counts = Counter()
    profile_status_counts = Counter()
    profile_complete = 0
    profile_missing_image = 0
    profile_missing_bio = 0
    profile_missing_data = 0

    for artist in public:
        gallery = gallery_for(galleries, artist)
        row = artist_case(artist, gallery, album_cache)
        rows.append(row)

        status_counts[str(artist.get("catalog_status") or "unknown")] += 1
        profile_status_counts[str(row.get("profile_status") or "legacy")] += 1
        if row.get("profile_complete"):
            profile_complete += 1
        missing_profile_fields = set(row.get("profile_missing_fields") or [])
        profile_missing_image += int("image" in missing_profile_fields)
        profile_missing_bio += int("bio" in missing_profile_fields)
        profile_missing_data += int("data" in missing_profile_fields)
        for source in artist.get("sources") or []:
            source_counts[str(source)] += 1

        tracks = [t for t in (artist.get("tracks") or []) if isinstance(t, dict) and has_text(t.get("title"))]
        total_tracks += len(tracks)
        if tracks:
            with_tracks += 1
        if int(artist.get("plays") or 0) > 0 or has_text(artist.get("first_played")) or has_text(artist.get("last_played")):
            with_history += 1

        for track in tracks:
            if track_has_artwork(str(artist.get("name") or ""), track, album_cache):
                tracks_with_art += 1
            if ba.track_album_bucket(track)[0] == "__other__":
                tracks_other += 1
            if has_text(track.get("first_played")) and has_text(track.get("last_played")):
                tracks_with_both_dates += 1

        if has_text(artist.get("image")):
            image_direct += 1
        elif effective_image(artist, gallery):
            image_gallery += 1

        if has_text(artist.get("bio")):
            bio_direct += 1
        elif has_text(gallery.get("bio_es")):
            bio_es += 1
        elif has_text(gallery.get("bio_en")):
            bio_en += 1

        if gallery.get("profile_checked_at"):
            gallery_checked += 1
        if ba.gallery_images(gallery):
            gallery_with_images += 1
        if effective_social(artist, gallery):
            with_social += 1
        if effective_genre(artist, gallery):
            with_genre += 1
        if artist.get("related"):
            with_related += 1
        if row["core_complete"]:
            core_complete += 1

    total = len(public)
    image_effective = image_direct + image_gallery
    bio_effective = bio_direct + bio_es + bio_en
    missing_image = total - image_effective
    missing_bio = total - bio_effective

    incomplete = [r for r in rows if not r["core_complete"]]
    incomplete.sort(key=lambda r: (-r["plays"], r["name"].casefold()))
    no_image = [r for r in rows if not r["has_image"]]
    no_image.sort(key=lambda r: (-r["plays"], r["name"].casefold()))
    no_bio = [r for r in rows if not r["has_bio"]]
    no_bio.sort(key=lambda r: (-r["plays"], r["name"].casefold()))

    targets = {}
    wanted = {"boylife", "monsun"}
    for r in rows:
        if ba.norm(str(r["name"])) in wanted or ba.norm(str(r["slug"])) in wanted:
            targets[ba.norm(str(r["name"]))] = r

    cache_entries = [v for v in album_cache.values() if isinstance(v, dict)]
    cache_found = sum(1 for v in cache_entries if has_text(v.get("url")))
    cache_missed = sum(1 for v in cache_entries if not has_text(v.get("url")))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_updates": {
            "artists": artist_store.get("updated_at") or artist_store.get("history_merge", {}).get("merged_at"),
            "galleries": gallery_store.get("updated_at"),
            "album_art": art_store.get("updated_at"),
        },
        "catalog": {
            "raw_artists": len(raw),
            "public_artists": total,
            "aliases_normalized": len(aliases),
            "with_history": with_history,
            "with_tracks": with_tracks,
            "without_tracks": total - with_tracks,
            "catalog_status": dict(status_counts.most_common()),
            "sources": dict(source_counts.most_common()),
            "history_merge": artist_store.get("history_merge") or {},
        },
        "profile_enrichment": {
            "real_profile_complete": profile_complete,
            "real_profile_missing": total - profile_complete,
            "real_profile_complete_pct": round((profile_complete / total * 100), 2) if total else 0,
            "profile_status": dict(profile_status_counts.most_common()),
            "missing_validated_profile_image": profile_missing_image,
            "missing_profile_bio": profile_missing_bio,
            "missing_profile_data": profile_missing_data,
            "profile_definition": "validated image + bio + identity/profile data",
            "core_complete": core_complete,
            "core_complete_pct": round((core_complete / total * 100), 2) if total else 0,
            "core_definition": "effective image + effective bio + >=1 track + first_played + last_played",
            "effective_image": image_effective,
            "effective_image_pct": round((image_effective / total * 100), 2) if total else 0,
            "image_direct_artist": image_direct,
            "image_gallery_fallback": image_gallery,
            "missing_image": missing_image,
            "effective_bio": bio_effective,
            "effective_bio_pct": round((bio_effective / total * 100), 2) if total else 0,
            "bio_direct_artist": bio_direct,
            "bio_gallery_es": bio_es,
            "bio_gallery_en": bio_en,
            "missing_bio": missing_bio,
            "gallery_checked": gallery_checked,
            "gallery_checked_pct": round((gallery_checked / total * 100), 2) if total else 0,
            "gallery_with_images": gallery_with_images,
            "with_social": with_social,
            "with_genre": with_genre,
            "with_related": with_related,
        },
        "tracks": {
            "total": total_tracks,
            "with_effective_artwork": tracks_with_art,
            "with_effective_artwork_pct": round((tracks_with_art / total_tracks * 100), 2) if total_tracks else 0,
            "missing_artwork": total_tracks - tracks_with_art,
            "grouped_as_otras": tracks_other,
            "with_first_and_last_dates": tracks_with_both_dates,
            "album_art_cache_entries": len(cache_entries),
            "album_art_cache_found": cache_found,
            "album_art_cache_missed": cache_missed,
        },
        "focus": targets,
        "priority_incomplete": incomplete[:100],
        "priority_missing_image": no_image[:100],
        "priority_missing_bio": no_bio[:100],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def pct(n: int, d: int) -> str:
        return f"{(100*n/d):.2f}%" if d else "0%"

    lines = [
        "# Auditoría Louder Artistas",
        "",
        f"Generada: {report['generated_at']}",
        "",
        "## Resumen",
        "",
        f"- Artistas crudos: {len(raw)}",
        f"- Artistas públicos normalizados: {total}",
        f"- Perfiles realmente completos: {profile_complete}/{total} ({pct(profile_complete,total)})",
        f"- Perfiles con faltantes reales: {total-profile_complete}",
        f"- Estados de enriquecimiento: {dict(profile_status_counts.most_common())}",
        f"- Sin imagen validada de perfil: {profile_missing_image}",
        f"- Sin biografía de perfil: {profile_missing_bio}",
        f"- Sin datos de identidad/perfil: {profile_missing_data}",
        f"- Fichas core completas: {core_complete}/{total} ({pct(core_complete,total)})",
        f"- Con imagen efectiva: {image_effective}/{total} ({pct(image_effective,total)})",
        f"- Sin imagen: {missing_image}",
        f"- Con biografía efectiva: {bio_effective}/{total} ({pct(bio_effective,total)})",
        f"- Sin biografía: {missing_bio}",
        f"- Galerías ya revisadas: {gallery_checked}/{total} ({pct(gallery_checked,total)})",
        f"- Artistas con canciones: {with_tracks}/{total}",
        f"- Canciones totales: {total_tracks}",
        f"- Canciones con portada efectiva: {tracks_with_art}/{total_tracks} ({pct(tracks_with_art,total_tracks)})",
        f"- Canciones sin portada: {total_tracks - tracks_with_art}",
        f"- Canciones agrupadas en Otras: {tracks_other}",
        "",
        "## Casos solicitados",
        "",
    ]
    for key in ("boylife", "monsun"):
        row = targets.get(key)
        if not row:
            lines.append(f"- {key}: no localizado entre perfiles públicos normalizados.")
        else:
            lines.append(
                f"- {row['name']}: plays={row['plays']}, tracks={row['tracks']}, "
                f"imagen={'sí' if row['has_image'] else 'no'}, bio={'sí' if row['has_bio'] else 'no'}, "
                f"portadas faltantes={row['tracks_missing_artwork']}, Otras={row['tracks_in_otras']}, "
                f"faltantes core={', '.join(row['missing_core']) or 'ninguno'}."
            )

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report["catalog"], ensure_ascii=False))
    print(json.dumps(report["profile_enrichment"], ensure_ascii=False))
    print(json.dumps(report["tracks"], ensure_ascii=False))
    print(
        "ACTION_REAL_MISSING "
        f"profiles={report['profile_enrichment']['real_profile_missing']} "
        f"image={report['profile_enrichment']['missing_validated_profile_image']} "
        f"bio={report['profile_enrichment']['missing_profile_bio']} "
        f"data={report['profile_enrichment']['missing_profile_data']} "
        f"track_art={report['tracks']['missing_artwork']} "
        f"states={report['profile_enrichment']['profile_status']}"
    )
    print(json.dumps(report["focus"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
