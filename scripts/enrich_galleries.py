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

ROOT = Path(__file__).resolve().parents[1]
ARTISTS_FILE = ROOT / "data" / "artists.json"
GALLERIES_FILE = ROOT / "data" / "galleries.json"

TADB_BASE = "https://www.theaudiodb.com/api/v1/json/123"
FANART_BASE = "https://webservice.fanart.tv/v3.2/music"
WIKI_SEARCH = "https://en.wikipedia.org/w/rest.php/v1/search/page"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary"
UA = "LouderMX-Artistas-Gallery/1.0 (+https://loudermx.com)"


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
    if not need_bio and not need_image:
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
        {"version": 1, "updated_at": None, "artists": {}},
    )
    galleries = gallery_store.setdefault("artists", {})
    fanart_key = os.getenv("FANART_TV_API_KEY", "").strip()
    client = RateClient(2.05)

    pending = []
    for artist in artists:
        slug = artist.get("slug")
        if not slug:
            continue
        existing = galleries.get(slug) or {}
        # Version 2 also enriches biography/social metadata. Existing gallery
        # entries are revisited once if they predate this enrichment.
        if not args.refresh and existing and existing.get("profile_checked_at"):
            continue
        pending.append(artist)

    pending.sort(
        key=lambda a: (
            bool(str(a.get("image") or "").strip()),
            -int(a.get("plays") or 0),
            norm(a.get("name", "")),
        )
    )

    if args.limit > 0:
        pending = pending[: args.limit]

    print(f"artists={len(artists)} pending={len(pending)} fanart_tv={'yes' if fanart_key else 'no'}")

    for i, artist in enumerate(pending, start=1):
        slug = artist["slug"]
        try:
            images, mbid, profile = tadb_gallery(client, artist)
            images = fanart_gallery(mbid, fanart_key, images)
            images, profile = wikipedia_profile(client, artist, images, profile)
            images = fallback_gallery(artist, images)
            now = datetime.now(timezone.utc).isoformat()
            galleries[slug] = {
                "name": artist.get("name", ""),
                "musicbrainz_id": mbid,
                "images": images[:5],
                "image_count": min(len(images), 5),
                "bio_es": profile.get("bio_es", ""),
                "bio_en": profile.get("bio_en", ""),
                "official_url": profile.get("website", ""),
                "social": {
                    "facebook": profile.get("facebook", ""),
                    "twitter": profile.get("twitter", ""),
                    "instagram": profile.get("instagram", ""),
                },
                "genre": profile.get("genre", ""),
                "style": profile.get("style", ""),
                "country": profile.get("country", ""),
                "wikipedia_url": profile.get("wikipedia_url", ""),
                "verified": bool(profile.get("verified")),
                "verification_source": profile.get("verification_source", ""),
                "verification_title": profile.get("verification_title", ""),
                "profile_checked_at": now,
                "updated_at": now,
            }
            print(
                f"{i}/{len(pending)} {artist.get('name')} "
                f"images={len(images[:5])} mbid={'yes' if mbid else 'no'}"
            )
        except Exception as exc:
            print(f"{i}/{len(pending)} {artist.get('name')}: ERROR {exc}")

        if i % 25 == 0:
            save(gallery_store)

    save(gallery_store)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
