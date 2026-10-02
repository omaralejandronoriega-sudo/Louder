#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import build_artists as ba

ROOT = Path(__file__).resolve().parents[1]
ARTISTS = ROOT / "data" / "artists.json"
OUT = ROOT / "diagnostics" / "artist-identity-review.json"
OUT_MD = ROOT / "diagnostics" / "artist-identity-review.md"

HIGH_CONF_EXACT = {
    "louder",
    "louder radio",
    "louder mx",
    "loudermx",
    "mordaz",
    "the british corner",
    "station id",
    "promo louder",
    "promos louder",
    "jingle louder",
    "sam broadcaster",
    "megaseg",
    "yesstreaming",
}

HIGH_CONF_PATTERNS = [
    (re.compile(r"^the british corner\b", re.I), "program_name"),
    (re.compile(r"^louder\s+(?:station\s*id|promo|promos|jingle|sweep|liner|ident)\b", re.I), "station_asset"),
    (re.compile(r"^(?:station\s*id|jingle|sweep|liner|ident)\s+(?:louder|louder\s+radio)\b", re.I), "station_asset"),
    (re.compile(r"^(?:sam broadcaster|megaseg|yesstreaming)(?:\s|$)", re.I), "software_metadata"),
]

REVIEW_PATTERNS = [
    (re.compile(r"\b(?:station\s*id|jingle|sweep|liner|ident)\b", re.I), "possible_station_asset"),
    (re.compile(r"\b(?:radio edit|clean edit|instrumental bed)\b", re.I), "possible_track_metadata"),
    (re.compile(r"\.(?:mp3|wav|m4a|aac|flac)$", re.I), "filename_as_artist"),
    (re.compile(r"^\d{1,2}[._ -]+.+"), "numbered_prefix"),
]


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def summarize(a: dict[str, Any], reason: str, confidence: str) -> dict[str, Any]:
    tracks = []
    for t in (a.get("tracks") or [])[:8]:
        if not isinstance(t, dict):
            continue
        tracks.append({
            "title": t.get("title") or "",
            "album": t.get("album") or "",
            "plays": int(t.get("plays") or 0),
            "sources": t.get("sources") or [],
        })
    return {
        "name": a.get("name") or "",
        "slug": a.get("slug") or "",
        "reason": reason,
        "confidence": confidence,
        "plays": int(a.get("plays") or 0),
        "catalog_status": a.get("catalog_status") or "",
        "sources": a.get("sources") or [],
        "tracks": tracks,
    }


def main() -> int:
    store = load(ARTISTS)
    raw = [a for a in (store.get("artists") or []) if isinstance(a, dict) and str(a.get("name") or "").strip()]
    exact_names = {ba.artist_key(str(a.get("name") or "")) for a in raw}

    high = []
    review = []
    seen = set()

    for a in raw:
        name = str(a.get("name") or "").strip()
        norm = ba.norm(name)
        key = ba.artist_key(name)
        reason = ""

        if norm in HIGH_CONF_EXACT:
            reason = "internal_exact"
        else:
            for pattern, why in HIGH_CONF_PATTERNS:
                if pattern.search(name):
                    reason = why
                    break

        if reason:
            token = (key, reason)
            if token not in seen:
                high.append(summarize(a, reason, "high"))
                seen.add(token)
            continue

        for pattern, why in REVIEW_PATTERNS:
            if not pattern.search(name):
                continue
            # Number prefixes already collapse safely when the clean name exists.
            if why == "numbered_prefix":
                stripped = re.sub(r"^\d{1,2}[._ -]+", "", name).strip()
                if ba.artist_key(stripped) in exact_names:
                    why = "numbered_prefix_duplicate"
                else:
                    continue
            token = (key, why)
            if token not in seen:
                review.append(summarize(a, why, "review"))
                seen.add(token)
            break

    high.sort(key=lambda x: (-x["plays"], x["name"].casefold()))
    review.sort(key=lambda x: (-x["plays"], x["name"].casefold()))

    report = {
        "high_confidence": high,
        "review": review,
        "counts": {
            "raw_artists": len(raw),
            "high_confidence": len(high),
            "review": len(review),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Revisión de identidad · Louder Artistas",
        "",
        f"- Universo bruto: {len(raw)}",
        f"- Candidatos de alta confianza: {len(high)}",
        f"- Candidatos para revisión: {len(review)}",
        "",
        "## Alta confianza",
        "",
    ]
    for item in high:
        track_text = "; ".join(
            f"{t['title']} ({t['plays']})" for t in item["tracks"][:4]
        ) or "sin canciones"
        lines.append(
            f"- {item['name']} — {item['reason']} — {item['plays']} plays — {track_text}"
        )
    lines += ["", "## Revisar, no excluir automáticamente", ""]
    for item in review[:200]:
        lines.append(f"- {item['name']} — {item['reason']} — {item['plays']} plays")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report["counts"], ensure_ascii=False))
    for item in high[:50]:
        print("HIGH", item["name"], item["reason"], item["plays"], item["tracks"][:3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
