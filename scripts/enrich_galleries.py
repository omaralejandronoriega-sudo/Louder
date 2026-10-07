#!/usr/bin/env python3
"""Build lightweight artist galleries without storing image binaries in GitHub.

Sources, in priority order:
1) TheAudioDB free API (fanart 1-4, wide thumb, thumb)
2) fanart.tv when FANART_TV_API_KEY is configured
3) the image already migrated from Louder as a fallback

Only URLs + attribution are committed. This keeps GitHub Pages well below its
1 GB published-site limit while moving image traffic away from WordPress.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

import build_artists as ba
import enrichment_state as es

ROOT = Path(__file__).resolve().parents[1]
ARTISTS_FILE = ROOT / "data" / "artists.json"
GALLERIES_FILE = ROOT / "data" / "galleries.json"

TADB_BASE = "https://www.theaudiodb.com/api/v1/json/123"
FANART_BASE = "https://webservice.fanart.tv/v3.2/music"
WIKI_SEARCH = "https://en.wikipedia.org/w/rest.php/v1/search/page"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary"
DEEZER_SEARCH = "https://api.deezer.com/search/artist"
LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
DISCOGS_SEARCH = "https://api.discogs.com/database/search"
UA = "LouderMX-Artistas-Gallery/2.0 (+https://loudermx.com)"


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


def save(data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    GALLERIES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class RateClient:
    def __init__(self, min_interval: float = 2.05) -> None:
        self.min_interval = min_interval
        self.last = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    def get_json(self, url: str, timeout: int = 35) -> dict[str, Any] | None:
        elapsed = time.monotonic() - self.last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        r = self.session.get(url, timeout=timeout)
        self.last = time.monotonic()
        if r.status_code in (404, 429):
            return None
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else None


def add_image(
    out: list[dict[str, str]],
    seen: set[str],
    url: str | None,
    source: str,
    kind: str,
    preview: str | None = None,
) -> None:
    url = str(url or "").strip()
    if not url or url in seen:
        return
    if not url.startswith("https://"):
        return
    seen.add(url)
    out.append(
        {
            "url": url,
            "preview": str(preview or url),
            "source": source,
            "kind": kind,
        }
    )


def tadb_gallery(client: RateClient, artist: dict[str, Any]) -> tuple[list[dict[str, str]], str, dict[str, Any]]:
    name = artist.get("name", "")
    data = client.get_json(f"{TADB_BASE}/search.php?s={quote(name)}") or {}
    rows = data.get("artists") or []
    if not rows or not isinstance(rows, list):
        return [], "", {}

    row = rows[0] or {}
    returned = str(row.get("strArtist") or "")
    if norm(returned) != norm(name):
        return [], "", {}

    images: list[dict[str, str]] = []
    seen: set[str] = set()

    for key in ("strArtistFanart", "strArtistFanart2", "strArtistFanart3", "strArtistFanart4"):
        url = row.get(key)
        add_image(
            images, seen, url, "TheAudioDB", "fanart",
            f"{url}/medium" if url else None,
        )

    for key, kind in (
        ("strArtistWideThumb", "wide"),
        ("strArtistThumb", "portrait"),
    ):
        url = row.get(key)
        add_image(
            images, seen, url, "TheAudioDB", kind,
            f"{url}/medium" if url else None,
        )

    profile = {
        "bio_es": str(row.get("strBiographyES") or "").strip(),
        "bio_en": str(row.get("strBiographyEN") or "").strip(),
        "website": str(row.get("strWebsite") or "").strip(),
        "facebook": str(row.get("strFacebook") or "").strip(),
        "twitter": str(row.get("strTwitter") or "").strip(),
        "instagram": str(row.get("strInstagram") or "").strip(),
        "genre": str(row.get("strGenre") or "").strip(),
        "style": str(row.get("strStyle") or "").strip(),
        "country": str(row.get("strCountry") or "").strip(),
        "verified": True,
        "verification_source": "TheAudioDB",
    }
    return images[:5], str(row.get("strMusicBrainzID") or "").strip(), profile


def fanart_gallery(
    mbid: str,
    api_key: str,
    already: list[dict[str, str]],
) -> list[dict[str, str]]:
    if not mbid or not api_key or len(already) >= 5:
        return already[:5]

    # fanart.tv is optional: TheAudioDB works without a private secret.
    r = requests.get(
        f"{FANART_BASE}/{quote(mbid)}",
        params={"api_key": api_key},
        headers={"User-Agent": UA},
        timeout=35,
    )
    if r.status_code in (401, 404, 429):
        return already[:5]
    r.raise_for_status()
    data = r.json()

    images = list(already)
    seen = {x.get("url", "") for x in images}

    for field, kind in (
        ("artistbackground", "fanart"),
        ("artistthumb", "portrait"),
    ):
        rows = data.get(field) or []
        if not isinstance(rows, list):
            continue
        rows = sorted(
            rows,
            key=lambda x: int(str(x.get("likes") or "0") or 0),
            reverse=True,
        )
        for item in rows:
            add_image(images, seen, item.get("url"), "fanart.tv", kind)
            if len(images) >= 5:
                return images[:5]

    return images[:5]


def wikipedia_profile(
    client: RateClient,
    artist: dict[str, Any],
    images: list[dict[str, str]],
    profile: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Use Wikipedia only when TheAudioDB left bio/image gaps.

    A result must look like a music entity; this prevents album/song/program
    pages from being accepted as artist profiles.
    """
    name = str(artist.get("name") or "").strip()
    if not name:
        return images, profile

    need_bio = not str(profile.get("bio_es") or profile.get("bio_en") or "").strip()
    need_image = not images
    need_data = not str(profile.get("lastfm_url") or "").strip()
    if not need_bio and not need_image and not need_data:
        return images, profile

    search = client.get_json(
        f"{WIKI_SEARCH}?q={quote(name)}&limit=6"
    ) or {}
    pages = search.get("pages") or []
    if not isinstance(pages, list):
        return images, profile

    positive = (
        "band", "musician", "singer", "musical group", "music group", "duo",
        "trio", "quartet", "singer-songwriter", "record producer", "dj",
        "composer", "rock group", "electronic music", "indie rock",
    )
    negative = (
        "album", "song", "film", "television", "radio program", "radio programme",
        "podcast", "magazine", "newspaper", "episode", "novel", "video game",
    )

    wanted = norm(name)
    best: dict[str, Any] | None = None
    best_score = -999

    for page in pages:
        if not isinstance(page, dict):
            continue
        title = str(page.get("title") or "").strip()
        description = str(page.get("description") or "").strip().lower()
        if not title:
            continue

        title_norm = norm(re.sub(r"\s*\([^)]*\)\s*$", "", title))
        score = 0
        if title_norm == wanted:
            score += 80
        elif wanted and (title_norm.startswith(wanted + " ") or wanted.startswith(title_norm + " ")):
            score += 35

        if any(word in description for word in positive):
            score += 70
        if any(word in description for word in negative):
            score -= 120

        if score > best_score:
            best_score = score
            best = page

    if not best or best_score < 80:
        return images, profile

    title = str(best.get("title") or "").strip()
    summary = client.get_json(f"{WIKI_SUMMARY}/{quote(title, safe='')}") or {}
    if str(summary.get("type") or "").lower() == "disambiguation":
        return images, profile

    description = str(summary.get("description") or best.get("description") or "").lower()
    if any(word in description for word in negative):
        return images, profile

    extract = str(summary.get("extract") or "").strip()
    if need_bio and extract:
        profile["bio_en"] = extract

    if need_image:
        original = summary.get("originalimage") or {}
        thumb = summary.get("thumbnail") or {}
        url = str(original.get("source") or thumb.get("source") or "").strip()
        if url.startswith("https://"):
            seen = {x.get("url", "") for x in images}
            add_image(images, seen, url, "Wikipedia", "portrait", url)

    content_urls = summary.get("content_urls") or {}
    desktop = content_urls.get("desktop") or {}
    if desktop.get("page"):
        profile["wikipedia_url"] = str(desktop.get("page"))

    profile["verified"] = True
    profile["verification_source"] = "Wikipedia"
    profile["verification_title"] = title
    return images[:5], profile


