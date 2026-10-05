from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shlex
import subprocess
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

APP_VERSION = "0.1.0"
DATA_DIR = pathlib.Path(os.getenv("LOUDER_DATA_DIR", "/app/state"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
SOCKET_PATH = os.getenv("LIQUIDSOAP_SOCKET", "/tmp/louder-liquidsoap.sock")
TOKEN = os.getenv("CONTROL_API_TOKEN", "")
MIC_HARBOR_URL = os.getenv(
    "MIC_HARBOR_URL",
    "icecast://source:changeme@127.0.0.1:8005/mic",
)

DEFAULT_STATE: dict[str, Any] = {
    "mode": "auto",
    "decks": {
        "a": {"air": False, "volume": 0.82, "last_uri": None},
        "b": {"air": False, "volume": 0.82, "last_uri": None},
    },
    "encoder": {"running": False},
    "crossfade": {
        "duration": 4.5,
        "fade_in": 1.2,
        "fade_out": 2.8,
    },
    "dsp": {},
    "last_action": None,
}


def load_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text())
        merged = DEFAULT_STATE | data
        merged["decks"] = DEFAULT_STATE["decks"] | data.get("decks", {})
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_STATE))


state = load_state()


def save_state() -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        return
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "Invalid bearer token")


async def liq(command: str, timeout: float = 3.0) -> str:
    if not pathlib.Path(SOCKET_PATH).exists():
        raise RuntimeError("Liquidsoap control socket is not available")

    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(SOCKET_PATH),
        timeout=timeout,
    )
    try:
        writer.write((command.strip() + "\n").encode())
        await writer.drain()
        chunks: list[str] = []
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\r\n")
            if text == "END":
                break
            chunks.append(text)
        return "\n".join(chunks)
    finally:
        writer.close()
        await writer.wait_closed()


async def liq_optional(command: str) -> tuple[bool, str]:
    try:
        return True, await liq(command)
    except Exception as exc:
        return False, str(exc)


class Payload(BaseModel):
    uri: str | None = None
    value: float | int | str | bool | None = None
    mode: str | None = None
    active: bool | None = None
    duckDb: float | None = None
    fadeMs: int | None = None
    autoDuck: bool | None = None
    processors: list[dict[str, Any]] | None = None
    duration: float | None = None
    fade_in: float | None = None
    fade_out: float | None = None


app = FastAPI(title="Louder Playout Node", version=APP_VERSION)

origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "*").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    ok, version = await liq_optional("version")
    return {
        "ok": True,
        "api_version": APP_VERSION,
        "liquidsoap": {"online": ok, "version": version if ok else None},
    }


@app.get("/status", dependencies=[Depends(require_token)])
async def status() -> dict[str, Any]:
    online, uptime = await liq_optional("uptime")
    on_air_ok, on_air = await liq_optional("request.on_air")
    return {
        "ok": online,
        "node": "online",
        "liquidsoap": {"online": online, "uptime": uptime if online else None},
        "mode": state["mode"],
        "decks": state["decks"],
        "encoder": state["encoder"],
        "on_air": on_air if on_air_ok else None,
        "last_action": state["last_action"],
        "time": time.time(),
    }


@app.post("/mode", dependencies=[Depends(require_token)])
async def set_mode(payload: Payload) -> dict[str, Any]:
    mode = (payload.mode or "").lower()
    if mode not in {"auto", "queue", "manual", "recovery"}:
        raise HTTPException(400, "Invalid mode")
    state["mode"] = mode
    state["last_action"] = f"mode:{mode}"
    save_state()
    return {"ok": True, "mode": mode}


def deck_name(deck: str) -> str:
    if deck not in {"a", "b"}:
        raise HTTPException(404, "Unknown deck")
    return deck


