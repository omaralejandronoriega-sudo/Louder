#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse, unquote

import requests
import build_artists as ba
import enrichment_state as es

ROOT = Path(__file__).resolve().parents[1]
ARTISTS = ROOT / "data" / "artists.json"
GALLERIES = ROOT / "data" / "galleries.json"
OUT = ROOT / "data" / "identity_enrichment.json"

MB_SEARCH = "https://musicbrainz.org/ws/2/artist/"
MB_LOOKUP = "https://musicbrainz.org/ws/2/artist/{mbid}"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SEARCH = "https://en.wikipedia.org/w/rest.php/v1/search/page"
DEEZER_SEARCH = "https://api.deezer.com/search/artist"
UA = "LouderMX-Identity-Enrichment/2.0 (+https://loudermx.com)"


def norm(value: str) -> str:
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def load(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else fallback
    except Exception:
        return fallback


class Client:
    def __init__(self, min_interval: float = 1.1) -> None:
        self.last = 0.0
        self.min_interval = min_interval
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: int = 35) -> dict[str, Any] | None:
        elapsed = time.monotonic() - self.last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        r = self.session.get(url, params=params, timeout=timeout)
        self.last = time.monotonic()
        if r.status_code in (404, 429, 503):
            return None
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else None


def exact_mb_match(client: Client, name: str) -> dict[str, Any] | None:
    data = client.get(MB_SEARCH, params={"query": f'artist:"{name}"', "fmt": "json", "limit": 8}) or {}
    rows = data.get("artists") or []
    wanted = norm(name)
    matches = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        names = [str(row.get("name") or ""), str(row.get("sort-name") or "")]
        names += [str(a.get("name") or "") for a in (row.get("aliases") or []) if isinstance(a, dict)]
        exact = any(norm(x) == wanted for x in names if x)
        if not exact:
            continue
        score = int(row.get("score") or 0)
        if score < 90:
            continue
        matches.append((score, row))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0], reverse=True)
    return matches[0][1]


def relation_urls(detail: dict[str, Any]) -> tuple[str, dict[str, str], str]:
    official = ""
    social = {"facebook": "", "twitter": "", "instagram": ""}
    wikipedia = ""
    for rel in detail.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        url = str((rel.get("url") or {}).get("resource") or "").strip()
        if not url:
            continue
        rtype = str(rel.get("type") or "").casefold()
        host = urlparse(url).netloc.casefold()
        if "wikipedia.org" in host and not wikipedia:
            wikipedia = url
        if ("official homepage" in rtype or rtype == "official homepage") and not official:
            official = url
        if "facebook.com" in host and not social["facebook"]:
            social["facebook"] = url
        elif ("twitter.com" in host or "x.com" in host) and not social["twitter"]:
            social["twitter"] = url
        elif "instagram.com" in host and not social["instagram"]:
            social["instagram"] = url
    return official, social, wikipedia


def wiki_title_from_url(url: str) -> str:
    try:
        path = urlparse(url).path
        if "/wiki/" not in path:
            return ""
        return unquote(path.split("/wiki/", 1)[1]).replace("_", " ")
    except Exception:
        return ""


def musical_summary_ok(data: dict[str, Any]) -> bool:
    desc = str(data.get("description") or "").casefold()
    if not desc:
        return True
    negative = ("album", "song", "film", "television", "episode", "novel", "video game", "radio programme", "radio program")
    positive = ("band", "musician", "singer", "musical group", "duo", "trio", "artist", "producer", "composer", "dj")
    if any(x in desc for x in negative) and not any(x in desc for x in positive):
        return False
    return True


