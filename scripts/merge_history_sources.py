#!/usr/bin/env python3
"""Merge Louder history sources into the static Artistas snapshot.

Sources are intentionally kept separate:
- Last.fm: long-term scrobble archive (artist-level aggregate)
- MegaSeg: detailed local playout logs (track-level aggregate)
- YesStreaming: current server catalog (programming inventory, not play count)

We NEVER blindly add Last.fm + MegaSeg because their date ranges overlap.
For an artist without a migrated canonical counter, the baseline play count is
max(Last.fm, MegaSeg). Existing migrated counters are preserved when larger.
YesStreaming live events are applied later by live/sync_history.py only after
this per-artist baseline cutoff.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "artists.json"
LASTFM = ROOT / "data" / "history" / "history_lastfm.json"
MEGASEG = ROOT / "data" / "history" / "history_megaseg.json"
YESSTREAMING = ROOT / "data" / "history" / "history_yesstreaming_catalog.json"

MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

# Public WordPress crawl finished at 2026-09-25 20:10:51 UTC.
# Historial Louder records local radio time (UTC-6 in San Luis Potosí), so
# every already-migrated profile uses this local snapshot time as the minimum
# live-sync cutoff. This prevents Sheet/YesStreaming events already reflected
# in WordPress from being counted a second time.
MIGRATED_SNAPSHOT_LOCAL = datetime(2026, 9, 25, 14, 10, 51)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def slugify(value: str) -> str:
    return normalize(value).replace(" ", "-").strip("-") or "artista"


def unique_slug(name: str, existing: set[str]) -> str:
    base = slugify(name)
    candidate = base
    n = 2
    while candidate in existing:
        candidate = f"{base}-{n}"
        n += 1
    existing.add(candidate)
    return candidate


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def parse_date(value: Any, end_of_day: bool = False) -> datetime | None:
    raw = str(value or "").strip()
    if not raw or raw == "—":
        return None

    iso = raw.replace("Z", "")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
    ):
        try:
            dt = datetime.strptime(iso, fmt)
            if end_of_day and all(token not in fmt for token in ("%H", "%M", "%S")):
                dt = datetime.combine(dt.date(), time(23, 59, 59))
            return dt
        except ValueError:
            pass

    match = re.search(
        r"(\d{1,2})\s+(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s+(\d{4})"
        r"(?:\s*[·|-]\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?",
        raw.casefold(),
    )
    if match:
        day, mon, year, hh, mm, ss = match.groups()
        if hh is None and end_of_day:
            return datetime(int(year), MONTHS[mon], int(day), 23, 59, 59)
        return datetime(
            int(year), MONTHS[mon], int(day),
            int(hh or 0), int(mm or 0), int(ss or 0),
        )
    return None


def human(dt: datetime | None, with_time: bool = False) -> str:
    if not dt:
        return ""
    months = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
    base = f"{dt.day} {months[dt.month - 1]} {dt.year}"
    if with_time and (dt.hour or dt.minute or dt.second):
        return f"{base} · {dt:%H:%M}"
    return base


def min_dt(values: list[datetime | None]) -> datetime | None:
    present = [x for x in values if x]
    return min(present) if present else None


def max_dt(values: list[datetime | None]) -> datetime | None:
    present = [x for x in values if x]
    return max(present) if present else None


def ensure_track(artist: dict[str, Any], by_track: dict[str, dict[str, Any]], title: str) -> dict[str, Any] | None:
    key = normalize(title)
    if not key:
        return None
    track = by_track.get(key)
    if track is None:
        track = {
            "title": title,
            "album": "",
            "artwork": "",
            "plays": 0,
            "first_played": "",
            "last_played": "",
            "sources": [],
            "source_stats": {},
        }
        artist.setdefault("tracks", []).append(track)
        by_track[key] = track
    track.setdefault("sources", [])
    track.setdefault("source_stats", {})
    return track


def add_source(target: dict[str, Any], source: str) -> None:
    sources = target.setdefault("sources", [])
    if source not in sources:
        sources.append(source)


def main() -> int:
    store = load(DATA)
    artists = store.get("artists") or []
    lastfm = (load(LASTFM).get("artists") or {})
    megaseg = (load(MEGASEG).get("artists") or {})
    yesstreaming = (load(YESSTREAMING).get("artists") or {})

    by_artist = {
        normalize(a.get("name", "")): a
        for a in artists
        if a.get("name")
    }
    slugs = {a.get("slug", "") for a in artists if a.get("slug")}
    existing_keys = set(by_artist)

    all_keys = set(lastfm) | set(megaseg) | set(yesstreaming)
    created = 0

    for key in sorted(all_keys):
        lf = lastfm.get(key)
        mg = megaseg.get(key)
        ys = yesstreaming.get(key)

        name = (
            (lf[0] if lf else "")
            or (mg[0] if mg else "")
            or (ys[0] if ys else "")
            or key.title()
        )
        artist = by_artist.get(key)
        was_existing = artist is not None

        if artist is None:
            artist = {
                "slug": unique_slug(name, slugs),
                "name": name,
                "source_url": "",
                "image": "",
                "genres": [],
                "plays": 0,
                "first_played": "",
                "last_played": "",
                "bio": "",
                "official_url": "",
                "social": [],
                "tracks": [],
                "related": [],
                "catalog_status": "history_only",
                "sources": [],
                "source_stats": {},
            }
            artists.append(artist)
            by_artist[key] = artist
            created += 1

        artist.setdefault("sources", [])
        artist.setdefault("source_stats", {})

        existing_plays = int(artist.get("plays") or 0)
        lf_plays = int(lf[3] or 0) if lf else 0
        mg_plays = int(mg[3] or 0) if mg else 0
        artist["plays"] = max(existing_plays, lf_plays, mg_plays)

        existing_first = parse_date(artist.get("first_played"))
        existing_last = parse_date(artist.get("last_played"), end_of_day=True)
        lf_first = parse_date(lf[1]) if lf else None
        lf_last = parse_date(lf[2], end_of_day=True) if lf else None
        mg_first = parse_date(mg[1]) if mg else None
        mg_last = parse_date(mg[2]) if mg else None

        first = min_dt([existing_first, lf_first, mg_first])
        last = max_dt([existing_last, lf_last, mg_last])
        if first:
            artist["first_played"] = human(first)
        if last:
            artist["last_played"] = human(last, with_time=True)

        cutoff = last
        if was_existing:
            cutoff = max_dt([cutoff, MIGRATED_SNAPSHOT_LOCAL])
        if cutoff:
            artist["history_cutoff"] = cutoff.isoformat(timespec="seconds")

        if lf:
            add_source(artist, "lastfm")
            artist["source_stats"]["lastfm"] = {
                "plays": lf_plays,
                "first_played": lf[1],
                "last_played": lf[2],
                "distinct_tracks": int(lf[4] or 0),
            }
        if mg:
            add_source(artist, "megaseg")
            artist["source_stats"]["megaseg"] = {
                "plays": mg_plays,
                "first_played": mg[1],
                "last_played": mg[2],
                "tracks": len(mg[4] or []),
            }
        if ys:
            add_source(artist, "yesstreaming")
            active = sum(1 for t in (ys[1] or []) if "ACTIVA" in str(t[2] or "").upper())
            artist["source_stats"]["yesstreaming"] = {
                "catalog_tracks": len(ys[1] or []),
                "active_tracks": active,
            }

        if not was_existing:
            if ys and (lf or mg):
                artist["catalog_status"] = "programmed_history"
            elif ys:
                artist["catalog_status"] = "programmed_only"
            else:
                artist["catalog_status"] = "history_only"

        tracks = artist.setdefault("tracks", [])
        by_track = {
            normalize(t.get("title", "")): t
            for t in tracks
            if isinstance(t, dict) and t.get("title")
        }
        for track in tracks:
            if not isinstance(track, dict):
                continue
            track.setdefault("sources", [])
            track.setdefault("source_stats", {})
            if was_existing:
                add_source(track, "migrated")

        if mg:
            for item in mg[4] or []:
                title, album, plays, first_s, last_s = item
                track = ensure_track(artist, by_track, str(title or ""))
                if not track:
                    continue
                add_source(track, "megaseg")
                track["source_stats"]["megaseg"] = {
                    "plays": int(plays or 0),
                    "first_played": first_s,
                    "last_played": last_s,
                }
                if not track.get("album") and album:
                    track["album"] = album
                track["plays"] = max(int(track.get("plays") or 0), int(plays or 0))
                old_first = parse_date(track.get("first_played"))
                old_last = parse_date(track.get("last_played"), end_of_day=True)
                new_first = parse_date(first_s)
                new_last = parse_date(last_s)
                tfirst = min_dt([old_first, new_first])
                tlast = max_dt([old_last, new_last])
                if tfirst:
                    track["first_played"] = human(tfirst)
                if tlast:
                    track["last_played"] = human(tlast, with_time=True)

        if ys:
            for item in ys[1] or []:
                title, rotation, status, file_path, uploaded = item
                track = ensure_track(artist, by_track, str(title or ""))
                if not track:
                    continue
                add_source(track, "yesstreaming")
                track["source_stats"]["yesstreaming"] = {
                    "rotation": rotation,
                    "status": status,
                    "file": file_path,
                    "uploaded": uploaded,
                }
                if not track.get("album"):
                    track["album"] = "Programación YesStreaming"

        if lf and lf[5]:
            track = ensure_track(artist, by_track, str(lf[5]))
            if track:
                add_source(track, "lastfm")
                track["source_stats"]["lastfm"] = {"first_registered_track": True}
                if not track.get("first_played") and lf[1]:
                    track["first_played"] = human(parse_date(lf[1]))

        artist["tracks"] = sorted(
            [t for t in artist.get("tracks") or [] if isinstance(t, dict) and t.get("title")],
            key=lambda t: (-int(t.get("plays") or 0), normalize(t.get("title", ""))),
        )

    store["artists"] = artists
    store["history_merge"] = {
        "strategy": "preserve_migrated_else_max_lastfm_megaseg_with_snapshot_cutoff",
        "lastfm_artists": len(lastfm),
        "megaseg_artists": len(megaseg),
        "yesstreaming_artists": len(yesstreaming),
        "source_union_artists": len(all_keys),
        "base_artists": len(existing_keys),
        "created_history_artists": created,
        "merged_artists": len(artists),
        "merged_at": datetime.utcnow().isoformat() + "Z",
    }
    DATA.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"merged artists={len(artists)} created={created} "
        f"lastfm={len(lastfm)} megaseg={len(megaseg)} yesstreaming={len(yesstreaming)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