@app.post("/deck/{deck}/load", dependencies=[Depends(require_token)])
async def deck_load(deck: str, payload: Payload) -> dict[str, Any]:
    deck = deck_name(deck)
    if not payload.uri:
        raise HTTPException(400, "uri required")
    result = await liq(f"deck_{deck}.push {payload.uri}")
    state["decks"][deck]["last_uri"] = payload.uri
    state["last_action"] = f"deck:{deck}:load"
    save_state()
    return {"ok": True, "request_id": result}


@app.post("/deck/{deck}/play", dependencies=[Depends(require_token)])
async def deck_play(deck: str) -> dict[str, Any]:
    deck = deck_name(deck)
    await liq(f"var.set deck_{deck}_air = true")
    state["decks"][deck]["air"] = True
    state["last_action"] = f"deck:{deck}:play"
    save_state()
    return {"ok": True}


@app.post("/deck/{deck}/air", dependencies=[Depends(require_token)])
async def deck_air(deck: str) -> dict[str, Any]:
    return await deck_play(deck)


@app.post("/deck/{deck}/pause", dependencies=[Depends(require_token)])
async def deck_pause(deck: str) -> dict[str, Any]:
    deck = deck_name(deck)
    await liq(f"var.set deck_{deck}_air = false")
    state["decks"][deck]["air"] = False
    state["last_action"] = f"deck:{deck}:pause"
    save_state()
    return {"ok": True}


@app.post("/deck/{deck}/stop", dependencies=[Depends(require_token)])
async def deck_stop(deck: str) -> dict[str, Any]:
    deck = deck_name(deck)
    await liq_optional(f"deck_{deck}.skip")
    await liq(f"var.set deck_{deck}_air = false")
    state["decks"][deck]["air"] = False
    state["last_action"] = f"deck:{deck}:stop"
    save_state()
    return {"ok": True}


@app.post("/deck/{deck}/cue", dependencies=[Depends(require_token)])
async def deck_cue(deck: str) -> dict[str, Any]:
    deck = deck_name(deck)
    # Cue is represented as loaded but not routed to AIR on the server.
    await liq(f"var.set deck_{deck}_air = false")
    state["decks"][deck]["air"] = False
    state["last_action"] = f"deck:{deck}:cue"
    save_state()
    return {"ok": True}


@app.post("/deck/{deck}/volume", dependencies=[Depends(require_token)])
async def deck_volume(deck: str, payload: Payload) -> dict[str, Any]:
    deck = deck_name(deck)
    raw = float(payload.value if payload.value is not None else 82)
    value = raw / 100.0 if raw > 1 else raw
    value = max(0.0, min(1.5, value))
    await liq(f"var.set deck_{deck}_volume = {value}")
    state["decks"][deck]["volume"] = value
    state["last_action"] = f"deck:{deck}:volume"
    save_state()
    return {"ok": True, "value": value}


@app.post("/queue/push", dependencies=[Depends(require_token)])
async def queue_push(payload: Payload) -> dict[str, Any]:
    if not payload.uri:
        raise HTTPException(400, "uri required")
    request_id = await liq(f"auto_queue.push {payload.uri}")
    state["last_action"] = "queue:push"
    save_state()
    return {"ok": True, "request_id": request_id}


@app.post("/queue/skip", dependencies=[Depends(require_token)])
async def queue_skip() -> dict[str, Any]:
    result = await liq("auto_queue.skip")
    state["last_action"] = "queue:skip"
    save_state()
    return {"ok": True, "result": result}


@app.post("/encoder/start", dependencies=[Depends(require_token)])
async def encoder_start() -> dict[str, Any]:
    result = await liq("yesstreaming.start")
    state["encoder"]["running"] = True
    state["last_action"] = "encoder:start"
    save_state()
    return {"ok": True, "result": result}


@app.post("/encoder/stop", dependencies=[Depends(require_token)])
async def encoder_stop() -> dict[str, Any]:
    result = await liq("yesstreaming.stop")
    state["encoder"]["running"] = False
    state["last_action"] = "encoder:stop"
    save_state()
    return {"ok": True, "result": result}


