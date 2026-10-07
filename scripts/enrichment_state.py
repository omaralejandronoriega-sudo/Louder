#!/usr/bin/env python3
"""Shared state/retry and remote-image validation helpers for Louder Artistas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

STATUSES = {"complete", "partial", "retry", "not_found"}
RETRY_DELAYS = {
    "retry": timedelta(hours=6),
    "partial": timedelta(days=3),
    "not_found": timedelta(days=14),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).isoformat() if dt else ""


def parse_iso(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


def next_retry_at(status: str, now: datetime | None = None) -> str:
    now = now or utcnow()
    delay = RETRY_DELAYS.get(status)
    return iso(now + delay) if delay else ""


def is_due(record: dict[str, Any] | None, *, refresh: bool = False, now: datetime | None = None) -> bool:
    """Only complete is terminal. Legacy records without profile_status are revisited."""
    if refresh or not isinstance(record, dict) or not record:
        return True
    status = str(record.get("profile_status") or record.get("status") or "").strip()
    if status == "complete":
        return False
    if status not in STATUSES:
        return True
    due = parse_iso(record.get("next_retry_at"))
    if due is None:
        checked = parse_iso(record.get("profile_checked_at") or record.get("checked_at"))
        delay = RETRY_DELAYS.get(status)
        if checked is None or delay is None:
            return True
        due = checked + delay
    return due <= (now or utcnow())


def _looks_like_image(data: bytes) -> bool:
    if not data:
        return False
    if data.startswith(b"\xff\xd8\xff"):
        return True
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if data.startswith((b"GIF87a", b"GIF89a")):
        return True
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return True
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis", b"heic", b"heix"}:
        return True
    return False


def validate_remote_image(
    session: requests.Session,
    url: Any,
    *,
    timeout: int = 15,
    min_bytes: int = 256,
) -> tuple[bool, str, str]:
    """Validate HTTPS remote imagery by reading real image bytes, never headers alone."""
    raw = str(url or "").strip()
    if not raw:
        return False, "", "empty"
    parsed = urlparse(raw)
    if parsed.scheme != "https" or not parsed.netloc:
        return False, raw, "not_https"

    headers = {
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "Range": "bytes=0-4095",
    }
    try:
        r = session.get(
            raw,
            headers=headers,
            allow_redirects=True,
            timeout=timeout,
            stream=True,
        )
        final_url = str(r.url or raw)
        if not (200 <= r.status_code < 400):
            return False, final_url, f"http_{r.status_code}"
        ctype = str(r.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        chunk = next(r.iter_content(chunk_size=4096), b"")
        if len(chunk) < min_bytes:
            return False, final_url, "too_small"
        if not _looks_like_image(chunk):
            return False, final_url, f"invalid_bytes:{ctype or 'unknown'}"
        return True, final_url, "bytes"
    except Exception as exc:
        return False, raw, f"error:{type(exc).__name__}"


def usable_gallery_images(gallery: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(gallery, dict):
        return []
    rows = []
    for item in gallery.get("images") or []:
        if not isinstance(item, dict) or not has_text(item.get("url")):
            continue
        # New records require explicit validation. Human-reviewed overrides are trusted.
        if item.get("valid") is True or item.get("source") == "Louder reviewed override":
            rows.append(item)
    return rows[:5]


def has_profile_data(artist: dict[str, Any], gallery: dict[str, Any] | None) -> bool:
    """Count usable identity/profile metadata from either canonical artist data or enrichment."""
    gallery = gallery if isinstance(gallery, dict) else {}
    gallery_social = gallery.get("social") or {}
    artist_social = artist.get("social") or []
    artist_social_ok = any(
        isinstance(item, dict) and has_text(item.get("url"))
        for item in artist_social
    )
    artist_genres = artist.get("genres") or []
    return any(
        [
            has_text(artist.get("official_url")),
            artist_social_ok,
            any(has_text(x) for x in artist_genres),
            has_text(gallery.get("musicbrainz_id")),
            has_text(gallery.get("genre")),
            has_text(gallery.get("style")),
            has_text(gallery.get("country")),
            has_text(gallery.get("official_url")),
            has_text(gallery.get("wikipedia_url")),
            has_text(gallery.get("lastfm_url")),
            bool(gallery.get("verified")),
            any(has_text(gallery_social.get(k)) for k in ("facebook", "twitter", "instagram")),
        ]
    )


def profile_missing_fields(artist: dict[str, Any], gallery: dict[str, Any] | None) -> list[str]:
    gallery = gallery if isinstance(gallery, dict) else {}
    missing: list[str] = []
    if not usable_gallery_images(gallery):
        missing.append("image")
    if not has_text(artist.get("bio") or gallery.get("bio_es") or gallery.get("bio_en")):
        missing.append("bio")
    return missing


def profile_status(
    artist: dict[str, Any],
    gallery: dict[str, Any] | None,
    *,
    transient_error: bool = False,
) -> tuple[str, list[str]]:
    missing = profile_missing_fields(artist, gallery)
    if not missing:
        return "complete", []
    if transient_error:
        return "retry", missing

    gallery = gallery if isinstance(gallery, dict) else {}
    found_any = bool(
        usable_gallery_images(gallery)
        or has_text(artist.get("bio") or gallery.get("bio_es") or gallery.get("bio_en"))
        or has_profile_data(artist, gallery)
    )
    return ("partial" if found_any else "not_found"), missing
