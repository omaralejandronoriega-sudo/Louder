#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import random
import re
import secrets
import time
from typing import Any

from aiohttp import web, WSMsgType, ClientSession


ROOT = pathlib.Path(os.getenv("LOUDER_DATA_DIR", "/data"))
ROOT.mkdir(parents=True, exist_ok=True)

STATE_FILE = ROOT / "studio-state.json"
AUTO_POOL_FILE = ROOT / "auto-pool.json"
VOICE_DIR = ROOT / "voice-tracks"
VOICE_DIR.mkdir(exist_ok=True)
FX_DIR = ROOT / "sound-fx"
FX_DIR.mkdir(exist_ok=True)

API_TOKEN = os.getenv("LOUDER_API_TOKEN", "").strip()
INTERNAL_KEY = os.getenv("LOUDER_INTERNAL_KEY", "").strip() or secrets.token_urlsafe(24)
LIQ_HOST = os.getenv("LIQUIDSOAP_HOST", "liquidsoap")
LIQ_PORT = int(os.getenv("LIQUIDSOAP_PORT", "1234"))
VOICE_HARBOR_HOST = os.getenv("VOICE_HARBOR_HOST", "liquidsoap")
VOICE_HARBOR_PORT = int(os.getenv("VOICE_HARBOR_PORT", "8005"))
VOICE_HARBOR_PASSWORD = os.getenv("VOICE_HARBOR_PASSWORD", "change-me")
CORS = os.getenv("LOUDER_CORS_ORIGIN", "*")
EMERGENCY_URI = os.getenv("EMERGENCY_URI", "").strip()
VAULT_BASE_URL = os.getenv("TELEGRAM_VAULT_BASE_URL", "http://vault:8765").rstrip("/")
VAULT_TOKEN = os.getenv("TELEGRAM_VAULT_TOKEN", "").strip()
YESSTREAMING_STATUS_URL = os.getenv("YESSTREAMING_STATUS_URL", "").strip()

DEFAULT_STATE: dict[str, Any] = {
    "mode": "auto",
    "queue": [],
    "history": [],
    "now": None,
    "artist_separation_minutes": 90,
    "track_separation_hours": 120,
    "crossfade": {"duration": 4.5, "fade_in": 1.2, "fade_out": 2.8},
    "voice": {"duck_db": -8.0, "fade_ms": 350, "active": False},
    "dsp": {
        "agc": True,
        "target": -14.0,
        "stereo_width": 0.0,
        "bass_gain": 0.0,
        "compressor": True,
        "threshold": -10.0,
        "ratio": 2.0,
        "limiter": True,
    },
    "encoders": [
        {
            "id": "out",
            "name": "YesStreaming Primary",
            "format": "MP3",
            "bitrate": 320,
            "status": "unknown",
        }
    ],
    "clockwheel": [],
    "clock_index": 0,
    "selection_cursors": {},
    "schedule": [],
    "pal_scripts": {},
    "requests": [],
}
_lock = asyncio.Lock()


def load_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


state = load_json(STATE_FILE, dict(DEFAULT_STATE))
for key, value in DEFAULT_STATE.items():
    state.setdefault(key, value)


async def save_state() -> None:
    async with _lock:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(STATE_FILE)


@web.middleware
async def cors_auth(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        if request.path.startswith("/internal/"):
            key = request.query.get("key", "")
            if INTERNAL_KEY and key != INTERNAL_KEY:
                raise web.HTTPUnauthorized()
        elif request.path not in ("/health", "/"):
            token = request.headers.get("Authorization", "")
            if token.startswith("Bearer "):
                token = token[7:]
            if not token:
                token = request.query.get("token", "")
            if API_TOKEN and token != API_TOKEN:
                raise web.HTTPUnauthorized()
        response = await handler(request)

    response.headers["Access-Control-Allow-Origin"] = CORS
    response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
    return response


async def liq(command: str, timeout: float = 3.0) -> str:
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(LIQ_HOST, LIQ_PORT), timeout
    )
    try:
        writer.write((command.strip() + "\n").encode())
        await writer.drain()
        chunks: list[str] = []
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout)
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\r\n")
            if text == "END":
                break
            chunks.append(text)
        return "\n".join(chunks)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def liq_float(command: str) -> float | None:
    try:
        raw = await liq(command)
        first = raw.splitlines()[0].strip() if raw else ""
        return float(first)
    except Exception:
        return None


def linear_to_db(value: float | None) -> float | None:
    if value is None:
        return None
    if value <= 0:
        return -60.0
    import math
    return max(-60.0, min(6.0, 20.0 * math.log10(value)))