@app.post("/encoder/restart", dependencies=[Depends(require_token)])
async def encoder_restart() -> dict[str, Any]:
    await liq_optional("yesstreaming.stop")
    await asyncio.sleep(0.6)
    result = await liq("yesstreaming.start")
    state["encoder"]["running"] = True
    state["last_action"] = "encoder:restart"
    save_state()
    return {"ok": True, "result": result}


@app.post("/crossfade/apply", dependencies=[Depends(require_token)])
async def crossfade_apply(request: Request) -> dict[str, Any]:
    body = await request.json()
    duration = float(body.get("ms", 4500)) / 1000.0
    fade_in = float(body.get("fadeIn", 1200)) / 1000.0
    fade_out = float(body.get("fadeOut", 2800)) / 1000.0
    await liq(f"var.set xf_duration = {duration}")
    await liq(f"var.set xf_in = {fade_in}")
    await liq(f"var.set xf_out = {fade_out}")
    state["crossfade"] = {
        "duration": duration,
        "fade_in": fade_in,
        "fade_out": fade_out,
        "raw": body,
    }
    state["last_action"] = "crossfade:apply"
    save_state()
    return {"ok": True, "crossfade": state["crossfade"]}


@app.post("/dsp/apply", dependencies=[Depends(require_token)])
async def dsp_apply(payload: Payload) -> dict[str, Any]:
    processors = payload.processors or []
    state["dsp"] = {"processors": processors}
    # Map the SAM-like controls that Liquidsoap exposes safely at runtime.
    by_name = {str(x.get("name", "")).lower(): x for x in processors}
    agc = by_name.get("agc")
    if agc and agc.get("values"):
        target = -24.0 + (float(agc["values"][0]) / 100.0) * 18.0
        await liq_optional(f"var.set agc_target = {target}")
    comp = by_name.get("compressor")
    if comp and comp.get("values"):
        threshold = -40.0 + (float(comp["values"][0]) / 100.0) * 34.0
        await liq_optional(f"var.set comp_threshold = {threshold}")
    limiter = by_name.get("limiter")
    if limiter and limiter.get("values"):
        ceiling = -6.0 + (float(limiter["values"][0]) / 100.0) * 5.5
        await liq_optional(f"var.set limiter_threshold = {ceiling}")
    state["last_action"] = "dsp:apply"
    save_state()
    return {"ok": True, "dsp": state["dsp"]}


@app.post("/voice/ptt", dependencies=[Depends(require_token)])
async def voice_ptt(payload: Payload) -> dict[str, Any]:
    active = bool(payload.active)
    await liq(f"var.set mic_live = {'true' if active else 'false'}")
    if payload.duckDb is not None:
        # Convert dB ducking to a linear amplification factor.
        factor = 10 ** (float(payload.duckDb) / 20.0)
        await liq_optional(f"var.set mic_duck = {factor}")
    state["last_action"] = f"voice:ptt:{active}"
    save_state()
    return {"ok": True, "active": active}


@app.websocket("/ws/mic")
async def mic_socket(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    if TOKEN and token != TOKEN:
        await websocket.close(code=4401)
        return
    await websocket.accept()

    ffmpeg = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "+nobuffer",
        "-i",
        "pipe:0",
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        "-content_type",
        "audio/mpeg",
        "-f",
        "mp3",
        MIC_HARBOR_URL,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        while True:
            chunk = await websocket.receive_bytes()
            if ffmpeg.stdin is None:
                break
            ffmpeg.stdin.write(chunk)
            await ffmpeg.stdin.drain()
    except WebSocketDisconnect:
        pass
    finally:
        if ffmpeg.stdin:
            ffmpeg.stdin.close()
        try:
            await asyncio.wait_for(ffmpeg.wait(), timeout=3)
        except asyncio.TimeoutError:
            ffmpeg.kill()
        await websocket.close()


@app.exception_handler(RuntimeError)
async def runtime_error(_: Request, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})