def wikipedia_data(client: Client, canonical: str, url: str) -> dict[str, str]:
    title = wiki_title_from_url(url)
    if not title:
        search = client.get(WIKI_SEARCH, params={"q": canonical, "limit": 6}) or {}
        wanted = norm(canonical)
        for page in search.get("pages") or []:
            if not isinstance(page, dict):
                continue
            candidate = str(page.get("title") or "").strip()
            desc = str(page.get("description") or "").casefold()
            clean = norm(re.sub(r"\s*\([^)]*\)\s*$", "", candidate))
            if clean != wanted:
                continue
            if any(x in desc for x in ("band", "musician", "singer", "musical group", "duo", "trio", "producer", "composer", "dj")):
                title = candidate
                break
    if not title:
        return {}
    data = client.get(WIKI_SUMMARY.format(title=quote(title, safe=""))) or {}
    if str(data.get("type") or "").casefold() == "disambiguation" or not musical_summary_ok(data):
        return {}
    image = str((data.get("originalimage") or {}).get("source") or (data.get("thumbnail") or {}).get("source") or "").strip()
    page = str((((data.get("content_urls") or {}).get("desktop") or {}).get("page")) or url or "").strip()
    return {
        "bio_en": str(data.get("extract") or "").strip(),
        "image": image if image.startswith("https://") else "",
        "wikipedia_url": page,
    }


