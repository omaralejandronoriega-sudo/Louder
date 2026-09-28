#!/usr/bin/env python3
"""Resolve missing album artwork through MusicBrainz + Cover Art Archive.

Only metadata/URLs are stored in GitHub. MusicBrainz requests are rate-limited
to <= 1 request/second as required by the public web service.
"""

from __future__ import annotations

import argparse
import json
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
ART_FILE = ROOT / "data" / "album_art.json"
MB = "https://musicbrainz.org/ws/2/release-group/"
CAA = "https://coverartarchive.org/release-group"
UA = "LouderMX-Artistas/1.0 (https://loudermx.com; contact via site)"


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def key(artist: str, album: str) -> str:
    return norm(artist) + "|" + norm(album)


def load(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


class MusicBrainz:
    def __init__(self) -> None:
        self.last = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    def search_release_group(self, artist: str, album: str) -> str:
        elapsed = time.monotonic() - self.last
        if elapsed < 1.10:
            time.sleep(1.10 - elapsed)

        query = f'releasegroup:"{album}" AND artist:"{artist}"'
        r = self.session.get(
            MB,
            params={"query": query, "fmt": "json", "limit": 5},
            timeout=35,
        )
        self.last = time.monotonic()
        if r.status_code == 503:
            return ""
        r.raise_for_status()
        rows = r.json().get("release-groups") or []

        exact = [
            row for row in rows
            if norm(row.get("title", "")) == norm(album)
        ]
        candidates = exact or rows
        if not candidates:
            return ""

        candidates = sorted(
            candidates,
            key=lambda row: int(row.get("score") or 0),
            reverse=True,
        )
        return str(candidates[0].get("id") or "")


def art_exists(session: requests.Session, mbid: str) -> bool:
    if not mbid:
        return False
    try:
        r = session.head(
            f"{CAA}/{mbid}/front-500",
            headers={"User-Agent": UA},
            allow_redirects=True,
            timeout=30,
        )
        return r.status_code == 200
    except Exception:
        return False


def itunes_art(session: requests.Session, artist: str, album: str) -> tuple[str, str]:
    """Fallback for releases missing in Cover Art Archive."""
    try:
        r = session.get(
            "https://itunes.apple.com/search",
            params={"media": "music", "entity": "song", "limit": 12, "term": f"{artist} {album}"},
            headers={"User-Agent": UA},
            timeout=30,
        )
        r.raise_for_status()
        rows = r.json().get("results") or []
        want_artist = norm(artist)
        want_album = norm(album)
        best = None
        best_score = -1
        for row in rows:
            a = norm(row.get("artistName", ""))
            al = norm(row.get("collectionName", ""))
            score = 0
            if a == want_artist:
                score += 100
            elif a and want_artist and (a in want_artist or want_artist in a):
                score += 30
            if al == want_album:
                score += 120
            elif al and want_album and (al in want_album or want_album in al):
                score += 45
            if score > best_score and row.get("artworkUrl100"):
                best = row
                best_score = score
        if not best or best_score < 100:
            return "", ""
        url = str(best.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")
        return url, str(best.get("collectionName") or album)
    except Exception:
        return "", ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=150)
    args = parser.parse_args()

    artist_store = load(ARTISTS_FILE, {"artists": []})
    artists = artist_store.get("artists") or []
    if len(artists) < 500:
        raise SystemExit(f"Base Artistas snapshot is not ready: only {len(artists)} artists.")

    store = load(ART_FILE, {"version": 1, "updated_at": None, "albums": {}})
    albums = store.setdefault("albums", {})

    pending: list[tuple[str, str]] = []
    seen: set[str] = set()
    for artist in artists:
        artist_name = str(artist.get("name") or "")
        for track in artist.get("tracks") or []:
            if track.get("artwork"):
                continue
            album = str(track.get("album") or "").strip()
            if not album or album in {"Álbum no identificado", "Recién incorporada al historial", "Programación YesStreaming"}:
                continue
            k = key(artist_name, album)
            existing = albums.get(k) or {}
            if not k or k in seen or existing.get("url") or existing.get("status") == "not_found_itunes":
                continue
            seen.add(k)
            pending.append((artist_name, album))

    if args.limit > 0:
        pending = pending[: args.limit]

    print(f"missing_album_art={len(pending)}")
    mb = MusicBrainz()
    session = requests.Session()

    for i, (artist, album) in enumerate(pending, start=1):
        k = key(artist, album)
        try:
            mbid = mb.search_release_group(artist, album)
            if mbid and art_exists(session, mbid):
                albums[k] = {
                    "artist": artist,
                    "album": album,
                    "release_group_mbid": mbid,
                    "url": f"{CAA}/{mbid}/front-500",
                    "source": "Cover Art Archive",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                print(f"{i}/{len(pending)} OK {artist} — {album}")
            else:
                itunes_url, itunes_album = itunes_art(session, artist, album)
                if itunes_url:
                    albums[k] = {
                        "artist": artist,
                        "album": itunes_album or album,
                        "release_group_mbid": mbid,
                        "url": itunes_url,
                        "source": "iTunes Search",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    print(f"{i}/{len(pending)} ITUNES {artist} — {album}")
                else:
                    albums[k] = {
                        "artist": artist,
                        "album": album,
                        "release_group_mbid": mbid,
                        "url": "",
                        "source": "MusicBrainz + iTunes Search",
                        "status": "not_found_itunes",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    print(f"{i}/{len(pending)} MISS {artist} — {album}")
        except Exception as exc:
            print(f"{i}/{len(pending)} ERROR {artist} — {album}: {exc}")

        if i % 25 == 0:
            store["updated_at"] = datetime.now(timezone.utc).isoformat()
            ART_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    store["updated_at"] = datetime.now(timezone.utc).isoformat()
    ART_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
