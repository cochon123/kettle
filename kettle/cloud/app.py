"""Kettle cloud service (FastAPI).

    .venv/bin/python -m kettle cloud            # http://localhost:8700/stage/

Channels:
  /ws/device/{home}   the Kettle in the home: appliance events up, check-in / glow commands down
  /ws/circle?m=<id>   a circle member's phone (PWA)
  /ws/stage           the presenter screen
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import os
import pathlib
import time

import segno
from fastapi import FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..clock import Clock
from .engine import Engine
from .grid import Grid
from .notify import VOICE, Notifier
from .relay import Relay
from .store import Store
from . import cards

log = logging.getLogger("kettle.cloud")
WEB = pathlib.Path(__file__).resolve().parents[2] / "web"
DEVICE_KEY = os.getenv("KETTLE_DEVICE_KEY", "demo-key")
DEMO = os.getenv("KETTLE_DEMO", "1") != "0"

clock = Clock()
store = Store()
grid = Grid()
engine = Engine(clock, Notifier(), store, grid, demo=DEMO)
engine.person_phone = {"margaret": os.getenv("KETTLE_MARGARET_PHONE")}
relay = (Relay(engine, os.environ["KETTLE_SITE"], os.getenv("KETTLE_SITE_SECRET", ""))
         if os.getenv("KETTLE_SITE") else None)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await store.open()
    engine.setup_demo()
    from ..rhythm import DayObs
    for h in engine.homes.values():
        await store.upsert_home(h.id, h.person, h.pronoun)
        if h.kind == "live" and not DEMO:
            # Real history wins over the REFIT seed: rebuild from the continuous aggregate.
            # (Not in demo mode: demo-clock days would pollute a real baseline.)
            for day, first_min in await store.daily_first(h.id):
                h.model.observe(DayObs(day, first_min, None))
    if DEMO:
        await engine.demo_reset(os.getenv("KETTLE_DEMO_START", "6:30"))
    tasks = [asyncio.create_task(_ticker()), asyncio.create_task(grid.run()), asyncio.create_task(_context())]
    if relay:
        tasks.append(asyncio.create_task(relay.run()))
    yield
    for t in tasks:
        t.cancel()


async def _ticker() -> None:
    while True:
        try:
            await engine.tick()
        except Exception:
            log.exception("tick failed")
        await asyncio.sleep(0.5)


async def _context() -> None:
    """Persist grid + weather context to TimescaleDB as it changes."""
    seen = None
    while True:
        await asyncio.sleep(30)
        live = grid.live
        if live.get("fetched") and live.get("fetched") != seen:
            seen = live["fetched"]
            await store.context(seen, "aeso_csd", {k: v for k, v in live.items() if k.endswith("_mw")})
            if grid.weather.get("temp_c") is not None:
                await store.context(seen, "eccc", {"temp_c": grid.weather["temp_c"]})


app = FastAPI(title="Kettle", lifespan=lifespan)


# ---------------------------------------------------------------------- websockets
@app.websocket("/ws/stage")
async def ws_stage(ws: WebSocket):
    await ws.accept()
    send = ws.send_json
    engine.stage_conns.add(send)
    await send(engine.stage_state())
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        engine.stage_conns.discard(send)


@app.websocket("/ws/circle")
async def ws_circle(ws: WebSocket, m: str):
    if m not in engine.members:
        await ws.close(code=4404)
        return
    await ws.accept()
    send = ws.send_json
    engine.circle_conns.setdefault(m, set()).add(send)
    await send(engine.member_state(m))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "respond":
                await engine.respond(m, int(msg["escalation"]), msg["response"])
            elif msg.get("type") == "glow":
                await engine.glow(m, msg.get("home", "margaret"))
    except (WebSocketDisconnect, json.JSONDecodeError):
        pass
    finally:
        engine.circle_conns.get(m, set()).discard(send)


@app.websocket("/ws/device/{home_id}")
async def ws_device(ws: WebSocket, home_id: str, key: str = ""):
    if key != DEVICE_KEY or home_id not in engine.homes:
        await ws.close(code=4403)
        return
    await ws.accept()
    send = ws.send_json
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            t = msg.get("type")
            if t == "hello":
                await engine.device_hello(home_id, send, msg.get("info", {}))
            elif t == "event":
                await engine.ingest(home_id, msg["event"])
            elif t == "heartbeat":
                await engine.device_heartbeat(home_id)
            elif t == "im_fine":
                await engine.self_ok(home_id, "device")
            elif t == "pause":
                await engine.set_pause(home_id, msg.get("hours"))
            elif t == "samples":
                # Defence in depth: the cloud refuses raw readings even if a device sends them.
                log.warning("device %s tried to upload raw samples; dropped", home_id)
    except (WebSocketDisconnect, json.JSONDecodeError):
        pass
    finally:
        await engine.device_gone(home_id, send)


# ---------------------------------------------------------------------- REST
class EventIn(BaseModel):
    kind: str = "on"
    label: str
    human: bool = True
    t: float | None = None
    channel: str = "device"
    dp_w: float | None = None
    duration_s: float | None = None
    confidence: float | None = None


@app.post("/api/events/{home_id}")
async def post_event(home_id: str, ev: EventIn, request: Request):
    """HTTP path for constrained devices (the ESP32 firmware posts here)."""
    if request.headers.get("x-kettle-key") != DEVICE_KEY:
        raise HTTPException(403)
    if home_id not in engine.homes:
        raise HTTPException(404)
    d = ev.model_dump()
    d["t"] = d["t"] or time.time()
    await engine.ingest(home_id, d)
    return {"ok": True}


class Respond(BaseModel):
    member: str
    escalation: int
    response: str


@app.post("/api/respond")
async def respond(r: Respond):
    return await engine.respond(r.member, r.escalation, r.response)


class GlowIn(BaseModel):
    member: str
    home: str = "margaret"


@app.post("/api/glow")
async def glow(g: GlowIn):
    return await engine.glow(g.member, g.home)


class JoinIn(BaseModel):
    name: str
    code: str


@app.post("/api/join")
async def join(j: JoinIn):
    if j.code.strip().lower() != os.getenv("KETTLE_INVITE", "margaret").lower():
        raise HTTPException(403, "That invite code didn't work.")
    m = engine.join(j.name)
    await engine.broadcast()
    return {"member": m.id}


@app.get("/api/state")
async def state():
    return engine.stage_state()


@app.get("/api/member/{mid}")
async def member(mid: str):
    if mid not in engine.members:
        raise HTTPException(404)
    return engine.member_state(mid)


@app.get("/api/data/{name}")
async def data_file(name: str):
    """Small public data files for the deck: jan13 (AESO + ECCC) and refit (evaluation summary)."""
    files = {"jan13": "data/jan13_2024.json", "refit": "data/refit/summary.json",
             "margaret": "data/refit/margaret_baseline.json"}
    if name not in files:
        raise HTTPException(404)
    p = WEB.parent / files[name]
    if not p.exists():
        raise HTTPException(404, "not generated yet")
    return JSONResponse(json.loads(p.read_text()))


@app.get("/api/urls")
async def urls(request: Request):
    """Addresses phones can actually reach (for QR codes): LAN IP and Tailscale IP of this machine."""
    import socket
    import subprocess
    port = request.url.port or 8700
    out = {}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        out["lan"] = f"http://{s.getsockname()[0]}:{port}"
        s.close()
    except Exception:
        pass
    try:
        ts = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=2).stdout.split()
        if ts:
            out["tailscale"] = f"http://{ts[0]}:{port}"
    except Exception:
        pass
    if os.getenv("KETTLE_PUBLIC_URL"):
        out["public"] = os.getenv("KETTLE_PUBLIC_URL").rstrip("/")
    out["best"] = out.get("public") or out.get("lan") or f"http://{request.url.hostname}:{port}"
    return out


@app.get("/api/qr.svg")
async def qr(data: str):
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=6, dark="#2b1d12", light=None, border=1)
    return Response(buf.getvalue(), media_type="image/svg+xml")


# ---------------------------------------------------------------------- demo controls (presenter only)
class ClockIn(BaseModel):
    hhmm: str | None = None
    speed: float | None = None


@app.post("/api/demo/clock")
async def demo_clock(c: ClockIn):
    await engine.demo_clock(c.hhmm, c.speed)
    return engine.clock.to_dict()


class ResetIn(BaseModel):
    hhmm: str = "6:30"
    speed: float = 1.0


@app.post("/api/demo/reset")
async def demo_reset(r: ResetIn | None = None):
    r = r or ResetIn()
    await engine.demo_reset(r.hhmm, r.speed)
    return {"ok": True}


@app.post("/api/demo/replay")
async def demo_replay(speed: float = 240.0, start: str = "17:30"):
    await engine.demo_replay(speed, start)
    return {"ok": True}


@app.post("/api/demo/cold/{mode}")
async def demo_cold(mode: str):
    if mode not in ("on", "off", "auto"):
        raise HTTPException(400)
    engine.cold_mode = mode
    await engine.broadcast()
    return engine.cold_info()


@app.post("/api/demo/jump")
async def demo_jump(home: str = "margaret", after: float = 4.0, speed: float | None = None):
    """Jump to a few minutes past the person's learned deadline (whatever their real rhythm says)."""
    return {"hhmm": await engine.demo_jump(home, after, speed), **engine.clock.to_dict()}


