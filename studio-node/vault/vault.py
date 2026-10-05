#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from aiohttp import web
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.environ["TELEGRAM_SESSION"]
CHAT_ID = int(os.environ["TELEGRAM_VAULT_CHAT_ID"])
TOKEN = os.environ["TELEGRAM_VAULT_TOKEN"]

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_range(value: str | None, size: int) -> ByteRange | None:
    if not value:
        return None
    if not value.startswith("bytes="):
        raise ValueError("unsupported range unit")

    spec = value[6:].strip()
    if "," in spec or "-" not in spec:
        raise ValueError("single range required")

    left, right = spec.split("-", 1)
    if not left:
        suffix = int(right)
        if suffix <= 0:
            raise ValueError("invalid suffix")
        return ByteRange(max(0, size - suffix), size - 1)

    start = int(left)
    if start < 0 or start >= size:
        raise IndexError("range outside file")

    end = size - 1 if not right else min(int(right), size - 1)
    if end < start:
        raise ValueError("bad range")
    return ByteRange(start, end)


def auth(request: web.Request) -> None:
    supplied = request.query.get("token", "")
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        supplied = header[7:]
    if supplied != TOKEN:
        raise web.HTTPUnauthorized()


def file_size(message) -> int:
    value = getattr(getattr(message, "file", None), "size", None)
    if not value:
        value = getattr(getattr(message, "document", None), "size", None)
    if not value:
        raise web.HTTPInternalServerError(text="unknown media size")
    return int(value)


def mime_type(message) -> str:
    value = getattr(getattr(message, "file", None), "mime_type", None)
    if not value:
        value = getattr(getattr(message, "document", None), "mime_type", None)
    return value or "application/octet-stream"


def infer_artist_title(filename: str) -> tuple[str, str]:
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename).strip()
    if " - " in base:
        artist, title = base.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", base


async def on_startup(app: web.Application) -> None:
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("TELEGRAM_SESSION is not authorized")


async def on_cleanup(app: web.Application) -> None:
    await client.disconnect()


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": client.is_connected(), "backend": "telegram-mtproto"})


async def index(request: web.Request) -> web.Response:
    auth(request)
    limit = max(1, min(5000, int(request.query.get("limit", "1000"))))
    items = []

    async for message in client.iter_messages(CHAT_ID, limit=limit):
        if not message.media or not getattr(message, "file", None):
            continue

        name = message.file.name or f"telegram-{message.id}"
        mime = message.file.mime_type or ""
        if not (
            mime.startswith("audio/")
            or name.lower().endswith((".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"))
        ):
            continue

        artist = getattr(message.file, "performer", None) or ""
        title = getattr(message.file, "title", None) or ""
        if not title:
            guessed_artist, guessed_title = infer_artist_title(name)
            artist = artist or guessed_artist
            title = guessed_title

        items.append(
            {
                "message_id": message.id,
                "date": message.date.isoformat() if message.date else None,
                "filename": name,
                "mime": mime,
                "size": file_size(message),
                "artist": artist,
                "title": title,
            }
        )

    return web.json_response({"ok": True, "count": len(items), "items": items})


async def media(request: web.Request) -> web.StreamResponse:
    auth(request)
    try:
        message_id = int(request.match_info["message_id"])
    except ValueError as exc:
        raise web.HTTPBadRequest(text="invalid message id") from exc

    message = await client.get_messages(CHAT_ID, ids=message_id)
    if message is None or not message.media:
        raise web.HTTPNotFound(text="media not found")

    size = file_size(message)
    mime = mime_type(message)

    try:
        wanted = parse_range(request.headers.get("Range"), size)
    except IndexError as exc:
        raise web.HTTPRequestRangeNotSatisfiable(
            headers={"Content-Range": f"bytes */{size}"}
        ) from exc
    except (ValueError, TypeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc

    start = wanted.start if wanted else 0
    end = wanted.end if wanted else size - 1
    status = 206 if wanted else 200

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": mime,
        "Content-Length": str(end - start + 1),
        "Cache-Control": "private, no-store",
    }
    if wanted:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"

    response = web.StreamResponse(status=status, headers=headers)
    await response.prepare(request)

    remaining = end - start + 1
    async for chunk in client.iter_download(
        message.media,
        offset=start,
        request_size=512 * 1024,
    ):
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        await response.write(chunk)
        remaining -= len(chunk)

    await response.write_eof()
    return response


app = web.Application()
app.router.add_get("/health", health)
app.router.add_get("/index", index)
app.router.add_get("/media/{message_id:\\d+}", media)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8765)