def liq_annotation_value(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("\\", "\\\\").replace('"', '\\"')


def recent_conflict(item: dict[str, Any]) -> bool:
    now = time.time()
    artist = str(item.get("artist", "")).casefold().strip()
    title = str(item.get("title", "")).casefold().strip()

    for row in reversed(state.get("history", [])[-1000:]):
        ts = float(row.get("ts", 0) or 0)
        same_artist = artist and str(row.get("artist", "")).casefold().strip() == artist
        same_track = (
            same_artist
            and title
            and str(row.get("title", "")).casefold().strip() == title
        )
        if same_artist and now - ts < state.get("artist_separation_minutes", 90) * 60:
            return True
        if same_track and now - ts < state.get("track_separation_hours", 120) * 3600:
            return True
    return False


def last_played_times() -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    artists: dict[str, float] = {}
    tracks: dict[tuple[str, str], float] = {}
    for row in state.get("history", []):
        ts = float(row.get("ts", 0) or 0)
        artist = str(row.get("artist", "")).casefold().strip()
        title = str(row.get("title", "")).casefold().strip()
        if artist:
            artists[artist] = max(ts, artists.get(artist, 0.0))
        if artist and title:
            key = (artist, title)
            tracks[key] = max(ts, tracks.get(key, 0.0))
    return artists, tracks


def choose_auto(
    category: str | None = None,
    selection: str = "random",
    enforce_rules: bool = True,
) -> dict[str, Any] | None:
    pool = load_json(AUTO_POOL_FILE, [])
    wanted = (category or "").strip()

    candidates = [
        item
        for item in pool
        if item.get("uri")
        and (
            not wanted
            or str(item.get("category", "")).casefold() == wanted.casefold()
        )
    ]
    if not candidates and wanted:
        candidates = [item for item in pool if item.get("uri")]

    eligible = (
        [item for item in candidates if not recent_conflict(item)]
        if enforce_rules
        else list(candidates)
    )
    if not eligible:
        eligible = candidates
    if not eligible:
        return None

    method = str(selection or "random").lower().replace(" ", "_")
    artists, tracks = last_played_times()

    if method in {"least_recent_song", "lrp_song", "least_recently_played_song"}:
        return min(
            eligible,
            key=lambda item: tracks.get(
                (
                    str(item.get("artist", "")).casefold().strip(),
                    str(item.get("title", "")).casefold().strip(),
                ),
                0.0,
            ),
        )

    if method in {"least_recent_artist", "lrp_artist", "least_recently_played_artist"}:
        return min(
            eligible,
            key=lambda item: artists.get(
                str(item.get("artist", "")).casefold().strip(),
                0.0,
            ),
        )

    if method in {"sequential", "sequence"}:
        ordered = sorted(
            eligible,
            key=lambda item: (
                str(item.get("artist", "")).casefold(),
                str(item.get("title", "")).casefold(),
            ),
        )
        key = wanted.casefold() or "__all__"
        cursors = state.setdefault("selection_cursors", {})
        index = int(cursors.get(key, 0) or 0) % len(ordered)
        cursors[key] = index + 1
        return ordered[index]

    if method in {"weighted", "weighted_random"}:
        weights = []
        for item in eligible:
            try:
                weights.append(max(0.01, float(item.get("weight", 1.0))))
            except Exception:
                weights.append(1.0)
        return random.choices(eligible, weights=weights, k=1)[0]

    return random.choice(eligible)


def choose_clock_item() -> dict[str, Any] | None:
    wheel = state.get("clockwheel", [])
    if not isinstance(wheel, list) or not wheel:
        return None

    # Advance through comments/non-audio slots until a playable entry is found.
    for _ in range(len(wheel)):
        index = int(state.get("clock_index", 0) or 0) % len(wheel)
        state["clock_index"] = (index + 1) % len(wheel)
        entry = wheel[index] if isinstance(wheel[index], dict) else {}
        kind = str(entry.get("kind", "category")).lower()

        if kind == "comment":
            continue

        if kind == "request":
            for row in state.get("requests", []):
                if row.get("status") != "pending":
                    continue
                try:
                    item = resolve_item(row.get("track", {}))
                except ValueError:
                    continue
                if entry.get("enforce_rules", True) and recent_conflict(item):
                    continue
                row["status"] = "approved"
                row["reason"] = "selected by clockwheel"
                return item
            continue

        category = str(entry.get("category", "")).strip()
        selection = str(entry.get("selection", "random"))
        enforce = bool(entry.get("enforce_rules", True))
        item = choose_auto(category, selection, enforce)
        if item:
            return item

    return None


def catalog_pool() -> list[dict[str, Any]]:
    value = load_json(AUTO_POOL_FILE, [])
    return value if isinstance(value, list) else []


def resolve_item(item: dict[str, Any]) -> dict[str, Any]:
    """Resolve browser-safe catalog references to an internal playable item."""
    if item.get("uri"):
        return dict(item)

    message_id = item.get("message_id")
    if message_id is not None:
        for candidate in catalog_pool():
            if int(candidate.get("message_id", -1)) == int(message_id):
                resolved = dict(candidate)
                # Keep browser-side metadata edits without allowing a URI override.
                for key in ("artist", "title", "category"):
                    if item.get(key):
                        resolved[key] = item[key]
                return resolved

    raise ValueError("track is not present in the playable catalog")


def public_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """Never leak internal vault URLs/tokens back to the browser."""
    if not item:
        return item
    safe = dict(item)
    safe.pop("uri", None)
    safe["playable"] = bool(item.get("uri"))
    return safe


async def internal_next(request: web.Request) -> web.Response:
    mode = state.get("mode", "auto")
    item: dict[str, Any] | None = None

    async with _lock:
        queue = state.setdefault("queue", [])
        if queue:
            item = queue.pop(0)
        elif mode in ("auto", "recovery"):
            item = choose_clock_item() or choose_auto()

        if item:
            state["now"] = item

    await save_state()

    if not item:
        if EMERGENCY_URI and mode == "recovery":
            return web.Response(text=EMERGENCY_URI)
        return web.Response(status=204)

    uri = str(item.get("uri", "")).strip()
    if not uri:
        return web.Response(status=204)

    # Crossfade rules are attached as request metadata, so changes made in
    # Cloud Studio apply to newly resolved tracks without restarting Liquidsoap.
    xf = state.get("crossfade", {})
    duration = float(xf.get("duration", 4.5))
    fade_in = float(xf.get("fade_in", 1.2))
    fade_out = float(xf.get("fade_out", 2.8))
    artist = liq_annotation_value(item.get("artist", ""))
    title = liq_annotation_value(item.get("title", ""))
    category = liq_annotation_value(item.get("category", ""))
    message_id = liq_annotation_value(item.get("message_id", ""))
    fade_in_type = liq_annotation_value(xf.get("fade_in_type", "lin"))
    fade_out_type = liq_annotation_value(xf.get("fade_out_type", "lin"))
    curve = float(xf.get("curve", 10.0))
    annotated = (
        "annotate:"
        f'artist="{artist}",'
        f'title="{title}",'
        f'category="{category}",'
        f'message_id="{message_id}",'
        f"liq_cross_duration={duration},"
        f"liq_fade_in={fade_in},"
        f"liq_fade_out={fade_out},"
        f'liq_fade_in_type="{fade_in_type}",'
        f'liq_fade_out_type="{fade_out_type}",'
        f"liq_fade_in_curve={curve},"
        f"liq_fade_out_curve={curve}:"
        f"{uri}"
    )
    return web.Response(text=annotated, content_type="text/plain")


async def health(request: web.Request) -> web.Response:
    liquidsoap_ok = False
    version = ""
    try:
        version = await liq("version")
        liquidsoap_ok = True
    except Exception:
        pass

    return web.json_response(
        {
            "ok": True,
            "liquidsoap": liquidsoap_ok,
            "liquidsoap_version": version,
            "internal_key_configured": bool(INTERNAL_KEY),
        }
    )


async def status(request: web.Request) -> web.Response:
    liquidsoap_ok = False
    metadata = ""
    output_status = "unknown"

    try:
        metadata = await liq("auto.metadata")
        output_status = await liq("out.status")
        liquidsoap_ok = True
    except Exception:
        pass

    auto_elapsed, auto_remaining, a_elapsed, a_remaining, b_elapsed, b_remaining, a_rms, b_rms, program_rms = await asyncio.gather(
        liq_float("auto.elapsed"),
        liq_float("auto.remaining"),
        liq_float("deck_a.elapsed"),
        liq_float("deck_a.remaining"),
        liq_float("deck_b.elapsed"),
        liq_float("deck_b.remaining"),
        liq_float("deck_a_meter.rms"),
        liq_float("deck_b_meter.rms"),
        liq_float("program_meter.rms"),
    )

    encoders = list(state.get("encoders", []))
    if encoders:
        encoders[0] = dict(encoders[0])
        encoders[0]["status"] = output_status or "unknown"

    return web.json_response(
        {
            "node": "online",
            "liquidsoap": liquidsoap_ok,
            "mode": state.get("mode"),
            "queue": [public_item(item) for item in state.get("queue", [])],
            "queue_count": len(state.get("queue", [])),
            "now": public_item(state.get("now")),
            "encoders": encoders,
            "crossfade": state.get("crossfade"),
            "dsp": state.get("dsp"),
            "voice": state.get("voice"),
            "liquidsoap_metadata": metadata,
            "timing": {
                "auto": {"elapsed": auto_elapsed, "remaining": auto_remaining},
                "a": {"elapsed": a_elapsed, "remaining": a_remaining},
                "b": {"elapsed": b_elapsed, "remaining": b_remaining},
            },
            "meters": {
                "a_db": linear_to_db(a_rms),
                "b_db": linear_to_db(b_rms),
                "program_db": linear_to_db(program_rms),
            },
        }
    )

async def set_mode(request: web.Request) -> web.Response:
    data = await request.json()
    mode = str(data.get("mode", "")).lower()
    if mode not in {"auto", "queue", "manual", "recovery"}:
        raise web.HTTPBadRequest(text="invalid mode")

    state["mode"] = mode
    await save_state()

    try:
        await liq(f"var.set studio_mode = {mode}")
    except Exception:
        pass

    return web.json_response({"ok": True, "mode": mode})


async def get_queue(request: web.Request) -> web.Response:
    return web.json_response([public_item(item) for item in state.get("queue", [])])


async def queue_add(request: web.Request) -> web.Response:
    data = await request.json()
    items = data.get("items") if isinstance(data, dict) else None
    if items is None:
        items = [data]
    if not isinstance(items, list):
        raise web.HTTPBadRequest()

    for item in items:
        if not isinstance(item, dict):
            raise web.HTTPBadRequest(text="invalid queue item")
        try:
            resolved = resolve_item(item)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        state.setdefault("queue", []).append(resolved)

    await save_state()
    return web.json_response({"ok": True, "count": len(state["queue"])})


async def queue_set(request: web.Request) -> web.Response:
    data = await request.json()
    if not isinstance(data, list):
        raise web.HTTPBadRequest(text="array required")

    try:
        resolved = [resolve_item(item) for item in data if isinstance(item, dict)]
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc

    if len(resolved) != len(data):
        raise web.HTTPBadRequest(text="invalid queue item")

    state["queue"] = resolved
    await save_state()
    return web.json_response({"ok": True})


async def queue_move(request: web.Request) -> web.Response:
    data = await request.json()
    source = int(data.get("from", -1))
    target = int(data.get("to", -1))
    queue = state.get("queue", [])

    if not (0 <= source < len(queue) and 0 <= target < len(queue)):
        raise web.HTTPBadRequest()

    item = queue.pop(source)
    queue.insert(target, item)
    await save_state()
    return web.json_response({"ok": True})


async def queue_remove(request: web.Request) -> web.Response:
    index = int((await request.json()).get("index", -1))
    queue = state.get("queue", [])
    if not 0 <= index < len(queue):
        raise web.HTTPBadRequest()

    queue.pop(index)
    await save_state()
    return web.json_response({"ok": True})


async def queue_clear(request: web.Request) -> web.Response:
    state["queue"] = []
    await save_state()
    return web.json_response({"ok": True})


async def deck_action(request: web.Request) -> web.Response:
    deck = request.match_info["deck"]
    action = request.match_info["action"]

    if deck not in ("a", "b") or action not in (
        "load",
        "play",
        "pause",
        "stop",
        "cue",
        "air",
        "skip",
        "volume",
    ):
        raise web.HTTPNotFound()

    data: dict[str, Any] = {}
    if request.can_read_body:
        try:
            data = await request.json()
        except Exception:
            data = {}

    try:
        if action == "load":
            try:
                item = resolve_item(data)
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
            uri = str(item.get("uri", "")).strip()
            result = await liq(f"deck_{deck}.push {uri}")
        elif action == "skip":
            result = await liq(f"deck_{deck}.skip")
        elif action == "volume":
            value = max(0.0, min(1.5, float(data.get("value", 100)) / 100.0))
            result = await liq(f"var.set deck_{deck}_gain = {value}")
        elif action in ("air", "play"):
            result = await liq(f"var.set manual_deck = {deck}")
        elif action == "pause":
            result = await liq("var.set manual_deck = none")
        elif action == "stop":
            first = await liq("var.set manual_deck = none")
            second = await liq(f"deck_{deck}.skip")
            result = first + "\n" + second
        else:
            result = "cue handled by browser preview"

        return web.json_response({"ok": True, "result": result})
    except web.HTTPException:
        raise
    except Exception as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from exc


async def aux_action(request: web.Request) -> web.Response:
    deck = request.match_info["deck"]
    action = request.match_info["action"]
    if deck not in ("1", "2", "3") or action not in (
        "load", "play", "pause", "stop", "skip", "volume"
    ):
        raise web.HTTPNotFound()

    data: dict[str, Any] = {}
    if request.can_read_body:
        try:
            data = await request.json()
        except Exception:
            data = {}

    try:
        if action == "load":
            try:
                item = resolve_item(data)
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
            result = await liq(f"aux_{deck}.push {item['uri']}")
        elif action == "play":
            result = await liq(f"var.set aux_{deck}_active = true")
        elif action == "pause":
            result = await liq(f"var.set aux_{deck}_active = false")
        elif action == "stop":
            first = await liq(f"var.set aux_{deck}_active = false")
            second = await liq(f"aux_{deck}.skip")
            result = first + "\n" + second
        elif action == "skip":
            result = await liq(f"aux_{deck}.skip")
        else:
            value = max(0.0, min(2.0, float(data.get("value", 100)) / 100.0))
            result = await liq(f"var.set aux_{deck}_gain = {value}")

        return web.json_response({"ok": True, "result": result})
    except web.HTTPException:
        raise
    except Exception as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from exc


async def encoder_action(request: web.Request) -> web.Response:
    action = request.match_info["action"]
    if action not in ("start", "stop", "restart"):
        raise web.HTTPNotFound()

    try:
        if action == "restart":
            first = await liq("out.stop")
            await asyncio.sleep(0.5)
            second = await liq("out.start")
            result = first + "\n" + second
        else:
            result = await liq("out." + action)

        return web.json_response({"ok": True, "result": result})
    except Exception as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from exc


async def crossfade_apply(request: web.Request) -> web.Response:
    data = await request.json()

    raw_ms = float(data.get("ms", 4500))
    raw_in = float(data.get("fadeIn", data.get("fade_in", 1200)))
    raw_out = float(data.get("fadeOut", data.get("fade_out", 2800)))

    duration = raw_ms / 1000.0 if raw_ms > 50 else raw_ms
    fade_in = raw_in / 1000.0 if raw_in > 50 else raw_in
    fade_out = raw_out / 1000.0 if raw_out > 50 else raw_out

    overlap_db = float(data.get("overlapDb", -9))
    silence_db = float(data.get("silenceDb", -48))
    silence_raw = float(data.get("silenceMs", 900))
    silence_max = silence_raw / 1000.0 if silence_raw > 50 else silence_raw

    fade_types = {"lin", "sin", "log", "exp"}
    fade_in_type = str(data.get("fadeInType", "lin")).lower()
    fade_out_type = str(data.get("fadeOutType", "lin")).lower()
    if fade_in_type not in fade_types:
        fade_in_type = "lin"
    if fade_out_type not in fade_types:
        fade_out_type = "lin"
    mode = str(data.get("mode", "smart")).lower()
    if mode not in {"smart", "always"}:
        mode = "smart"

    cfg = {
        "enabled": bool(data.get("enable", True)),
        "mode": mode,
        "duration": max(0.0, min(20.0, duration)),
        "fade_in": max(0.0, min(20.0, fade_in)),
        "fade_out": max(0.0, min(20.0, fade_out)),
        "fade_in_type": fade_in_type,
        "fade_out_type": fade_out_type,
        "curve": max(1.0, min(100.0, float(data.get("curve", 10)))),
        "overlap_db": max(-60.0, min(0.0, overlap_db)),
        "gap_killer": bool(data.get("gapKiller", True)),
        "silence_db": max(-80.0, min(-10.0, silence_db)),
        "silence_max": max(0.1, min(30.0, silence_max)),
        "respect_cue": bool(data.get("respectCue", True)),
        "crossfade_jingles": bool(data.get("jingles", False)),
    }
    state["crossfade"] = cfg
    await save_state()

    commands = [
        ("xf_enabled", "true" if cfg["enabled"] else "false"),
        ("xf_smart", "true" if cfg["mode"] == "smart" else "false"),
        ("xf_duration", cfg["duration"]),
        ("xf_in", cfg["fade_in"]),
        ("xf_out", cfg["fade_out"]),
        ("xf_overlap_db", cfg["overlap_db"]),
        ("xf_jingles", "true" if cfg["crossfade_jingles"] else "false"),
        ("gap_enabled", "true" if cfg["gap_killer"] else "false"),
        ("gap_threshold", cfg["silence_db"]),
        ("gap_max", cfg["silence_max"]),
    ]
    results = []
    for name, value in commands:
        try:
            results.append(await liq(f"var.set {name} = {value}"))
        except Exception as exc:
            results.append(str(exc))

    return web.json_response(
        {
            "ok": True,
            "crossfade": cfg,
            "result": results,
            "applies": "live",
        }
    )

async def dsp_apply(request: web.Request) -> web.Response:
    data = await request.json()
    processors = data.get("processors", [])
    by_name = {
        str(item.get("name", "")).lower(): item
        for item in processors
        if isinstance(item, dict)
    }

    def enabled(name: str, default: bool = True) -> bool:
        return bool(by_name.get(name, {}).get("on", default))

    def values(name: str) -> list[float]:
        raw = by_name.get(name, {}).get("values", [])
        result: list[float] = []
        for value in raw:
            try:
                result.append(float(value))
            except Exception:
                result.append(50.0)
        return result

    def at(name: str, index: int, default: float = 50.0) -> float:
        row = values(name)
        return row[index] if index < len(row) else default

    # Sliders use SAM-like 0..100 center-at-50 values in the browser.
    mixer_input = max(0.0, min(2.0, at("mixer", 0) / 50.0))
    mixer_output = max(0.0, min(2.0, at("mixer", 1) / 50.0))

    eq_low = max(-12.0, min(12.0, (at("eq", 0) - 50.0) * 0.24))
    eq_mid = max(-12.0, min(12.0, (at("eq", 1) - 50.0) * 0.24))
    eq_high = max(-12.0, min(12.0, (at("eq", 2) - 50.0) * 0.24))

    agc_target = -24.0 + (at("agc", 0) / 100.0) * 18.0
    speed = max(0.0, min(100.0, at("agc", 1)))
    agc_up = 30.0 - (speed / 100.0) * 29.9
    agc_down = 5.0 - (speed / 100.0) * 4.98

    stereo_width = max(-1.0, min(1.0, (at("stereo expander", 0) - 50.0) / 50.0))

    bass_frequency = 60.0 + (at("bass eq", 0) / 100.0) * 340.0
    bass_gain = max(-12.0, min(12.0, (at("bass eq", 1) - 50.0) * 0.24))

    comp_threshold = -40.0 + (at("compressor", 0) / 100.0) * 35.0
    comp_ratio = 1.0 + (at("compressor", 1) / 100.0) * 9.0

    limiter_threshold = -6.0 + (at("limiter", 0) / 100.0) * 5.9

    cfg = {
        "mixer": enabled("mixer", True),
        "mixer_input_gain": mixer_input,
        "mixer_output_gain": mixer_output,
        "eq": enabled("eq", True),
        "eq_low": eq_low,
        "eq_mid": eq_mid,
        "eq_high": eq_high,
        "agc": enabled("agc", True),
        "agc_target": agc_target,
        "agc_up": agc_up,
        "agc_down": agc_down,
        "stereo": enabled("stereo expander", False),
        "stereo_width": stereo_width,
        "bass": enabled("bass eq", False),
        "bass_frequency": bass_frequency,
        "bass_gain": bass_gain,
        "compressor": enabled("compressor", True),
        "comp_threshold": comp_threshold,
        "comp_ratio": comp_ratio,
        "limiter": enabled("limiter", True),
        "limiter_threshold": limiter_threshold,
    }
    state["dsp"] = cfg
    await save_state()

    commands = [
        ("mixer_enabled", "true" if cfg["mixer"] else "false"),
        ("mixer_input_gain", cfg["mixer_input_gain"]),
        ("mixer_output_gain", cfg["mixer_output_gain"]),
        ("eq_enabled", "true" if cfg["eq"] else "false"),
        ("eq_low", cfg["eq_low"]),
        ("eq_mid", cfg["eq_mid"]),
        ("eq_high", cfg["eq_high"]),
        ("agc_enabled", "true" if cfg["agc"] else "false"),
        ("agc_target", cfg["agc_target"]),
        ("agc_up", cfg["agc_up"]),
        ("agc_down", cfg["agc_down"]),
        ("stereo_enabled", "true" if cfg["stereo"] else "false"),
        ("stereo_width", cfg["stereo_width"]),
        ("bass_enabled", "true" if cfg["bass"] else "false"),
        ("bass_frequency", cfg["bass_frequency"]),
        ("bass_gain", cfg["bass_gain"]),
        ("comp_enabled", "true" if cfg["compressor"] else "false"),
        ("comp_threshold", cfg["comp_threshold"]),
        ("comp_ratio", cfg["comp_ratio"]),
        ("limiter_enabled", "true" if cfg["limiter"] else "false"),
        ("limiter_threshold", cfg["limiter_threshold"]),
    ]

    results = []
    for name, value in commands:
        try:
            results.append(await liq(f"var.set {name} = {value}"))
        except Exception as exc:
            results.append(str(exc))

    return web.json_response({"ok": True, "dsp": cfg, "result": results})


def db_to_gain(db: float) -> float:
    return 10 ** (db / 20.0)


async def voice_ptt(request: web.Request) -> web.Response:
    data = await request.json()
    active = bool(data.get("active"))
    duck = float(data.get("duckDb", -8))
    state["voice"] = {
        "active": active,
        "duck_db": duck,
        "fade_ms": int(data.get("fadeMs", 350)),
    }
    await save_state()

    gain = db_to_gain(duck) if active and data.get("autoDuck", True) else 1.0
    try:
        await liq(f"var.set music_gain = {gain}")
        await liq(f"var.set voice_active = {'true' if active else 'false'}")
    except Exception:
        pass

    return web.json_response({"ok": True})


async def voice_ws(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(max_msg_size=2 * 1024 * 1024, heartbeat=20)
    await ws.prepare(request)

    try:
        input_rate = int(request.query.get("rate", "48000"))
    except ValueError:
        input_rate = 48000
    input_rate = max(8000, min(96000, input_rate))

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "f32le",
        "-ar",
        str(input_rate),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        "-content_type",
        "audio/mpeg",
        "-f",
        "mp3",
        (
            f"icecast://source:{VOICE_HARBOR_PASSWORD}@"
            f"{VOICE_HARBOR_HOST}:{VOICE_HARBOR_PORT}/voice"
        ),
    ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        async for message in ws:
            if message.type == WSMsgType.BINARY and process.stdin:
                process.stdin.write(message.data)
                await process.stdin.drain()
            elif message.type == WSMsgType.ERROR:
                break
    finally:
        if process.stdin:
            try:
                process.stdin.close()
            except Exception:
                pass

        try:
            await asyncio.wait_for(process.wait(), 2)
        except asyncio.TimeoutError:
            process.kill()

    return ws


async def save_multipart_file(
    request: web.Request,
    directory: pathlib.Path,
    default_name: str,
) -> tuple[pathlib.Path, str]:
    reader = await request.multipart()
    field = await reader.next()
    if field is None:
        raise web.HTTPBadRequest(text="file required")

    original = field.filename or default_name
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", original)
    destination = directory / f"{int(time.time())}-{name}"

    with destination.open("wb") as handle:
        while True:
            chunk = await field.read_chunk(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)

    return destination, name


async def voice_track_upload(request: web.Request) -> web.Response:
    destination, name = await save_multipart_file(
        request,
        VOICE_DIR,
        f"voice-{int(time.time())}.webm",
    )
    return web.json_response(
        {
            "ok": True,
            "name": name,
            "path": str(destination),
            "uri": "file://" + str(destination),
        }
    )


async def fx_upload(request: web.Request) -> web.Response:
    destination, name = await save_multipart_file(
        request,
        FX_DIR,
        f"fx-{int(time.time())}.mp3",
    )
    return web.json_response(
        {
            "ok": True,
            "name": name,
            "path": str(destination),
            "uri": "file://" + str(destination),
        }
    )


async def fx_play(request: web.Request) -> web.Response:
    data = await request.json()
    uri = str(data.get("uri", "")).strip()
    if not uri:
        raise web.HTTPBadRequest(text="uri required")

    try:
        result = await liq(f"fx.push {uri}")
    except Exception as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from exc

    return web.json_response({"ok": True, "result": result})


async def get_catalog(request: web.Request) -> web.Response:
    return web.json_response([public_item(item) for item in catalog_pool()])


async def vault_sync(request: web.Request) -> web.Response:
    data = await request.json() if request.can_read_body else {}
    limit = max(1, min(25000, int(data.get("limit", 25000))))
    default_category = str(data.get("category", "Telegram")).strip() or "Telegram"

    if not VAULT_TOKEN:
        raise web.HTTPServiceUnavailable(text="TELEGRAM_VAULT_TOKEN is not configured")

    existing = load_json(AUTO_POOL_FILE, [])
    categories = {
        int(item.get("message_id")): item.get("category")
        for item in existing
        if item.get("message_id") is not None
    }

    url = f"{VAULT_BASE_URL}/index?limit={limit}&token={VAULT_TOKEN}"
    async with ClientSession() as session:
        async with session.get(url, timeout=120) as response:
            if response.status != 200:
                raise web.HTTPServiceUnavailable(
                    text=f"vault returned HTTP {response.status}"
                )
            payload = await response.json()

    pool = []
    for item in payload.get("items", []):
        message_id = int(item["message_id"])
        pool.append(
            {
                "message_id": message_id,
                "artist": item.get("artist", ""),
                "title": item.get("title", "") or item.get("filename", ""),
                "filename": item.get("filename", ""),
                "size": item.get("size"),
                "mime": item.get("mime"),
                "category": categories.get(message_id) or default_category,
                "uri": (
                    f"{VAULT_BASE_URL}/media/{message_id}"
                    f"?token={VAULT_TOKEN}"
                ),
            }
        )

    tmp = AUTO_POOL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(pool, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(AUTO_POOL_FILE)
    return web.json_response({"ok": True, "count": len(pool)})


async def relay_stats(request: web.Request) -> web.Response:
    if not YESSTREAMING_STATUS_URL:
        return web.json_response(
            {"configured": False, "listeners": None, "peak": None, "sources": []}
        )

    try:
        async with ClientSession() as session:
            async with session.get(YESSTREAMING_STATUS_URL, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError(f"status HTTP {response.status}")
                payload = await response.json(content_type=None)

        ice = payload.get("icestats", payload) if isinstance(payload, dict) else {}
        sources = ice.get("source", []) if isinstance(ice, dict) else []
        if isinstance(sources, dict):
            sources = [sources]

        cleaned = []
        listeners = 0
        peak = 0
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict):
                continue
            current = int(source.get("listeners", 0) or 0)
            source_peak = int(source.get("listener_peak", 0) or 0)
            listeners += current
            peak = max(peak, source_peak)
            cleaned.append(
                {
                    "listenurl": source.get("listenurl"),
                    "server_name": source.get("server_name"),
                    "server_description": source.get("server_description"),
                    "title": source.get("title"),
                    "listeners": current,
                    "peak": source_peak,
                    "bitrate": source.get("bitrate"),
                }
            )

        return web.json_response(
            {
                "configured": True,
                "listeners": listeners,
                "peak": peak,
                "sources": cleaned,
            }
        )
    except Exception as exc:
        return web.json_response(
            {"configured": True, "error": str(exc), "listeners": None, "peak": None},
            status=502,
        )


async def get_requests(request: web.Request) -> web.Response:
    return web.json_response(state.get("requests", []))


async def request_add(request: web.Request) -> web.Response:
    data = await request.json()
    message_id = data.get("message_id")
    match = None

    if message_id is not None:
        for item in catalog_pool():
            if int(item.get("message_id", -1)) == int(message_id):
                match = item
                break
    else:
        artist = str(data.get("artist", "")).casefold().strip()
        title = str(data.get("title", "")).casefold().strip()
        for item in catalog_pool():
            if (
                str(item.get("artist", "")).casefold().strip() == artist
                and str(item.get("title", "")).casefold().strip() == title
            ):
                match = item
                break

    if not match:
        raise web.HTTPNotFound(text="track not found")

    conflict = recent_conflict(match)
    row = {
        "id": secrets.token_hex(8),
        "created_at": int(time.time()),
        "requested_by": str(data.get("requested_by", "listener"))[:80],
        "track": public_item(match),
        "status": "blocked" if conflict else "pending",
        "reason": "separation rule" if conflict else "",
    }
    state.setdefault("requests", []).append(row)
    state["requests"] = state["requests"][-500:]
    await save_state()
    return web.json_response(row)


async def request_decide(request: web.Request) -> web.Response:
    request_id = request.match_info["request_id"]
    action = request.match_info["action"]
    if action not in ("approve", "reject"):
        raise web.HTTPNotFound()

    row = next(
        (item for item in state.get("requests", []) if item.get("id") == request_id),
        None,
    )
    if not row:
        raise web.HTTPNotFound()

    if action == "approve":
        try:
            resolved = resolve_item(row.get("track", {}))
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        state.setdefault("queue", []).append(resolved)
        row["status"] = "approved"
        row["reason"] = ""
    else:
        row["status"] = "rejected"

    await save_state()
    return web.json_response({"ok": True, "request": row})


async def get_clockwheel(request: web.Request) -> web.Response:
    return web.json_response(state.get("clockwheel", []))


async def set_clockwheel(request: web.Request) -> web.Response:
    data = await request.json()
    if not isinstance(data, list):
        raise web.HTTPBadRequest()

    if len(data) > 250:
        raise web.HTTPBadRequest(text="clock has too many entries")

    allowed_kinds = {"category", "request", "comment", "directory"}
    allowed_selection = {
        "random", "weighted", "least_recent_song",
        "least_recent_artist", "sequential"
    }
    normalized = []
    for raw in data:
        if not isinstance(raw, dict):
            raise web.HTTPBadRequest(text="invalid clock entry")
        kind = str(raw.get("kind", "category")).lower()
        if kind not in allowed_kinds:
            raise web.HTTPBadRequest(text="invalid clock entry kind")
        selection = str(raw.get("selection", "random")).lower()
        if selection not in allowed_selection:
            selection = "random"
        normalized.append(
            {
                "kind": kind,
                "category": str(raw.get("category", ""))[:120],
                "selection": selection,
                "enforce_rules": bool(raw.get("enforce_rules", True)),
                "comment": str(raw.get("comment", ""))[:240],
            }
        )

    state["clockwheel"] = normalized
    state["clock_index"] = 0
    await save_state()
    return web.json_response({"ok": True, "entries": len(normalized)})


async def get_schedule(request: web.Request) -> web.Response:
    return web.json_response(state.get("schedule", []))


async def set_schedule(request: web.Request) -> web.Response:
    data = await request.json()
    if not isinstance(data, list):
        raise web.HTTPBadRequest()

    state["schedule"] = data
    await save_state()
    return web.json_response({"ok": True, "count": len(data)})


async def execute_pal(script: str, log: list[str] | None = None) -> list[str]:
    output = log if log is not None else []

    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        match = re.match(r'^LOG\s+"(.*)"$', line, re.I)
        if match:
            output.append(match.group(1))
            continue

        match = re.match(r"^WAIT\s+(\d+(?:\.\d+)?)$", line, re.I)
        if match:
            await asyncio.sleep(min(3600.0, float(match.group(1))))
            continue

        match = re.match(r"^MODE\s+(AUTO|QUEUE|MANUAL|RECOVERY)$", line, re.I)
        if match:
            state["mode"] = match.group(1).lower()
            await save_state()
            output.append("MODE " + match.group(1).upper())
            continue

        match = re.match(r'^QUEUE\s+CATEGORY\s+"(.*)"\s+(\d+)$', line, re.I)
        if match:
            count = min(100, int(match.group(2)))
            added = 0
            for _ in range(count):
                item = choose_auto(match.group(1))
                if item:
                    state.setdefault("queue", []).append(item)
                    added += 1
            await save_state()
            output.append(f"QUEUED {added} {match.group(1)}")
            continue

        match = re.match(r'^QUEUE\s+URI\s+"(.*)"$', line, re.I)
        if match:
            state.setdefault("queue", []).append(
                {
                    "artist": "",
                    "title": "PAL URI",
                    "uri": match.group(1),
                    "category": "PAL",
                }
            )
            await save_state()
            output.append("QUEUED URI")
            continue

        match = re.match(r"^ENCODER\s+(START|STOP|RESTART)$", line, re.I)
        if match:
            action = match.group(1).lower()
            if action == "restart":
                await liq("out.stop")
                await asyncio.sleep(0.3)
                await liq("out.start")
            else:
                await liq("out." + action)
            output.append("ENCODER " + match.group(1).upper())
            continue

        if re.match(r"^SKIP$", line, re.I):
            await liq("auto.skip")
            output.append("SKIP")
            continue

        raise ValueError("Unsupported PAL command: " + line)

    return output


async def pal_run(request: web.Request) -> web.Response:
    data = await request.json()
    script = str(data.get("script", ""))
    try:
        log = await execute_pal(script, [])
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    return web.json_response({"ok": True, "log": log})


async def pal_scripts_list(request: web.Request) -> web.Response:
    scripts = state.get("pal_scripts", {})
    return web.json_response(
        [
            {"name": name, "script": script}
            for name, script in sorted(
                scripts.items(),
                key=lambda item: item[0].casefold(),
            )
        ]
    )


async def pal_script_get(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    scripts = state.get("pal_scripts", {})
    if name not in scripts:
        raise web.HTTPNotFound()
    return web.json_response({"name": name, "script": scripts[name]})


def validate_pal_script(script: str) -> None:
    patterns = [
        r'^LOG\s+".*"$',
        r"^WAIT\s+\d+(?:\.\d+)?$",
        r"^MODE\s+(AUTO|QUEUE|MANUAL|RECOVERY)$",
        r'^QUEUE\s+CATEGORY\s+".*"\s+\d+$',
        r'^QUEUE\s+URI\s+".*"$',
        r"^ENCODER\s+(START|STOP|RESTART)$",
        r"^SKIP$",
    ]
    for raw in script.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not any(re.match(pattern, line, re.I) for pattern in patterns):
            raise ValueError("Unsupported PAL command: " + line)


async def pal_script_save(request: web.Request) -> web.Response:
    name = request.match_info["name"].strip()
    if not name or len(name) > 80:
        raise web.HTTPBadRequest(text="invalid script name")

    data = await request.json()
    script = str(data.get("script", ""))
    try:
        validate_pal_script(script)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc

    state.setdefault("pal_scripts", {})[name] = script
    await save_state()
    return web.json_response({"ok": True, "name": name})


async def pal_script_delete(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    scripts = state.setdefault("pal_scripts", {})
    if name not in scripts:
        raise web.HTTPNotFound()
    del scripts[name]
    await save_state()
    return web.json_response({"ok": True})


async def run_scheduled_event(event: dict[str, Any]) -> None:
    action = str(event.get("action", "")).lower()

    if action in ("run pal", "pal"):
        script_name = str(event.get("script_name") or "").strip()
        if script_name:
            script = str(state.get("pal_scripts", {}).get(script_name, ""))
            if not script:
                raise ValueError("PAL script not found: " + script_name)
        else:
            script = str(event.get("script") or event.get("payload") or "")
        await execute_pal(script, [])
        return

    if action in ("queue category", "category"):
        category = str(event.get("category") or event.get("payload") or "")
        count = int(event.get("count", 1) or 1)
        for _ in range(max(0, min(count, 100))):
            item = choose_auto(category)
            if item:
                state.setdefault("queue", []).append(item)
        await save_state()
        return

    if action in ("load clock", "clock"):
        if isinstance(event.get("clock"), list):
            state["clockwheel"] = event["clock"]
            await save_state()
        return

    if action in ("station id", "id"):
        uri = str(event.get("uri", ""))
        if uri:
            state.setdefault("queue", []).insert(
                0,
                {
                    "artist": "Louder",
                    "title": "Station ID",
                    "uri": uri,
                    "category": "Station IDs",
                },
            )
            await save_state()


async def scheduler_loop(app: web.Application) -> None:
    while True:
        now = time.localtime()
        hhmm = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        day = time.strftime("%Y-%m-%d", now)
        changed = False

        for event in state.get("schedule", []):
            if str(event.get("time", "")) == hhmm and event.get("_last") != day:
                try:
                    await run_scheduled_event(event)
                except Exception as exc:
                    print("scheduler:", exc, flush=True)
                event["_last"] = day
                changed = True

        if changed:
            await save_state()

        await asyncio.sleep(15)


async def on_startup(app: web.Application) -> None:
    app["scheduler_task"] = asyncio.create_task(scheduler_loop(app))


async def on_cleanup(app: web.Application) -> None:
    task = app.get("scheduler_task")
    if task:
        task.cancel()


async def history_event(request: web.Request) -> web.Response:
    data = await request.json()
    item = {
        "ts": time.time(),
        "time": time.strftime("%H:%M:%S"),
        **data,
    }
    state.setdefault("history", []).append(item)
    state["history"] = state["history"][-5000:]
    state["now"] = data
    await save_state()
    return web.json_response({"ok": True})


app = web.Application(
    middlewares=[cors_auth],
    client_max_size=64 * 1024 * 1024,
)
app.router.add_get(
    "/",
    lambda request: web.json_response({"name": "Louder Playout Node", "ok": True}),
)
app.router.add_get("/health", health)
app.router.add_get("/status", status)
app.router.add_post("/mode", set_mode)
app.router.add_get("/queue", get_queue)
app.router.add_post("/queue/add", queue_add)
app.router.add_post("/queue/set", queue_set)
app.router.add_post("/queue/move", queue_move)
app.router.add_post("/queue/remove", queue_remove)
app.router.add_post("/queue/clear", queue_clear)
app.router.add_post("/deck/{deck}/{action}", deck_action)
app.router.add_post("/aux/{deck}/{action}", aux_action)
app.router.add_post("/encoder/{action}", encoder_action)
app.router.add_post("/crossfade/apply", crossfade_apply)
app.router.add_post("/dsp/apply", dsp_apply)
app.router.add_post("/voice/ptt", voice_ptt)
app.router.add_get("/ws/voice", voice_ws)
app.router.add_post("/voice-track", voice_track_upload)
app.router.add_post("/fx/upload", fx_upload)
app.router.add_post("/fx/play", fx_play)
app.router.add_get("/catalog", get_catalog)
app.router.add_post("/vault/sync", vault_sync)
app.router.add_get("/stats", relay_stats)
app.router.add_get("/requests", get_requests)
app.router.add_post("/requests/add", request_add)
app.router.add_post("/requests/{request_id}/{action}", request_decide)
app.router.add_get("/clockwheel", get_clockwheel)
app.router.add_post("/clockwheel", set_clockwheel)
app.router.add_get("/schedule", get_schedule)
app.router.add_post("/schedule", set_schedule)
app.router.add_post("/pal/run", pal_run)
app.router.add_get("/pal/scripts", pal_scripts_list)
app.router.add_get("/pal/scripts/{name}", pal_script_get)
app.router.add_post("/pal/scripts/{name}", pal_script_save)
app.router.add_delete("/pal/scripts/{name}", pal_script_delete)
app.router.add_post("/history", history_event)
app.router.add_post("/internal/history", history_event)
app.router.add_get("/internal/next", internal_next)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == "__main__":
    web.run_app(
        app,
        host=os.getenv("LOUDER_API_BIND", "0.0.0.0"),
        port=int(os.getenv("LOUDER_API_PORT", "8787")),
    )