@app.post("/api/demo/kettle")
async def demo_kettle(home: str = "margaret", appliance: str = "kettle"):
    """Ask the home's Kettle to simulate an appliance (only used when no real plug is attached)."""
    return {"ok": await engine.demo_device(home, {"type": "sim", "appliance": appliance})}


@app.post("/api/demo/outage")
async def demo_outage(home: str = "margaret", seconds: float = 30):
    return {"ok": await engine.demo_device(home, {"type": "outage", "seconds": seconds})}


@app.post("/api/demo/grid-alert")
async def demo_grid_alert():
    await engine.grid_alert_now()
    return {"ok": True}


class ShowIn(BaseModel):
    usual: str = "8:30"
    phones: dict[str, str] = {}
    call: bool = False


@app.post("/api/demo/show/setup")
async def demo_show_setup(s: ShowIn):
    """Presenter mode (python -m kettle show): no timers; each step happens when the presenter asks."""
    try:
        return await engine.show_setup("margaret", s.usual, s.phones, s.call)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/demo/show/{step}")
async def demo_show_step(step: str):
    """step: next | reset | ask_self | ask_neighbour | ask_family | tea"""
    try:
        return await engine.show_step(step)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/demo/show")
async def demo_show_state():
    return engine.show_state()


# ---------------------------------------------------------------------- phone app (same API as the Vercel site)
@app.get("/api/p/config")
async def phone_config():
    return {"mode": "local", "characters": cards.CHARACTERS, "relay": relay.status() if relay else None}