def deezer_image(client: Client, name: str) -> str:
    data = client.get(DEEZER_SEARCH, params={"q": name, "limit": 8}) or {}
    wanted = norm(name)
    for row in data.get("data") or []:
        if not isinstance(row, dict) or norm(row.get("name", "")) != wanted:
            continue
        for key in ("picture_xl", "picture_big", "picture_medium", "picture"):
            url = str(row.get(key) or "").strip()
            if url.startswith("https://"):
                return url
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=180)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    artists = load(ARTISTS, {"artists": []}).get("artists") or []
    galleries = (load(GALLERIES, {"artists": {}}).get("artists") or {})
    store = load(OUT, {"version": 2, "updated_at": None, "artists": {}})
    store["version"] = max(int(store.get("version") or 1), 2)
    out = store.setdefault("artists", {})
    now = es.utcnow()

    pending = []
    for artist in artists:
        if not isinstance(artist, dict):
            continue
        slug = str(artist.get("slug") or "").strip()
        name = str(artist.get("name") or "").strip()
        if not slug or not name or not ba.is_public_artist_candidate(name):
            continue
        gallery = galleries.get(slug) or {}
        if not es.profile_missing_fields(artist, gallery):
            continue
        existing = out.get(slug) or {}
        if not es.is_due(existing, refresh=args.refresh, now=now):
            continue
        pending.append(artist)

    def priority(a: dict[str, Any]) -> tuple[Any, ...]:
        sources = set(a.get("sources") or [])
        date_key = ba.history_date_key(a.get("last_played"))
        if date_key[0] >= 9998:
            recent_score = 0
        else:
            y, m, d, hh, mm, ss = date_key
            recent_score = y * 10**10 + m * 10**8 + d * 10**6 + hh * 10**4 + mm * 10**2 + ss
        return (
            0 if "yesstreaming_live" in sources else 1,
            -recent_score,
            0 if "yesstreaming" in sources else 1,
            -int(a.get("plays") or 0),
            norm(a.get("name", "")),
        )

    pending.sort(key=priority)
    if args.limit > 0:
        pending = pending[:args.limit]

    mb = Client(1.1)
    wiki = Client(0.35)
    deezer = Client(0.20)
    print(f"identity_due={len(pending)}")

    for i, artist in enumerate(pending, start=1):
        slug = str(artist["slug"])
        name = str(artist["name"])
        attempt = es.utcnow()
        existing = out.get(slug) or {}
        row: dict[str, Any] = dict(existing)
        row.update({
            "name": name,
            "verified": False,
            "profile_checked_at": es.iso(attempt),
            "checked_at": es.iso(attempt),
        })
        try:
            match = exact_mb_match(mb, name)
            mbid = ""
            canonical = name
            official = ""
            social = {"facebook": "", "twitter": "", "instagram": ""}
            wikipedia = ""
            genre = ""
            verification_source = ""

            if match:
                mbid = str(match.get("id") or "")
                canonical = str(match.get("name") or name)
                detail = mb.get(
                    MB_LOOKUP.format(mbid=mbid),
                    params={"inc": "url-rels+aliases+genres", "fmt": "json"},
                ) or {}
                official, social, wikipedia = relation_urls(detail)
                genres = detail.get("genres") or []
                if isinstance(genres, list) and genres:
                    genres = sorted(
                        [g for g in genres if isinstance(g, dict)],
                        key=lambda g: int(g.get("count") or 0),
                        reverse=True,
                    )
                    if genres:
                        genre = str(genres[0].get("name") or "")
                verification_source = "MusicBrainz"

            # Wikipedia search is also allowed without a MusicBrainz match so
            # obscure/legacy artists are not permanently blocked on one source.
            w = wikipedia_data(wiki, canonical, wikipedia)
            fallback_image = w.get("image", "") or deezer_image(deezer, canonical)
            image_source = (
                "Wikipedia" if w.get("image") else
                ("Deezer exact artist match" if fallback_image else "")
            )
            if fallback_image:
                ok, final_url, _method = es.validate_remote_image(deezer.session, fallback_image)
                fallback_image = final_url if ok else ""

            row.update({
                "verified": bool(match or w),
                "musicbrainz_id": mbid or existing.get("musicbrainz_id", ""),
                "canonical_name": canonical,
                "match_score": int(match.get("score") or 0) if match else int(existing.get("match_score") or 0),
                "verification_source": verification_source or ("Wikipedia" if w else existing.get("verification_source", "")),
                "official_url": official or existing.get("official_url", ""),
                "social": social if any(social.values()) else existing.get("social", {}),
                "genre": genre or existing.get("genre", ""),
                "bio_en": w.get("bio_en", "") or existing.get("bio_en", ""),
                "image": fallback_image or existing.get("image", ""),
                "image_source": image_source or existing.get("image_source", ""),
                "wikipedia_url": w.get("wikipedia_url", wikipedia) or existing.get("wikipedia_url", ""),
            })
            if match and norm(canonical) != norm(name):
                row["alias_suggestion"] = canonical

            gallery = dict(galleries.get(slug) or {})
            if row.get("image"):
                gallery["images"] = [{
                    "url": row["image"],
                    "preview": row["image"],
                    "source": row.get("image_source") or "Identity fallback",
                    "kind": "portrait",
                    "valid": True,
                    "validated_at": es.iso(attempt),
                }]
            if row.get("bio_en") and not gallery.get("bio_en"):
                gallery["bio_en"] = row["bio_en"]
            for key in ("musicbrainz_id", "official_url", "genre", "wikipedia_url", "verified"):
                if row.get(key) and not gallery.get(key):
                    gallery[key] = row[key]
            if row.get("social") and not gallery.get("social"):
                gallery["social"] = row["social"]

            status, missing = es.profile_status(artist, gallery)
            if not match and not w and not fallback_image and not row.get("bio_en"):
                status = "not_found"
            row["profile_status"] = status
            row["status"] = status
            row["missing_fields"] = missing
            row["next_retry_at"] = es.next_retry_at(status, attempt)
            row["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
            row.pop("error", None)
            out[slug] = row
            print(
                f"{i}/{len(pending)} {name} -> {status} "
                f"image={'yes' if row.get('image') else 'no'} "
                f"bio={'yes' if row.get('bio_en') else 'no'} "
                f"missing={','.join(missing) or 'none'}"
            )
        except Exception as exc:
            row["profile_status"] = "retry"
            row["status"] = "retry"
            row["next_retry_at"] = es.next_retry_at("retry", attempt)
            row["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
            row["error"] = str(exc)[:300]
            out[slug] = row
            print(f"{i}/{len(pending)} {name} -> retry ERROR {exc}")

        if i % 25 == 0:
            store["updated_at"] = es.iso(es.utcnow())
            OUT.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    store["updated_at"] = es.iso(es.utcnow())
    OUT.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts = {"complete": 0, "partial": 0, "retry": 0, "not_found": 0, "legacy": 0}
    for value in out.values():
        if not isinstance(value, dict):
            continue
        status = str(value.get("profile_status") or "legacy")
        counts[status if status in counts else "legacy"] += 1
    print(
        "identity_result "
        f"complete={counts['complete']} partial={counts['partial']} "
        f"retry={counts['retry']} not_found={counts['not_found']} legacy={counts['legacy']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
