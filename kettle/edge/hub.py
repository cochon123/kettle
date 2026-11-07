"""The Kettle edge hub: the small box (or Raspberry Pi) in the senior's home.

    .venv/bin/python -m kettle edge --plug sim                  # no hardware
    .venv/bin/python -m kettle edge --plug shelly:192.168.1.50  # real plug on the kettle

It
  1. reads the plug once a second, on the LAN only,
  2. runs the detector (kettle/detect.py) locally,
  3. sends *events only* to the cloud (store-and-forward if the internet drops),
  4. serves the kitchen display (web/hub) and a local-only live trace on :8701.

The raw readings exist only in this process's memory and on the local screen.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import contextlib
import json
import logging
import pathlib
import time

import websockets
import ipaddress

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from ..detect import Detector, DetectorConfig
from .plugs import make_plug
from .sim import Simulator

log = logging.getLogger("kettle.edge")
WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


class Hub:
    def __init__(self, home: str, plug_spec: str, cloud: str, key: str, kettle_s: float, sensing: str = "plug"):
        self.home, self.cloud, self.key = home, cloud.rstrip("/"), key
        self.sensing = sensing
        self.label = "kettle" if sensing == "plug" else "home"
        self.sim = Simulator(kettle_s=kettle_s)
        self.plug = make_plug(plug_spec, self.sim)
        cfg = DetectorConfig.for_plug("kettle") if sensing == "plug" else DetectorConfig(region="na")
        self.det = Detector(self.label, cfg)
        self.local: set = set()
        self.outq: collections.deque = collections.deque(maxlen=5000)   # store-and-forward
        self.cloud_ws = None
        self.cloud_ok = False
        self.outage_until = 0.0
        self.trace: collections.deque = collections.deque(maxlen=600)  # last ~10 min, local only
        self.ui: dict = {"checkin": None, "glow": None, "clock": None}
        self.plug_ok, self.plug_err = False, None
        self.events_sent = 0
        self.interval = 0.5 if not self.plug.real else 1.0

    # ------------------------------------------------------------------ local UI
    async def to_local(self, msg: dict) -> None:
        dead = []
        for ws in self.local:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.local.discard(ws)

    def status(self) -> dict:
        return {"type": "status", "home": self.home, "plug": self.plug.name, "plug_real": self.plug.real,
                "plug_ok": self.plug_ok, "plug_err": self.plug_err, "cloud_ok": self.cloud_ok,
                "queued": len(self.outq), "sent": self.events_sent, "outage": time.time() < self.outage_until,
                "ui": self.ui, "label": self.label}

    async def from_local(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "im_fine":
            self.ui["checkin"] = None
            await self.send_cloud({"type": "im_fine"})
            await self.to_local({"type": "checkin_end", "text": "Thank you. Your circle knows you're fine."})
        elif t == "pause":
            await self.send_cloud({"type": "pause", "hours": msg.get("hours")})
        elif t == "sim" and not self.plug.real:
            self.sim.start(msg.get("appliance", "kettle"))

    # ------------------------------------------------------------------ cloud link
    async def send_cloud(self, msg: dict) -> None:
        if msg.get("type") == "event":
            self.outq.append(msg)
            await self._flush()
            return
        if self.cloud_ws and self.cloud_ok:
            with contextlib.suppress(Exception):
                await self.cloud_ws.send(json.dumps(msg))

    async def _flush(self) -> None:
        while self.outq and self.cloud_ws and self.cloud_ok:
            msg = self.outq[0]
            try:
                await self.cloud_ws.send(json.dumps(msg))
            except Exception:
                return
            self.outq.popleft()
            self.events_sent += 1

    async def cloud_loop(self) -> None:
        url = f"{self.cloud}/ws/device/{self.home}?key={self.key}"
        backoff = 1.0
        while True:
            if time.time() < self.outage_until:
                await asyncio.sleep(0.5)
                continue
            try:
                async with websockets.connect(url, open_timeout=5, ping_interval=10) as ws:
                    self.cloud_ws, self.cloud_ok, backoff = ws, True, 1.0
                    await ws.send(json.dumps({"type": "hello", "info": {
                        "plug": self.plug.name, "real": self.plug.real, "channels": [self.label],
                        "sensing": "v0 kettle plug" if self.sensing == "plug" else "v1 whole-home meter",
                        "fw": "kettle-edge 0.1"}}))
                    await self._flush()
                    await self.to_local(self.status())
                    hb = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw in ws:
                            await self.on_cloud(json.loads(raw))
                            if time.time() < self.outage_until:
                                break
                    finally:
                        hb.cancel()
            except Exception as e:
                log.info("cloud link down: %s", e)
            self.cloud_ws, self.cloud_ok = None, False
            await self.to_local(self.status())
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15)

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(10)
            await ws.send(json.dumps({"type": "heartbeat", "queued": len(self.outq)}))

    async def on_cloud(self, msg: dict) -> None:
        t = msg.get("type")
        if t in ("checkin", "checkin_keep"):
            self.ui["checkin"] = msg.get("text")
            await self.to_local({"type": "checkin", "text": msg.get("text")})
        elif t == "checkin_end":
            self.ui["checkin"] = None
            await self.to_local({"type": "checkin_end", "text": msg.get("text", "")})
        elif t == "glow":
            self.ui["glow"] = {"from": msg.get("from"), "until": time.time() + 60}
            await self.to_local(msg)
        elif t == "clock":
            self.ui["clock"] = msg
            await self.to_local(msg)
        elif t == "sim":
            if not self.plug.real:
                self.sim.start(msg.get("appliance", "kettle"))
            else:
                await self.to_local({"type": "toast", "text": "Real plug attached: switch the kettle on!"})
        elif t == "outage":
            # Demo: behave like the house lost power. Drop the cloud link, blank the screen.
            self.outage_until = time.time() + float(msg.get("seconds", 30))
            await self.to_local({"type": "outage", "seconds": msg.get("seconds", 30)})
            if self.cloud_ws:
                await self.cloud_ws.close()

    # ------------------------------------------------------------------ sensing
    async def sense_loop(self) -> None:
        while True:
            t0 = time.time()
            try:
                w = await self.plug.read()
                if not self.plug_ok:
                    self.plug_ok, self.plug_err = True, None
                    await self.to_local(self.status())
            except Exception as e:
                if self.plug_ok or self.plug_err is None:
                    self.plug_ok, self.plug_err = False, str(e)[:100]
                    await self.to_local(self.status())
                await asyncio.sleep(2)
                continue
            self.trace.append((t0, w))
            if time.time() >= self.outage_until:   # in a (simulated) power cut the screen is dark
                await self.to_local({"type": "sample", "t": t0, "w": round(w, 1)})
            for ev in self.det.push(t0, w):
                d = ev.to_dict()
                await self.to_local({"type": "event", "event": d})
                await self.send_cloud({"type": "event", "event": d})
            await asyncio.sleep(max(0.05, self.interval - (time.time() - t0)))


def _is_lan(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def make_app(hub: Hub) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app):
        tasks = [asyncio.create_task(hub.sense_loop()), asyncio.create_task(hub.cloud_loop())]
        yield
        for t in tasks:
            t.cancel()
        await hub.plug.close()

    app = FastAPI(title="Kettle edge hub", lifespan=lifespan)

    @app.websocket("/ws/local")
    async def ws_local(ws: WebSocket):
        await ws.accept()
        hub.local.add(ws)
        await ws.send_json(hub.status())
        await ws.send_json({"type": "history", "points": [[round(t, 2), round(w, 1)] for t, w in hub.trace]})
        try:
            while True:
                await hub.from_local(json.loads(await ws.receive_text()))
        except (WebSocketDisconnect, json.JSONDecodeError):
            pass
        finally:
            hub.local.discard(ws)

    @app.post("/api/sim/{appliance}")
    async def sim(appliance: str):
        if hub.plug.real:
            return {"ok": False, "reason": "real plug attached"}
        return {"ok": True, "seconds": hub.sim.start(appliance)}

    @app.post("/api/push")
    async def push(body: dict, request: Request):
        """LAN-only: a sensor (ESP32 meter-pulse / CT clamp) pushes its latest reading here."""
        if not hasattr(hub.plug, "push"):
            return {"ok": False, "reason": "hub not started with --plug push"}
        host = request.client.host if request.client else ""
        if not _is_lan(host):
            return {"ok": False, "reason": "LAN only"}
        hub.plug.push(float(body["w"]), body.get("source", host))
        return {"ok": True}

    @app.post("/api/im_fine")
    async def im_fine(request: Request):
        """LAN-only: the physical "I'm fine" button on the sensor."""
        if not _is_lan(request.client.host if request.client else ""):
            return {"ok": False, "reason": "LAN only"}
        await hub.from_local({"type": "im_fine"})
        return {"ok": True}

    @app.get("/api/status")
    async def status():
        return hub.status()

    @app.get("/")
    async def root():
        return RedirectResponse("/hub/")

    for name in ("hub", "shared"):
        app.mount(f"/{name}", StaticFiles(directory=WEB / name, html=True), name=name)
    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn
    ap = argparse.ArgumentParser(prog="kettle edge")
    ap.add_argument("--home", default="margaret")
    ap.add_argument("--plug", default="sim", help="sim | shelly:<ip> | shelly1:<ip> | tasmota:<ip> | kasa:<ip>")
    ap.add_argument("--cloud", default="ws://127.0.0.1:8700")
    ap.add_argument("--key", default="demo-key")
    ap.add_argument("--port", type=int, default=8701)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--kettle-seconds", type=float, default=75.0, help="simulated boil length")
    ap.add_argument("--sensing", choices=["plug", "meter"], default="plug",
                    help="plug: a plug on the kettle (v0). meter: whole-home reading (v1), e.g. ESP32 on the meter LED")
    a = ap.parse_args(argv)
    hub = Hub(a.home, a.plug, a.cloud, a.key, a.kettle_seconds, a.sensing)
    uvicorn.run(make_app(hub), host=a.host, port=a.port, log_level="warning")
