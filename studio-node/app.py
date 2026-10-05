from __future__ import annotations

import asyncio
import json
import os
import pathlib
import secrets
import shlex
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path(os.getenv("LOUDER_NODE_DATA", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
SETTINGS = DATA / "settings.json"

TOKEN = os.getenv("LOUDER_NODE_TOKEN", "").strip()
LIQ_HOST = os.getenv("LIQUIDSOAP_HOST", "127.0.0.1")
LIQ_PORT = int(os.getenv("LIQUIDSOAP_PORT", "1234"))
HARBOR_PORT = int(os.getenv("LIQUIDSOAP_HARBOR_PORT", "8090"))
HARBOR_PASSWORD = os.getenv("LIQUIDSOAP_HARBOR_PASSWORD", "change-me")
CORS = [x.strip() for x in os.getenv("LOUDER_STUDIO_ORIGINS", "*").split(",") if x.strip()]

app = FastAPI(title="Louder Cloud Studio Node", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_settings() -> dict[str, Any]:
    if not SETTINGS.exists():
        return {}
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_settings(data: dict[str, Any]) -> None:
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(SETTINGS)


def authorized(auth: str | None) -> bool:
    if not TOKEN:
        return True
    return bool(auth and auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], TOKEN))


def require(auth: str | None) -> None:
    if not authorized(auth):
        raise HTTPException(401, "Unauthorized")


async def liq(command: str, timeout: float = 4.0) -> str:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(LIQ_HOST, LIQ_PORT), timeout=timeout
        )
    except Exception as exc:
        raise HTTPException(503, f"Liquidsoap unavailable: {exc}") from exc

    writer.write((command.strip() + "\n").encode())
    await writer.drain()
    chunks: list[str] = []
    try:
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            if not line:
                break
            s = line.decode(errors="replace").rstrip("\r\n")
            if s == "END":
                break
            chunks.append(s)
    finally:
        writer.write(b"exit\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    return "\n".join(chunks)


class ModeBody(BaseModel):
    mode: str


class ValueBody(BaseModel):
    value: float


class QueueBody(BaseModel):
    uri: str
    artist: str = ""
    title: str = ""


class VoiceBody(BaseModel):
    active: bool
    duckDb: float = -8
    fadeMs: int = 350
    autoDuck: bool = True


class ConfigBody(BaseModel):
    model_config = {"extra": "allow"}


@app.get("/status")
async def status(authorization: str | None = Header(default=None)):
    require(authorization)
    try:
        uptime = await liq("uptime")
        commands = await liq("help")
        return {
            "ok": True,
            "liquidsoap": True,
            "uptime": uptime,
            "harbor_port": HARBOR_PORT,
            "capabilities": {
                "deck_a": "deck_a.push" in commands,
                "deck_b": "deck_b.push" in commands,
                "encoder": "yesstreaming.start" in commands,
                "mic_harbor": True,
            },
        }
    except HTTPException:
        raise


@app.post("/mode")
async def mode(body: ModeBody, authorization: str | None = Header(default=None)):
    require(authorization)
    modes = {"auto": 0, "queue": 1, "manual": 2, "recovery": 3}
    key = body.mode.lower()
    if key not in modes:
        raise HTTPException(400, "Invalid mode")
    await liq(f"var.set studio_mode = {modes[key]}")
    cfg = read_settings()
    cfg["mode"] = key
    write_settings(cfg)
    return {"ok": True, "mode": key}


@app.post("/queue/push")
async def queue_push(body: QueueBody, authorization: str | None = Header(default=None)):
    require(authorization)
    if not body.uri or "\n" in body.uri or "\r" in body.uri:
        raise HTTPException(400, "Invalid URI")
    req_id = await liq(f"deck_a.push {body.uri}")
    return {"ok": True, "request_id": req_id}


@app.post("/deck/{deck}/play")
async def deck_play(deck: str, authorization: str | None = Header(default=None)):
    require(authorization)
    d = _deck(deck)
    await liq(f"var.set {d}_enabled = true")
    return {"ok": True}


@app.post("/deck/{deck}/pause")
async def deck_pause(deck: str, authorization: str | None = Header(default=None)):
    require(authorization)
    d = _deck(deck)
    await liq(f"var.set {d}_enabled = false")
    return {"ok": True}


@app.post("/deck/{deck}/stop")
async def deck_stop(deck: str, authorization: str | None = Header(default=None)):
    require(authorization)
    d = _deck(deck)
    await liq(f"{d}.skip")
    await liq(f"var.set {d}_enabled = false")
    return {"ok": True}


@app.post("/deck/{deck}/cue")
async def deck_cue(deck: str, authorization: str | None = Header(default=None)):
    require(authorization)
    # Browser cue monitoring is handled client-side; this endpoint records selection.
    d = _deck(deck)
    cfg = read_settings()
    cfg["cue_deck"] = d
    write_settings(cfg)
    return {"ok": True, "cue": d}


@app.post("/deck/{deck}/air")
async def deck_air(deck: str, authorization: str | None = Header(default=None)):
    require(authorization)
    d = _deck(deck)
    other = "deck_b" if d == "deck_a" else "deck_a"
    await liq(f"var.set {d}_enabled = true")
    await liq(f"var.set {other}_enabled = false")
    return {"ok": True, "air": d}


@app.post("/deck/{deck}/volume")
async def deck_volume(deck: str, body: ValueBody, authorization: str | None = Header(default=None)):
    require(authorization)
    d = _deck(deck)
    v = max(0.0, min(1.5, body.value / 100.0))
    await liq(f"var.set {d}_gain = {v}")
    return {"ok": True, "gain": v}


def _deck(deck: str) -> str:
    if deck.lower() not in {"a", "b"}:
        raise HTTPException(404, "Unknown deck")
    return f"deck_{deck.lower()}"


@app.post("/encoder/start")
async def encoder_start(authorization: str | None = Header(default=None)):
    require(authorization)
    return {"ok": True, "result": await liq("yesstreaming.start")}


@app.post("/encoder/stop")
async def encoder_stop(authorization: str | None = Header(default=None)):
    require(authorization)
    return {"ok": True, "result": await liq("yesstreaming.stop")}


@app.post("/encoder/restart")
async def encoder_restart(authorization: str | None = Header(default=None)):
    require(authorization)
    await liq("yesstreaming.stop")
    await asyncio.sleep(0.5)
    return {"ok": True, "result": await liq("yesstreaming.start")}


@app.post("/voice/ptt")
async def voice_ptt(body: VoiceBody, authorization: str | None = Header(default=None)):
    require(authorization)
    duck = 10 ** (body.duckDb / 20.0) if body.autoDuck and body.active else 1.0
    await liq(f"var.set music_duck = {duck}")
    return {"ok": True, "active": body.active, "duck": duck}


@app.post("/crossfade/apply")
async def crossfade_apply(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require(authorization)
    cfg = read_settings()
    cfg["crossfade"] = body
    write_settings(cfg)
    # Crossfade topology is generated at Liquidsoap start; persist safely for next reload.
    return {"ok": True, "saved": True, "hot_applied": False, "reload_required": True}


@app.post("/dsp/apply")
async def dsp_apply(body: dict[str, Any], authorization: str | None = Header(default=None)):
    require(authorization)
    cfg = read_settings()
    cfg["dsp"] = body
    write_settings(cfg)
    return {"ok": True, "saved": True, "hot_applied": False, "reload_required": True}


@app.websocket("/voice/live")
async def voice_live(ws: WebSocket):
    token = ws.query_params.get("token", "")
    if TOKEN and not secrets.compare_digest(token, TOKEN):
        await ws.close(code=4401)
        return
    await ws.accept()

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "webm", "-i", "pipe:0",
        "-vn", "-ac", "2", "-ar", "44100",
        "-codec:a", "libmp3lame", "-b:a", "192k",
        "-content_type", "audio/mpeg",
        "-f", "mp3",
        f"icecast://source:{HARBOR_PASSWORD}@127.0.0.1:{HARBOR_PORT}/mic",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        await ws.send_json({"ok": False, "error": "ffmpeg not installed"})
        await ws.close(code=1011)
        return

    await ws.send_json({"ok": True, "state": "ready"})
    try:
        while True:
            data = await ws.receive_bytes()
            if proc.stdin is None:
                break
            proc.stdin.write(data)
            await proc.stdin.drain()
    except WebSocketDisconnect:
        pass
    finally:
        if proc.stdin:
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 3)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
