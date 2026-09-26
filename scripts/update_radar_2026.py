#!/usr/bin/env python3
"""Discover 2026-only song candidates for Louder without touching WordPress.

Canonical discovery uses MusicBrainz because its recording search exposes
first-release-date. Existing Louder artists get priority; a small set of genre
queries also discovers new artists for manual Louder-fit review.

Spotify is intentionally NOT used as a discovery database here. In 2026 its
Browse/New Releases endpoint was removed, and Spotify platform data has usage
restrictions. Spotify links can be added later as outbound references only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
ARTISTS_PATH = ROOT / "data" / "artists.json"
RADAR_PATH = ROOT / "data" / "radar_2026.json"

YEAR = 2026
MB_BASE = "https://musicbrainz.org/ws/2/recording/"
USER_AGENT = os.environ.get(
    "MUSICBRAINZ_USER_AGENT",
    "LouderMX-Radar/1.0 (https://loudermx.com)"
)
BATCH_SIZE = int(os.environ.get("RADAR_ARTIST_BATCH", "60"))
REQUEST_GAP = float(os.environ.get("MUSICBRAINZ_REQUEST_GAP", "1.05"))

DISCOVERY_TAGS = [
    "indie rock",
    "post-punk",
    "alternative rock",
    "shoegaze",
    "indie pop",
    "garage rock",
    "dream pop",
    "britpop",
]

SUSPECT_WORDS = (
    "remaster",
    "remastered",
    "reissue",
    "anniversary",
    "deluxe edition",
    "super deluxe",
)


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def artist_credit(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for credit in item.get("artist-credit") or []:
        if isinstance(credit, str):
            parts.append(credit)
            continue
        if not isinstance(credit, dict):
            continue
        name = credit.get("name") or (credit.get("artist") or {}).get("name")
        if name:
            parts.append(str(name))
        join = credit.get("joinphrase")
        if join:
            parts.append(str(join))
    return "".join(parts).strip()


def mb_search(query: str, limit: int = 25) -> list[dict[str, Any]]:
    response = requests.get(
        MB_BASE,
        params={"query": query, "fmt": "json", "limit": limit},
        headers={"User-Agent": USER_AGENT},
        timeout=35,
    )
    response.raise_for_status()
    time.sleep(REQUEST_GAP)
    return response.json().get("recordings") or []


def suspicious(item: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            str(item.get("title") or ""),
            " ".join(str(r.get("title") or "") for r in item.get("releases") or [] if isinstance(r, dict)),
        ]
    ).casefold()
    return any(word in haystack for word in SUSPECT_WORDS)


DERIVATIVE_TITLE_RE = re.compile(
    r"(?:\(|\[|\s[-–—]\s).*\b(remix|remaster(?:ed)?|reissue|live|acoustic|demo|edit|version|session|mix)\b",
    re.IGNORECASE,
)


def year_in(value: str) -> int | None:
    match = re.search(r"\b(?:19|20)\d{2}\b", value or "")
    return int(match.group(0)) if match else None


def legacy_louder_titles(artists: list[dict[str, Any]]) -> set[tuple[str, str]]:
    legacy: set[tuple[str, str]] = set()
    for artist in artists:
        artist_name = norm(str(artist.get("name") or ""))
        if not artist_name:
            continue
        for track in artist.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            title = norm(str(track.get("title") or ""))
            first_year = year_in(str(track.get("first_played") or ""))
            if title and first_year and first_year < YEAR:
                legacy.add((artist_name, title))
    return legacy


def derivative_title(title: str) -> bool:
    return bool(DERIVATIVE_TITLE_RE.search(title or ""))


def candidate_from_mb(
    item: dict[str, Any],
    known_artists: set[str],
    legacy_titles: set[tuple[str, str]],
    signal: str,
) -> dict[str, Any] | None:
    first = str(item.get("first-release-date") or "")
    if not first.startswith(f"{YEAR}-") and first != str(YEAR):
        return None

    mbid = str(item.get("id") or "").strip()
    title = str(item.get("title") or "").strip()
    artist = artist_credit(item)
    if not mbid or not title or not artist:
        return None

    artist_key = norm(artist)
    title_key = norm(title)
    known = artist_key in known_artists

    # "Netamente 2026": if Louder already played this exact artist/title
    # before 2026, or the title explicitly identifies a remix/live/edit/etc.,
    # it is legacy/derivative material and must not enter the 2026 song queue.
    if (artist_key, title_key) in legacy_titles or derivative_title(title):
        return None

    suspect = suspicious(item)
    originality = "probable_2026" if known and not suspect else "review"
    operational_status = "pending" if known and not suspect else "review"
    return {
        "id": f"mb:{mbid}",
        "artist": artist,
        "title": title,
        "original_release_date": first,
        "original_release_year": YEAR,
        "originality": originality,
        "louder_fit": "yes" if known and not suspect else "review",
        "in_louder_catalog": known,
        "availability": "released",
        "download_status": operational_status,
        "downloaded_at": None,
        "programmed_at": None,
        "notes": "",
        "source_signals": [signal],
        "sources": {
            "musicbrainz": f"https://musicbrainz.org/recording/{mbid}"
        },
        "discovered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def merge(old: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    keep = dict(fresh)
    for field in (
        "download_status",
        "downloaded_at",
        "programmed_at",
        "notes",
        "louder_fit",
    ):
        if field in old:
            keep[field] = old[field]
    signals = list(dict.fromkeys((old.get("source_signals") or []) + (fresh.get("source_signals") or [])))
    keep["source_signals"] = signals
    sources = dict(old.get("sources") or {})
    sources.update(fresh.get("sources") or {})
    keep["sources"] = sources
    keep["discovered_at"] = old.get("discovered_at") or fresh.get("discovered_at")
    return keep


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artist-batch", type=int, default=BATCH_SIZE)
    parser.add_argument("--no-broad-discovery", action="store_true")
    args = parser.parse_args()

    artists_data = read_json(ARTISTS_PATH, {"artists": []})
    artists = [a for a in artists_data.get("artists") or [] if isinstance(a, dict) and a.get("name")]
    artists.sort(key=lambda a: int(a.get("plays") or 0), reverse=True)

    known_artists = {norm(str(a.get("name"))) for a in artists}
    legacy_titles = legacy_louder_titles(artists)
    print(f"legacy_louder_titles={len(legacy_titles)}")
    radar = read_json(
        RADAR_PATH,
        {
            "schema_version": 1,
            "year": YEAR,
            "updated_at": None,
            "scan_cursor": 0,
            "rules": {"original_release_year": YEAR},
            "tracks": [],
        },
    )
    existing = {str(x.get("id")): x for x in radar.get("tracks") or [] if isinstance(x, dict) and x.get("id")}

    cursor = int(radar.get("scan_cursor") or 0)
    if artists:
        batch = [artists[(cursor + i) % len(artists)] for i in range(min(args.artist_batch, len(artists)))]
    else:
        batch = []

    discovered: dict[str, dict[str, Any]] = {}

    for artist in batch:
        name = str(artist.get("name") or "").strip()
        if not name:
            continue
        query = f'artist:"{name.replace(chr(34), "")}" AND firstreleasedate:[{YEAR}-01-01 TO {YEAR}-12-31]'
        try:
            rows = mb_search(query, limit=25)
        except Exception as exc:
            print(f"MusicBrainz artist scan failed for {name}: {exc}")
            continue
        for row in rows:
            item = candidate_from_mb(row, known_artists, legacy_titles, "musicbrainz:louder-artist")
            if item:
                discovered[item["id"]] = item

    if not args.no_broad_discovery:
        for tag in DISCOVERY_TAGS:
            query = f'firstreleasedate:[{YEAR}-01-01 TO {YEAR}-12-31] AND tag:"{tag}"'
            try:
                rows = mb_search(query, limit=50)
            except Exception as exc:
                print(f"MusicBrainz tag scan failed for {tag}: {exc}")
                continue
            for row in rows:
                item = candidate_from_mb(row, known_artists, legacy_titles, f"musicbrainz:tag:{tag}")
                if not item:
                    continue
                if item["id"] in discovered:
                    discovered[item["id"]] = merge(discovered[item["id"]], item)
                else:
                    discovered[item["id"]] = item

    for track_id, item in discovered.items():
        if track_id in existing:
            existing[track_id] = merge(existing[track_id], item)
        else:
            existing[track_id] = item

    # Hard 2026 gate: stale/legacy tracks can never survive this dataset.
    tracks = [
        x for x in existing.values()
        if int(x.get("original_release_year") or 0) == YEAR
        and str(x.get("original_release_date") or "").startswith(str(YEAR))
        and (norm(str(x.get("artist") or "")), norm(str(x.get("title") or ""))) not in legacy_titles
        and not derivative_title(str(x.get("title") or ""))
    ]

    today = dt.date.today().isoformat()
    for track in tracks:
        release_date = str(track.get("original_release_date") or "")
        upcoming = len(release_date) >= 10 and release_date > today
        track["availability"] = "upcoming" if upcoming else "released"
        if upcoming:
            track["download_status"] = "upcoming"
        elif track.get("louder_fit") != "yes":
            track["download_status"] = "review"
        elif track.get("download_status") in {"upcoming", "review"}:
            track["download_status"] = "pending"

    tracks.sort(
        key=lambda x: (
            1 if x.get("availability") == "released" else 0,
            str(x.get("original_release_date") or ""),
            str(x.get("artist") or "").casefold(),
            str(x.get("title") or "").casefold(),
        ),
        reverse=True,
    )

    radar["year"] = YEAR
    radar["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    radar["scan_cursor"] = (cursor + len(batch)) % max(len(artists), 1)
    radar["tracks"] = tracks
    radar["stats"] = {
        "total": len(tracks),
        "released": sum(x.get("availability") == "released" for x in tracks),
        "upcoming": sum(x.get("availability") == "upcoming" for x in tracks),
        "pending": sum(x.get("download_status") == "pending" for x in tracks),
        "downloaded": sum(x.get("download_status") == "downloaded" for x in tracks),
        "programmed": sum(x.get("download_status") == "programmed" for x in tracks),
        "review_queue": sum(x.get("download_status") == "review" for x in tracks),
        "discarded": sum(x.get("download_status") == "discarded" for x in tracks),
        "louder_yes": sum(x.get("louder_fit") == "yes" for x in tracks),
        "review": sum(x.get("louder_fit") == "review" for x in tracks),
    }
    write_json(RADAR_PATH, radar)
    print(json.dumps(radar["stats"], ensure_ascii=False))


if __name__ == "__main__":
    main()