@app.get("/api/p/me")
async def phone_me(c: str):
    try:
        return cards.card(engine, c)
    except KeyError:
        raise HTTPException(404, "unknown character")


class ActIn(BaseModel):
    c: str
    action: str
    ref: dict | None = None


@app.post("/api/p/act")
async def phone_act(a: ActIn):
    r = await cards.act(engine, a.c, a.action, a.ref)
    await engine.broadcast()
    return r


# ---------------------------------------------------------------------- Twilio voice webhook
@app.post("/twilio/gather/{home_id}")
async def twilio_gather(home_id: str, Digits: str = Form("")):
    if Digits == "1":
        await engine.self_ok(home_id, "phone")
        say = "Thank you. We'll let your circle know you're fine. Have a lovely day."
    else:
        say = "Okay. If you're fine, press the glowing button on your Kettle."
    return Response(f'<Response><Say voice="{VOICE}">{say}</Say></Response>', media_type="text/xml")


# ---------------------------------------------------------------------- static
@app.get("/")
async def root():
    return RedirectResponse("/stage/")


@app.get("/circle/")
async def circle_redirect(m: str | None = None, join: str | None = None):
    """The old circle app; the redesigned phone app lives at /phone/ (and on the Vercel site)."""
    if join is not None or not m:
        return RedirectResponse("/circle/classic.html" + (f"?join={join}" if join is not None else ""))
    return RedirectResponse(f"/phone/?c={m}")


app.mount("/phone", StaticFiles(directory=WEB.parent / "site", html=True), name="phone")
for name in ("stage", "circle", "hub", "shared", "deck"):
    d = WEB / name
    d.mkdir(parents=True, exist_ok=True)
    app.mount(f"/{name}", StaticFiles(directory=d, html=True), name=name)
