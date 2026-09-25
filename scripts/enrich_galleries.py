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


def tadb_gallery(client: RateClient, artist: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    name = artist.get("name", "")
    data = client.get_json(f"{TADB_BASE}/search.php?s={quote(name)}") or {}
    rows = data.get("artists") or []
    if not rows or not isinstance(rows, list):
        return [], ""

    row = rows[0] or {}
    returned = str(row.get("strArtist") or "")
    if norm(returned) != norm(name):
        return [], ""

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

    return images[:5], str(row.get("strMusicBrainzID") or "").strip()


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
        if not args.refresh and len(existing.get("images") or []) >= 3:
            continue
        pending.append(artist)

    if args.limit > 0:
        pending = pending[: args.limit]

    print(f"artists={len(artists)} pending={len(pending)} fanart_tv={'yes' if fanart_key else 'no'}")

    for i, artist in enumerate(pending, start=1):
        slug = artist["slug"]
        try:
            images, mbid = tadb_gallery(client, artist)
            images = fanart_gallery(mbid, fanart_key, images)
            images = fallback_gallery(artist, images)
            galleries[slug] = {
                "name": artist.get("name", ""),
                "musicbrainz_id": mbid,
                "images": images[:5],
                "image_count": min(len(images), 5),
                "updated_at": datetime.now(timezone.utc).isoformat(),
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
