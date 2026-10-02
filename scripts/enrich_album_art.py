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

import enrichment_state as es

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


PLACEHOLDER_ALBUMS = {
    "", "album no identificado", "album desconocido", "unknown album",
    "recien incorporada al historial", "sin album", "no album",
    "programacion yesstreaming", "yesstreaming", "programacion", "programming",
}


def is_placeholder_album(album: str) -> bool:
    return norm(album) in PLACEHOLDER_ALBUMS


def key(artist: str, album: str) -> str:
    return norm(artist) + "|" + norm(album)


def track_key(artist: str, title: str) -> str:
    return "track|" + norm(artist) + "|" + norm(title)


def cache_key(artist: str, album: str, title: str) -> str:
    return track_key(artist, title) if is_placeholder_album(album) else key(artist, album)


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


def itunes_track_art(session: requests.Session, artist: str, title: str) -> str:
    """Fallback cover for a track with no useful parent-album metadata."""
    try:
        r = session.get(
            "https://itunes.apple.com/search",
            params={"media": "music", "entity": "song", "limit": 12, "term": f"{artist} {title}"},
            headers={"User-Agent": UA},
            timeout=30,
        )
        r.raise_for_status()
        want_artist = norm(artist)
        want_title = norm(title)
        best = None
        best_score = -1
        for row in r.json().get("results") or []:
            a = norm(row.get("artistName", ""))
            t = norm(row.get("trackName", ""))
            score = 0
            if a == want_artist:
                score += 100
            elif a and want_artist and (a in want_artist or want_artist in a):
                score += 25
            if t == want_title:
                score += 140
            elif t and want_title and (t in want_title or want_title in t):
                score += 35
            if score > best_score and row.get("artworkUrl100"):
                best = row
                best_score = score
        if not best or best_score < 200:
            return ""
        return str(best.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")
    except Exception:
        return ""


def validated_art(
    session: requests.Session,
    url: str,
) -> tuple[str, str]:
    ok, final_url, method = es.validate_remote_image(session, url, timeout=20)
    return (final_url, method) if ok else ("", method)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=350)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    artist_store = load(ARTISTS_FILE, {"artists": []})
    artists = artist_store.get("artists") or []
    if len(artists) < 500:
        raise SystemExit(f"Base Artistas snapshot is not ready: only {len(artists)} artists.")

    store = load(ART_FILE, {"version": 2, "updated_at": None, "albums": {}})
    store["version"] = max(int(store.get("version") or 1), 2)
    albums = store.setdefault("albums", {})
    now = es.utcnow()

    candidates: dict[str, dict[str, str]] = {}
    for artist in artists:
        artist_name = str(artist.get("name") or "").strip()
        for track in artist.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            title = str(track.get("title") or "").strip()
            if not title:
                continue
            album = str(track.get("album") or "").strip()
            k = cache_key(artist_name, album, title)
            if not k:
                continue
            mode = "track" if is_placeholder_album(album) else "album"
            row = candidates.setdefault(
                k,
                {
                    "artist": artist_name,
                    "album": album,
                    "title": title,
                    "mode": mode,
                    "track_artwork": "",
                },
            )
            track_art = str(track.get("artwork") or "").strip()
            if track_art and not row["track_artwork"]:
                row["track_artwork"] = track_art

    pending: list[tuple[str, dict[str, str]]] = []
    for k, candidate in candidates.items():
        existing = albums.get(k) or {}
        if es.is_due(existing, refresh=args.refresh, now=now):
            pending.append((k, candidate))

    pending.sort(
        key=lambda item: (
            0 if item[1].get("track_artwork") else 1,
            norm(item[1]["artist"]),
            norm(item[1].get("album") or item[1].get("title") or ""),
        )
    )
    if args.limit > 0:
        pending = pending[: args.limit]

    status_counts = {"complete": 0, "partial": 0, "retry": 0, "not_found": 0, "legacy": 0}
    for value in albums.values():
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or "legacy")
        status_counts[status if status in status_counts else "legacy"] += 1
    real_missing_before = sum(
        1 for k in candidates
        if not (
            isinstance(albums.get(k), dict)
            and albums[k].get("status") == "complete"
            and albums[k].get("validated") is True
            and albums[k].get("url")
        )
    )
    print(
        f"album_art_queue albums={len(candidates)} due={len(pending)} "
        f"real_missing_album_art={real_missing_before}"
    )

    mb = MusicBrainz()
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    for i, (k, candidate) in enumerate(pending, start=1):
        artist = candidate["artist"]
        album = candidate.get("album", "")
        title = candidate.get("title", "")
        mode = candidate.get("mode", "album")
        track_artwork = candidate.get("track_artwork", "")
        existing = albums.get(k) or {}
        attempt = es.utcnow()
        try:
            final_url = ""
            validation_method = ""
            source = ""
            mbid = str(existing.get("release_group_mbid") or "")
            matched_album = album
            matched_title = title

            if track_artwork:
                final_url, validation_method = validated_art(session, track_artwork)
                if final_url:
                    source = "Historical track artwork"

            if not final_url and mode == "album":
                mbid = mb.search_release_group(artist, album)
                if mbid and art_exists(session, mbid):
                    caa_url = f"{CAA}/{mbid}/front-500"
                    final_url, validation_method = validated_art(session, caa_url)
                    if final_url:
                        source = "Cover Art Archive"

            if not final_url and mode == "album":
                itunes_url, itunes_album = itunes_art(session, artist, album)
                if itunes_url:
                    validated, validation_method = validated_art(session, itunes_url)
                    if validated:
                        final_url = validated
                        matched_album = itunes_album or album
                        source = "iTunes Search"

            if not final_url and mode == "track":
                itunes_url = itunes_track_art(session, artist, title)
                if itunes_url:
                    validated, validation_method = validated_art(session, itunes_url)
                    if validated:
                        final_url = validated
                        source = "iTunes Track Search"

            if final_url:
                albums[k] = {
                    "artist": artist,
                    "album": matched_album,
                    "track_title": matched_title,
                    "mode": mode,
                    "release_group_mbid": mbid,
                    "url": final_url,
                    "source": source,
                    "status": "complete",
                    "validated": True,
                    "validated_at": es.iso(attempt),
                    "validation_method": validation_method,
                    "checked_at": es.iso(attempt),
                    "next_retry_at": "",
                    "attempt_count": int(existing.get("attempt_count") or 0) + 1,
                    "updated_at": es.iso(attempt),
                }
                label = album or title
                print(f"{i}/{len(pending)} complete {artist} — {label} [{source}]")
            else:
                status = "partial" if mbid else "not_found"
                albums[k] = {
                    "artist": artist,
                    "album": album,
                    "track_title": title,
                    "mode": mode,
                    "release_group_mbid": mbid,
                    "url": "",
                    "source": "MusicBrainz + Cover Art Archive + iTunes",
                    "status": status,
                    "validated": False,
                    "checked_at": es.iso(attempt),
                    "next_retry_at": es.next_retry_at(status, attempt),
                    "attempt_count": int(existing.get("attempt_count") or 0) + 1,
                    "updated_at": es.iso(attempt),
                }
                label = album or title
                print(f"{i}/{len(pending)} {status} {artist} — {label}")
        except Exception as exc:
            row = dict(existing)
            row.update({
                "artist": artist,
                "album": album,
                "track_title": title,
                "mode": mode,
                "status": "retry",
                "validated": False,
                "checked_at": es.iso(attempt),
                "next_retry_at": es.next_retry_at("retry", attempt),
                "attempt_count": int(existing.get("attempt_count") or 0) + 1,
                "last_error": str(exc)[:300],
                "updated_at": es.iso(attempt),
            })
            albums[k] = row
            label = album or title
            print(f"{i}/{len(pending)} retry {artist} — {label}: {exc}")

        if i % 25 == 0:
            store["updated_at"] = es.iso(es.utcnow())
            ART_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    store["updated_at"] = es.iso(es.utcnow())
    ART_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = {"complete": 0, "partial": 0, "retry": 0, "not_found": 0, "legacy": 0}
    for value in albums.values():
        if not isinstance(value, dict):
            continue
        status = str(value.get("status") or "legacy")
        counts[status if status in counts else "legacy"] += 1
    real_missing_after = sum(
        1 for k in candidates
        if not (
            isinstance(albums.get(k), dict)
            and albums[k].get("status") == "complete"
            and albums[k].get("validated") is True
            and albums[k].get("url")
        )
    )
    print(
        "album_art_result "
        f"complete={counts['complete']} partial={counts['partial']} retry={counts['retry']} "
        f"not_found={counts['not_found']} legacy={counts['legacy']} "
        f"real_missing_album_art={real_missing_after}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