def deezer_profile(
    name: str,
    images: list[dict[str, Any]],
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Exact-name Deezer fallback for artists missed by TheAudioDB/Wikipedia."""
    if images:
        return images, profile
    try:
        r = requests.get(
            DEEZER_SEARCH,
            params={"q": name, "limit": 8},
            headers={"User-Agent": UA},
            timeout=25,
        )
        r.raise_for_status()
        wanted = norm(name)
        for row in r.json().get("data") or []:
            if not isinstance(row, dict) or norm(row.get("name", "")) != wanted:
                continue
            for key in ("picture_xl", "picture_big", "picture_medium", "picture"):
                url = str(row.get(key) or "").strip()
                if url.startswith("https://"):
                    add_image(images, {x.get("url", "") for x in images}, url, "Deezer", "portrait", url)
                    profile.setdefault("verification_source", "Deezer")
                    return images[:5], profile
    except Exception:
        pass
    return images, profile


def lastfm_profile(
    name: str,
    api_key: str,
    images: list[dict[str, Any]],
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Optional Last.fm fallback; only exact artist-name matches are accepted."""
    if not api_key:
        return images, profile
    need_bio = not str(profile.get("bio_es") or profile.get("bio_en") or "").strip()
    need_image = not images
    if not need_bio and not need_image:
        return images, profile
    try:
        r = requests.get(
            LASTFM_API,
            params={"method": "artist.getinfo", "artist": name, "api_key": api_key, "format": "json", "autocorrect": 0},
            headers={"User-Agent": UA},
            timeout=25,
        )
        r.raise_for_status()
        row = r.json().get("artist") or {}
        if not isinstance(row, dict) or norm(row.get("name", "")) != norm(name):
            return images, profile
        if need_bio:
            raw_bio = str(((row.get("bio") or {}).get("summary")) or "").strip()
            clean_bio = re.sub(r"<[^>]+>", "", raw_bio).strip()
            if clean_bio:
                profile["bio_en"] = clean_bio
        if need_image:
            for item in reversed(row.get("image") or []):
                if not isinstance(item, dict):
                    continue
                url = str(item.get("#text") or "").strip()
                if url.startswith("https://") and "2a96cbd8b46e442fc41c2b86b821562f" not in url:
                    add_image(images, {x.get("url", "") for x in images}, url, "Last.fm", "portrait", url)
                    break
        if row.get("url") and not profile.get("lastfm_url"):
            profile["lastfm_url"] = str(row.get("url"))
    except Exception:
        pass
    return images[:5], profile


def discogs_profile(
    name: str,
    token: str,
    images: list[dict[str, Any]],
    profile: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Optional Discogs fallback for difficult/legacy artists."""
    if not token:
        return images, profile
    need_image = not images
    need_data = not str(profile.get("website") or "").strip()
    if not need_image and not need_data:
        return images, profile
    headers = {"User-Agent": UA, "Authorization": f"Discogs token={token}"}
    try:
        r = requests.get(
            DISCOGS_SEARCH,
            params={"q": name, "type": "artist", "per_page": 8},
            headers=headers,
            timeout=25,
        )
        r.raise_for_status()
        wanted = norm(name)
        hit = None
        for row in r.json().get("results") or []:
            title = re.sub(r"\s*\(\d+\)\s*$", "", str(row.get("title") or "")).strip()
            if norm(title) == wanted:
                hit = row
                break
        if not hit or not hit.get("resource_url"):
            return images, profile
        d = requests.get(str(hit["resource_url"]), headers=headers, timeout=25)
        d.raise_for_status()
        detail = d.json()
        if need_image:
            for item in detail.get("images") or []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("uri") or item.get("resource_url") or "").strip()
                if url.startswith("https://"):
                    add_image(images, {x.get("url", "") for x in images}, url, "Discogs", "portrait", url)
                    break
        urls = detail.get("urls") or []
        if urls and not profile.get("website"):
            profile["website"] = str(urls[0] or "").strip()
    except Exception:
        pass
    return images[:5], profile


def validate_images(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only URLs that currently resolve to actual image bytes."""
    out: list[dict[str, Any]] = []
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    seen: set[str] = set()
    for original in images[:8]:
        if not isinstance(original, dict):
            continue
        item = dict(original)
        ok, final_url, method = es.validate_remote_image(session, item.get("url"))
        if not ok or final_url in seen:
            continue
        item["url"] = final_url
        preview = str(item.get("preview") or final_url).strip()
        if preview != final_url:
            p_ok, p_final, _ = es.validate_remote_image(session, preview)
            item["preview"] = p_final if p_ok else final_url
        else:
            item["preview"] = final_url
        item["valid"] = True
        item["validated_at"] = es.iso(es.utcnow())
        item["validation_method"] = method
        out.append(item)
        seen.add(final_url)
        if len(out) >= 5:
            break
    return out


def summarize_real_missing(artists: list[dict[str, Any]], galleries: dict[str, Any]) -> dict[str, int]:
    counts = {
        "total": 0,
        "complete": 0,
        "partial": 0,
        "retry": 0,
        "not_found": 0,
        "legacy": 0,
        "real_missing_profiles": 0,
        "missing_image": 0,
        "missing_bio": 0,
        "missing_data": 0,
    }
    for artist in artists:
        if not isinstance(artist, dict) or not artist.get("slug"):
            continue
        counts["total"] += 1
        gallery = galleries.get(str(artist.get("slug"))) or {}
        status = str(gallery.get("profile_status") or "legacy")
        if status not in counts:
            status = "legacy"
        counts[status] += 1
        missing = es.profile_missing_fields(artist, gallery)
        if missing:
            counts["real_missing_profiles"] += 1
        for field in missing:
            key = f"missing_{field}"
            if key in counts:
                counts[key] += 1
    return counts


def fallback_gallery(artist: dict[str, Any], current: list[dict[str, str]]) -> list[dict[str, str]]:
    if current:
        return current[:5]
    url = str(artist.get("image") or "").strip()
    if url.startswith("https://"):
        return [
            {
                "url": url,
                "preview": url,
                "source": "Louder",
                "kind": "legacy",
            }
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max artists this run; 0 = all")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    artists_store = load_json(ARTISTS_FILE, {"artists": []})
    artists = artists_store.get("artists") or []
    if len(artists) < 500:
        raise SystemExit(
            f"Base Artistas snapshot is not ready: only {len(artists)} artists."
        )

    gallery_store = load_json(
        GALLERIES_FILE,
        {"version": 2, "updated_at": None, "artists": {}},
    )
    gallery_store["version"] = max(int(gallery_store.get("version") or 1), 2)
    galleries = gallery_store.setdefault("artists", {})
    fanart_key = os.getenv("FANART_TV_API_KEY", "").strip()
    lastfm_key = os.getenv("LASTFM_API_KEY", "").strip()
    discogs_token = os.getenv("DISCOGS_TOKEN", "").strip()
    client = RateClient(2.05)
    now = es.utcnow()

    # Editorial priority is part of the queue contract, not a cosmetic sort.
    # Core Louder artists with an unusable/missing bio or image bypass retry
    # cooldowns so the public archive cannot leave major artists unfinished
    # while long-tail profiles are processed.
    core_names = [
        "Arctic Monkeys", "The Strokes", "Interpol", "Foals", "Fontaines D.C.",
        "The Killers", "Radiohead", "Oasis", "Yeah Yeah Yeahs", "Franz Ferdinand",
        "Bloc Party", "The National", "Vampire Weekend", "LCD Soundsystem",
        "The Libertines", "The Hives", "Phoenix", "MGMT", "Tame Impala", "Gorillaz",
        "The Cure", "Depeche Mode", "New Order", "Joy Division", "Blur", "Pulp",
        "Suede", "Placebo", "Muse", "Kasabian", "Editors", "White Lies",
        "The Vaccines", "Two Door Cinema Club", "The Kooks", "The Cribs",
        "The Rapture", "Klaxons", "The Horrors", "The Drums", "Metric",
        "Arcade Fire", "Modest Mouse", "Death Cab for Cutie", "The Shins",
        "Spoon", "Wilco", "The War on Drugs", "Beach House", "DIIV",
        "Slowdive", "Ride", "My Bloody Valentine", "Primal Scream", "Massive Attack",
        "Portishead", "Underworld", "The Chemical Brothers", "Daft Punk", "M83",
        "Caribou", "Hot Chip", "Cut Copy", "Friendly Fires", "Metronomy",
        "IDLES", "Shame", "Wet Leg", "Wolf Alice", "The Last Dinner Party"
    ]
    core_rank = {norm(name): i for i, name in enumerate(core_names)}

    pending = []
    for artist in artists:
        if not isinstance(artist, dict):
            continue
        slug = str(artist.get("slug") or "").strip()
        if not slug:
            continue
        existing = galleries.get(slug) or {}
        missing = es.profile_missing_fields(artist, existing)
        is_core = norm(artist.get("name", "")) in core_rank
        # Trust "complete" only when the current data still passes the actual
        # photo+bio checks. This repairs stale status flags.
        if str(existing.get("profile_status") or "") == "complete" and not missing:
            continue
        # Core artists with real gaps are always due. Long-tail profiles keep
        # normal backoff so API failures do not hammer external services.
        if not is_core and not es.is_due(existing, refresh=args.refresh, now=now):
            continue
        pending.append(artist)

    def priority(a: dict[str, Any]) -> tuple[Any, ...]:
        sources = set(a.get("sources") or [])
        catalog_status = str(a.get("catalog_status") or "")
        if catalog_status in {"live_only", "programmed_history"} or "yesstreaming_live" in sources:
            active_rank = 0
        elif catalog_status == "programmed_only" or "yesstreaming" in sources:
            active_rank = 1
        else:
            active_rank = 2
        date_key = ba.history_date_key(a.get("last_played"))
        recent_score = 0 if date_key[0] >= 9998 else (
            date_key[0] * 10**10 + date_key[1] * 10**8 + date_key[2] * 10**6
            + date_key[3] * 10**4 + date_key[4] * 10**2 + date_key[5]
        )
        return (-int(a.get("plays") or 0), active_rank, -recent_score, norm(a.get("name", "")))

    pending.sort(key=lambda a: (core_rank.get(norm(a.get("name", "")), 999999),) + priority(a))
    if args.limit > 0:
        pending = pending[: args.limit]

    before = summarize_real_missing(artists, galleries)
    print(
        "profile_queue "
        f"artists={len(artists)} due={len(pending)} "
        f"real_missing_profiles={before['real_missing_profiles']} "
        f"missing_image={before['missing_image']} missing_bio={before['missing_bio']} "
        f"missing_data={before['missing_data']}"
    )
    print(
        "sources "
        f"theaudiodb=yes fanart_tv={'yes' if fanart_key else 'no'} "
        f"wikipedia=no deezer=yes lastfm={'yes' if lastfm_key else 'no'} "
        f"discogs={'yes' if discogs_token else 'no'}"
    )

    for i, artist in enumerate(pending, start=1):
        slug = str(artist["slug"])
        name = str(artist.get("name") or "")
        existing = galleries.get(slug) or {}
        attempt_time = es.utcnow()
        try:
            images, mbid, profile = tadb_gallery(client, artist)
            images = fanart_gallery(mbid, fanart_key, images)
            images, profile = deezer_profile(name, images, profile)
            images, profile = lastfm_profile(name, lastfm_key, images, profile)
            images, profile = discogs_profile(name, discogs_token, images, profile)
            images = fallback_gallery(artist, images)
            images = validate_images(images)

            old_images = es.usable_gallery_images(existing)
            if not images and old_images:
                images = old_images

            def keep(new_value: Any, old_key: str) -> Any:
                if isinstance(new_value, str) and new_value.strip():
                    return new_value
                if new_value not in (None, "", [], {}):
                    return new_value
                return existing.get(old_key, "")

            old_social = existing.get("social") or {}
            row: dict[str, Any] = {
                "name": name,
                "musicbrainz_id": mbid or existing.get("musicbrainz_id", ""),
                "images": images[:5],
                "image_count": min(len(images), 5),
                "bio_es": keep(profile.get("bio_es", ""), "bio_es"),
                "bio_en": keep(profile.get("bio_en", ""), "bio_en"),
                "official_url": keep(profile.get("website", ""), "official_url"),
                "social": {
                    "facebook": profile.get("facebook") or old_social.get("facebook", ""),
                    "twitter": profile.get("twitter") or old_social.get("twitter", ""),
                    "instagram": profile.get("instagram") or old_social.get("instagram", ""),
                },
                "genre": keep(profile.get("genre", ""), "genre"),
                "style": keep(profile.get("style", ""), "style"),
                "country": keep(profile.get("country", ""), "country"),
                "wikipedia_url": keep(profile.get("wikipedia_url", ""), "wikipedia_url"),
                "lastfm_url": keep(profile.get("lastfm_url", ""), "lastfm_url"),
                "verified": bool(profile.get("verified") or existing.get("verified")),
                "verification_source": profile.get("verification_source") or existing.get("verification_source", ""),
                "verification_title": profile.get("verification_title") or existing.get("verification_title", ""),
                "profile_checked_at": es.iso(attempt_time),
                "updated_at": es.iso(attempt_time),
            }
            status, missing = es.profile_status(artist, row)
            row["profile_status"] = status
            row["missing_fields"] = missing
            row["next_retry_at"] = es.next_retry_at(status, attempt_time)
            row["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
            row.pop("last_error", None)
            galleries[slug] = row
            print(
                f"{i}/{len(pending)} {name} -> {status} "
                f"missing={','.join(missing) or 'none'} images={len(images)}"
            )
        except Exception as exc:
            row = dict(existing)
            row["name"] = name
            row["profile_checked_at"] = es.iso(attempt_time)
            row["profile_status"] = "retry"
            row["missing_fields"] = es.profile_missing_fields(artist, row)
            row["next_retry_at"] = es.next_retry_at("retry", attempt_time)
            row["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
            row["last_error"] = str(exc)[:300]
            row["updated_at"] = es.iso(attempt_time)
            galleries[slug] = row
            print(f"{i}/{len(pending)} {name} -> retry ERROR {exc}")

        if i % 25 == 0:
            save(gallery_store)

    save(gallery_store)
    after = summarize_real_missing(artists, galleries)
    print(
        "profile_result "
        f"complete={after['complete']} partial={after['partial']} retry={after['retry']} "
        f"not_found={after['not_found']} legacy={after['legacy']} "
        f"real_missing_profiles={after['real_missing_profiles']} "
        f"missing_image={after['missing_image']} missing_bio={after['missing_bio']} "
        f"missing_data={after['missing_data']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
