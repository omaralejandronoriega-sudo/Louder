#!/usr/bin/env python3
"""Apply only NEW YesStreaming/Sheet history to the merged Louder snapshot.

The baseline is first rebuilt from Last.fm + MegaSeg + YesStreaming catalog by
scripts/merge_history_sources.py. This process then adds only rows newer than
each artist's history_cutoff, preventing repeated or cross-source inflation.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "artists.json"
SHEET_ID = "1UrWsD2vn0Az-8tBlMELqxjBXCcxZzHwobqcqxbY0uEU"
SHEET_NAME = "Historial Louder"
MONTHS = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def slugify(value: str) -> str:
    return normalize(value).replace(" ", "-").strip("-") or "artista"


def parse_dt(date_value: str, time_value: str = "") -> datetime | None:
    if time_value == "" and "T" in str(date_value):
        try:
            return datetime.fromisoformat(str(date_value).replace("Z", ""))
        except ValueError:
            pass
    raw_date = str(date_value or "").strip()
    raw_time = str(time_value or "").strip() or "00:00:00"
    candidates = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(f"{raw_date} {raw_time}", fmt)
        except ValueError:
            pass
    return None


def human(dt: datetime | None, with_time: bool = False) -> str:
    if not dt:
        return "—"
    base = f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"
    return f"{base} · {dt:%H:%M}" if with_time else base


def fetch_rows() -> list[dict[str, Any]]:
    url = (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq"
        f"?tqx=out:csv&sheet={quote(SHEET_NAME)}"
    )
    response = requests.get(
        url,
        timeout=45,
        headers={"User-Agent": "LouderMX-Artistas-Live/2.0 (+https://loudermx.com)"},
    )
    response.raise_for_status()

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for cols in csv.reader(io.StringIO(response.text)):
        if len(cols) < 4:
            continue
        date_value, time_value, artist, title = cols[:4]
        artist = artist.strip()
        title = title.strip()
        if not artist or not title or normalize(artist) in {"artist", "artista"}:
            continue
        dt = parse_dt(date_value, time_value)
        if not dt:
            continue
        fingerprint = (normalize(artist), normalize(title), dt.isoformat(timespec="seconds"))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        rows.append({"artist": artist, "title": title, "dt": dt})
    return rows


def unique_slug(name: str, existing: set[str]) -> str:
    base = slugify(name)
    candidate = base
    n = 2
    while candidate in existing:
        candidate = f"{base}-{n}"
        n += 1
    existing.add(candidate)
    return candidate


def add_source(target: dict[str, Any], source: str) -> None:
    sources = target.setdefault("sources", [])
    if source not in sources:
        sources.append(source)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-min", type=int, default=7000)
    args = parser.parse_args()

    store = json.loads(DATA.read_text(encoding="utf-8"))
    artists = store.get("artists") or []
    if len(artists) < args.require_min:
        raise SystemExit(
            f"Refusing live deploy: merged snapshot has only {len(artists)} artists "
            f"(minimum {args.require_min})."
        )

    rows = fetch_rows()
    grouped: dict[str, list[dict[str, Any]]] = {}
    display_names: dict[str, str] = {}
    for row in rows:
        key = normalize(row["artist"])
        grouped.setdefault(key, []).append(row)
        display_names.setdefault(key, row["artist"])

    by_artist = {normalize(a.get("name", "")): a for a in artists if a.get("name")}
    slugs = {a.get("slug", "") for a in artists if a.get("slug")}
    applied = 0
    touched = 0

    for key, live_rows in grouped.items():
        artist = by_artist.get(key)
        if artist is None:
            name = display_names[key]
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
                "catalog_status": "live_only",
                "sources": [],
                "source_stats": {},
            }
            artists.append(artist)
            by_artist[key] = artist

        cutoff = parse_dt(str(artist.get("history_cutoff") or ""))
        new_rows = [row for row in live_rows if cutoff is None or row["dt"] > cutoff]
        if not new_rows:
            continue

        touched += 1
        applied += len(new_rows)
        add_source(artist, "yesstreaming_live")
        stats = artist.setdefault("source_stats", {})
        stats["yesstreaming_live"] = {
            "plays_after_baseline": len(new_rows),
            "first_played": min(r["dt"] for r in new_rows).isoformat(timespec="seconds"),
            "last_played": max(r["dt"] for r in new_rows).isoformat(timespec="seconds"),
        }

        artist["plays"] = int(artist.get("plays") or 0) + len(new_rows)
        first_new = min(row["dt"] for row in new_rows)
        latest = max(row["dt"] for row in new_rows)
        if not artist.get("first_played"):
            artist["first_played"] = human(first_new)
        artist["last_played"] = human(latest, with_time=True)
        artist["history_cutoff"] = latest.isoformat(timespec="seconds")

        by_track = {
            normalize(t.get("title", "")): t
            for t in (artist.get("tracks") or [])
            if isinstance(t, dict) and t.get("title")
        }
        per_track: dict[str, list[dict[str, Any]]] = {}
        names: dict[str, str] = {}
        for row in new_rows:
            tkey = normalize(row["title"])
            per_track.setdefault(tkey, []).append(row)
            names.setdefault(tkey, row["title"])

        for tkey, trows in per_track.items():
            first = min(row["dt"] for row in trows)
            last = max(row["dt"] for row in trows)
            track = by_track.get(tkey)
            if track is None:
                track = {
                    "title": names[tkey],
                    "album": "Recién incorporada al historial",
                    "artwork": "",
                    "plays": 0,
                    "first_played": human(first),
                    "last_played": human(last, with_time=True),
                    "sources": [],
                    "source_stats": {},
                }
                artist.setdefault("tracks", []).append(track)
                by_track[tkey] = track
            add_source(track, "yesstreaming_live")
            track.setdefault("source_stats", {})["yesstreaming_live"] = {
                "plays_after_baseline": len(trows),
                "first_played": first.isoformat(timespec="seconds"),
                "last_played": last.isoformat(timespec="seconds"),
            }
            track["plays"] = int(track.get("plays") or 0) + len(trows)
            if not track.get("first_played"):
                track["first_played"] = human(first)
            track["last_played"] = human(last, with_time=True)

    store["artists"] = artists
    store["live_history_rows_total"] = len(rows)
    store["live_history_rows_applied"] = applied
    store["live_history_artists_touched"] = touched
    store["live_history_updated_at"] = datetime.utcnow().isoformat() + "Z"
    DATA.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"sheet_rows={len(rows)} applied={applied} touched={touched} "
        f"artists={len(artists)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
