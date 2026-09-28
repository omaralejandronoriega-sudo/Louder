#!/usr/bin/env python3
"""Incrementally ingest MegaSeg history exports into history_megaseg.json.

Drop CSV/TSV/TXT/LOG exports in data/history/megaseg-inbox/. The importer is
idempotent for the normal incremental case: an event is counted only when its
timestamp is newer than the last known timestamp for that artist/track.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data" / "history" / "history_megaseg.json"
INBOX = ROOT / "data" / "history" / "megaseg-inbox"

DATE_KEYS = ("datetime", "date time", "timestamp", "played at", "played_at", "time")
DATE_ONLY_KEYS = ("date", "played date")
TIME_ONLY_KEYS = ("time", "played time")
ARTIST_KEYS = ("artist", "performer", "author")
TITLE_KEYS = ("title", "song", "track", "name")
ALBUM_KEYS = ("album", "release")


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def clean_key(value: str) -> str:
    return re.sub(r"[_\-]+", " ", str(value or "").strip().casefold())


def parse_dt(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("T", " ").replace("Z", "").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


def get_value(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    normalized = {clean_key(k): str(v or "").strip() for k, v in row.items()}
    for alias in aliases:
        value = normalized.get(alias)
        if value:
            return value
    return ""


def row_datetime(row: dict[str, str]) -> datetime | None:
    direct = get_value(row, DATE_KEYS)
    dt = parse_dt(direct)
    if dt:
        return dt
    date = get_value(row, DATE_ONLY_KEYS)
    clock = get_value(row, TIME_ONLY_KEYS)
    return parse_dt(f"{date} {clock}".strip())


def sniff_rows(path: Path) -> Iterable[dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if not text.strip():
        return []
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if reader.fieldnames and len(reader.fieldnames) >= 2:
        return list(reader)

    # Fallback for simple MegaSeg log lines:
    # date/time<TAB>artist<TAB>title<TAB>album
    out: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = [x.strip() for x in re.split(r"\t|\s+\|\s+", line) if x.strip()]
        if len(parts) >= 3:
            out.append({
                "datetime": parts[0],
                "artist": parts[1],
                "title": parts[2],
                "album": parts[3] if len(parts) > 3 else "",
            })
    return out


def load_history() -> dict:
    if not HISTORY.exists():
        return {"version": 1, "source": "megaseg", "generated_at": "", "artists": {}}
    data = json.loads(HISTORY.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("Invalid MegaSeg history JSON")
    data.setdefault("version", 1)
    data.setdefault("source", "megaseg")
    data.setdefault("artists", {})
    return data


def index_tracks(artist_record: list) -> dict[str, list]:
    tracks = artist_record[4] if len(artist_record) > 4 and isinstance(artist_record[4], list) else []
    return {norm(t[0]): t for t in tracks if isinstance(t, list) and t}


def apply_event(store: dict, artist_name: str, title: str, album: str, dt: datetime) -> bool:
    artist_key = norm(artist_name)
    track_key = norm(title)
    if not artist_key or not track_key:
        return False

    artists = store["artists"]
    artist = artists.get(artist_key)
    stamp = dt.strftime("%Y-%m-%d %H:%M:%S")
    if artist is None:
        artists[artist_key] = [artist_name, stamp, stamp, 1, [[title, album, 1, stamp, stamp]]]
        return True

    tracks = index_tracks(artist)
    track = tracks.get(track_key)
    if track is None:
        artist[3] = int(artist[3] or 0) + 1
        artist[2] = max(str(artist[2] or ""), stamp)
        artist[1] = min(str(artist[1] or stamp), stamp)
        artist[4].append([title, album, 1, stamp, stamp])
        return True

    last = parse_dt(track[4] if len(track) > 4 else "")
    if last and dt <= last:
        return False

    track[2] = int(track[2] or 0) + 1
    track[4] = stamp
    if album and not str(track[1] or "").strip():
        track[1] = album
    artist[3] = int(artist[3] or 0) + 1
    artist[2] = max(str(artist[2] or ""), stamp)
    artist[1] = min(str(artist[1] or stamp), stamp)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", default=str(INBOX))
    args = parser.parse_args()

    inbox = Path(args.inbox)
    store = load_history()
    files = sorted(
        p for p in inbox.rglob("*")
        if p.is_file() and p.suffix.casefold() in {".csv", ".tsv", ".txt", ".log"}
    ) if inbox.exists() else []

    added = 0
    skipped = 0
    bad = 0
    for path in files:
        for row in sniff_rows(path):
            artist = get_value(row, ARTIST_KEYS)
            title = get_value(row, TITLE_KEYS)
            album = get_value(row, ALBUM_KEYS)
            dt = row_datetime(row)
            if not artist or not title or not dt:
                bad += 1
                continue
            if apply_event(store, artist, title, album, dt):
                added += 1
            else:
                skipped += 1

    store["generated_at"] = datetime.now(timezone.utc).isoformat()
    store["ingest"] = {
        "files_seen": len(files),
        "events_added": added,
        "events_skipped_existing": skipped,
        "rows_invalid": bad,
        "mode": "incremental_newer_than_track_last_played",
    }

    if added:
        HISTORY.write_text(
            json.dumps(store, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    print(json.dumps(store["ingest"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
