#!/usr/bin/env python3
"""Update editorial/download state for one Radar 2026 track."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "radar_2026.json"
VALID = {"pending", "downloaded", "programmed", "discarded"}
FITS = {"yes", "review", "no"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True)
    p.add_argument("--status", choices=sorted(VALID))
    p.add_argument("--fit", choices=sorted(FITS))
    p.add_argument("--note")
    args = p.parse_args()

    data = json.loads(PATH.read_text(encoding="utf-8"))
    found = False
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for track in data.get("tracks") or []:
        if track.get("id") != args.id:
            continue
        found = True
        if args.status:
            track["download_status"] = args.status
            if args.status == "downloaded":
                track["downloaded_at"] = now
            if args.status == "programmed":
                track["programmed_at"] = now
        if args.fit:
            track["louder_fit"] = args.fit
        if args.note is not None:
            track["notes"] = args.note
        break

    if not found:
        raise SystemExit(f"Track id not found: {args.id}")

    data["updated_at"] = now
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
