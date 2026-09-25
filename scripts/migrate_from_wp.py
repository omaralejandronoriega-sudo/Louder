#!/usr/bin/env python3
"""
One-time/periodic migration of Louder Artistas from the current public frontend
to a normalized JSON snapshot stored in GitHub.

The crawler is deliberately conservative:
- one request at a time
- configurable delay between requests
- resumes from the existing JSON snapshot
- checkpoints every 25 profiles
- keeps previous data when a profile fetch fails

It reads only public pages; no WordPress credentials are required.
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
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data" / "artists.json"
DEFAULT_BASE = "https://loudermx.com"
UA = "LouderMX-Artistas-Migration/1.0 (+https://loudermx.com)"


def clean(text: str | None) -> str:
    return " ".join((text or "").split()).strip()


def parse_int(text: str | None) -> int:
    raw = re.sub(r"[^0-9]", "", text or "")
    return int(raw) if raw else 0


def slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1]


def load_store() -> dict[str, Any]:
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("artists"), list):
                return data
        except Exception:
            pass
    return {"version": 1, "generated_at": None, "source": "", "artists": []}


def save_store(store: dict[str, Any]) -> None:
    store["generated_at"] = datetime.now(timezone.utc).isoformat()
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(store, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


class Client:
    def __init__(self, delay: float) -> None:
        self.delay = max(delay, 0.0)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": UA,
                "Accept-Language": "es-MX,es;q=0.9,en;q=0.7",
                "Cache-Control": "no-cache",
            }
        )
        self.last_request = 0.0

    def get(self, url: str, timeout: int = 35) -> requests.Response:
        elapsed = time.monotonic() - self.last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        response = self.session.get(url, timeout=timeout)
        self.last_request = time.monotonic()
        response.raise_for_status()
        return response


def parse_archive(html: str, base: str) -> tuple[list[dict[str, Any]], int]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []

    for card in soup.select("a.lmx-card"):
        href = urljoin(base, card.get("href", ""))
        name_el = card.select_one("h2")
        name = clean(name_el.get_text(" ", strip=True) if name_el else "")
        if not href or not name:
            continue

        meta = clean((card.select_one(".lmx-meta") or card).get_text(" ", strip=True))
        image_el = card.select_one("img")
        image = urljoin(base, image_el.get("src", "")) if image_el else ""
        rows.append(
            {
                "slug": slug_from_url(href),
                "name": name,
                "source_url": href,
                "image": image,
                "plays": parse_int(meta.split("reproducciones", 1)[0]),
            }
        )

    total = 0
    meta_candidates = [clean(x.get_text(" ", strip=True)) for x in soup.select(".lmx-meta")]
    for txt in meta_candidates:
        match = re.search(r"([0-9][0-9.,]*)\s+artistas\s+publicados", txt, re.I)
        if match:
            total = parse_int(match.group(1))
            break

    return rows, total


def discover_catalog(client: Client, base: str, max_pages: int = 250) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    expected = 0

    for page in range(1, max_pages + 1):
        url = urljoin(base, "/artistas/")
        if page > 1:
            url += f"?pagina={page}"
        response = client.get(url)
        rows, total = parse_archive(response.text, base)
        expected = expected or total

        if not rows:
            break

        before = len(found)
        for row in rows:
            found[row["slug"]] = row

        print(f"archive page={page} found={len(found)} expected={expected or '?'}")

        if expected and len(found) >= expected:
            break
        if len(found) == before:
            break

    return list(found.values())


def metric_values(soup: BeautifulSoup) -> list[str]:
    return [
        clean(node.get_text(" ", strip=True))
        for node in soup.select(".lmx-artist-metric strong")
    ]


def parse_profile(html: str, source_url: str, seed: dict[str, Any]) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    name_el = soup.select_one(".lmx-artist-name")
    name = clean(name_el.get_text(" ", strip=True) if name_el else seed.get("name", ""))

    image_el = soup.select_one(".lmx-artist-art img")
    image = image_el.get("src", "") if image_el else seed.get("image", "")

    genres = [
        clean(x.get_text(" ", strip=True))
        for x in soup.select(".lmx-artist-genre")
        if clean(x.get_text(" ", strip=True))
    ]

    metrics = metric_values(soup)
    plays = parse_int(metrics[0]) if metrics else int(seed.get("plays") or 0)
    first_played = metrics[1] if len(metrics) > 1 else ""
    last_played = metrics[2] if len(metrics) > 2 else ""

    bio_el = soup.select_one(".lmx-bio")
    bio = "\n\n".join(
        clean(x.get_text(" ", strip=True))
        for x in (bio_el.select("p") if bio_el else [])
        if clean(x.get_text(" ", strip=True))
    )
    if not bio and bio_el:
        bio = clean(bio_el.get_text(" ", strip=True))

    social: list[dict[str, str]] = []
    official_url = ""
    for anchor in soup.select(".lmx-artist-social a"):
        label = clean(anchor.get_text(" ", strip=True))
        href = anchor.get("href", "").strip()
        if not href:
            continue
        if label.casefold() == "web oficial":
            official_url = href
        else:
            social.append({"name": label, "url": href})

    tracks: list[dict[str, Any]] = []
    for row in soup.select("[data-lmx-track]"):
        title_el = row.select_one(".lmx-track-title")
        album_el = row.select_one(".lmx-track-album")
        cover_el = row.select_one(".lmx-track-cover img")
        date_nodes = row.select(".lmx-date-chip strong")
        plays_el = row.select_one(".lmx-track-plays strong")
        title = clean(title_el.get_text(" ", strip=True) if title_el else row.get("data-title", ""))
        if not title:
            continue
        tracks.append(
            {
                "title": title,
                "album": clean(album_el.get_text(" ", strip=True) if album_el else ""),
                "artwork": cover_el.get("src", "") if cover_el else "",
                "plays": parse_int(plays_el.get_text(" ", strip=True) if plays_el else row.get("data-plays", "")),
                "first_played": clean(date_nodes[0].get_text(" ", strip=True)) if len(date_nodes) > 0 else "",
                "last_played": clean(date_nodes[1].get_text(" ", strip=True)) if len(date_nodes) > 1 else "",
            }
        )

    related: list[dict[str, str]] = []
    for card in soup.select("a.lmx-related-card"):
        href = card.get("href", "")
        rel_name_el = card.select_one(".lmx-related-name")
        rel_name = clean(rel_name_el.get_text(" ", strip=True) if rel_name_el else "")
        if href and rel_name:
            related.append(
                {
                    "slug": slug_from_url(href),
                    "name": rel_name,
                }
            )

    return {
        "slug": seed["slug"],
        "name": name or seed["name"],
        "source_url": source_url,
        "image": image,
        "genres": genres,
        "plays": plays,
        "first_played": first_played,
        "last_played": last_played,
        "bio": bio,
        "official_url": official_url,
        "social": social,
        "tracks": tracks,
        "related": related,
        "migrated_at": datetime.now(timezone.utc).isoformat(),
    }


def normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFD", value)
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--max-artists", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    client = Client(args.delay)
    store = load_store()
    store["source"] = urljoin(base + "/", "artistas/")

    catalog = discover_catalog(client, base)
    if args.max_artists > 0:
        catalog = catalog[: args.max_artists]

    previous = {
        a.get("slug"): a
        for a in store.get("artists", [])
        if isinstance(a, dict) and a.get("slug")
    }

    output: list[dict[str, Any]] = []
    failures: list[str] = []

    for index, seed in enumerate(catalog, start=1):
        slug = seed["slug"]
        if slug in previous and previous[slug].get("bio") and not args.refresh:
            output.append(previous[slug])
            print(f"profile {index}/{len(catalog)} {slug}: resume")
            continue

        try:
            response = client.get(seed["source_url"])
            artist = parse_profile(response.text, seed["source_url"], seed)
            output.append(artist)
            print(
                f"profile {index}/{len(catalog)} {slug}: "
                f"tracks={len(artist['tracks'])} bio={'yes' if artist['bio'] else 'no'}"
            )
        except Exception as exc:
            failures.append(slug)
            fallback = previous.get(slug) or seed
            output.append(fallback)
            print(f"profile {index}/{len(catalog)} {slug}: ERROR {exc}")

        if index % 25 == 0:
            store["artists"] = sorted(output, key=lambda a: normalized_name(a.get("name", "")))
            store["failures"] = failures
            save_store(store)

    # Preserve any previously known artist that disappeared from discovery instead
    # of silently deleting it. This protects drafts/edge cases during migration.
    current_slugs = {a.get("slug") for a in output}
    for slug, artist in previous.items():
        if slug not in current_slugs:
            artist = dict(artist)
            artist["catalog_status"] = "not_seen_in_latest_archive"
            output.append(artist)

    store["artists"] = sorted(output, key=lambda a: normalized_name(a.get("name", "")))
    store["failures"] = failures
    store["catalog_count"] = len(catalog)
    store["artist_count"] = len(store["artists"])
    save_store(store)

    print(
        f"done catalog={len(catalog)} stored={len(store['artists'])} "
        f"failures={len(failures)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
