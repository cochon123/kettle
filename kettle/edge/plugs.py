"""Power sources for the edge hub: real smart plugs over the LAN, or the simulator.

All drivers speak to the plug *locally* (no vendor cloud) and return watts.

  sim                       built-in appliance simulator (no hardware)
  shelly:<ip>               Shelly Plus / Gen2 / Gen3 plugs   GET /rpc/Switch.GetStatus?id=0 -> apower
  shelly1:<ip>              Shelly Gen1 plugs (Plug US, Plug S) GET /meter/0 -> power
  tasmota:<ip>              any Tasmota-flashed energy plug    GET /cm?cmnd=Status%2010 -> ENERGY.Power
  kasa:<ip>                 TP-Link Kasa KP115 / HS110 / EP25  (pip install python-kasa)
  push                      a sensor pushes readings to the hub: POST /api/push {"w": 1520.0}
                            (the ESP32 meter-pulse / CT-clamp firmware in firmware/kettle-sense)
"""

from __future__ import annotations

import time

import httpx

from .sim import Simulator


class Plug:
    name = "plug"
    real = True

    async def read(self) -> float:  # watts
        raise NotImplementedError

    async def close(self) -> None:
        pass


class SimPlug(Plug):
    name, real = "simulator", False

    def __init__(self, sim: Simulator):
        self.sim = sim

    async def read(self) -> float:
        return self.sim.sample()


class HttpPlug(Plug):
    def __init__(self, host: str):
        self.host = host
        self.client = httpx.AsyncClient(timeout=2.0)

    async def close(self) -> None:
        await self.client.aclose()


class ShellyGen2(HttpPlug):
    name = "Shelly Gen2+"

    async def read(self) -> float:
        r = await self.client.get(f"http://{self.host}/rpc/Switch.GetStatus", params={"id": 0})
        return float(r.json()["apower"])


class ShellyGen1(HttpPlug):
    name = "Shelly Gen1"

    async def read(self) -> float:
        r = await self.client.get(f"http://{self.host}/meter/0")
        return float(r.json()["power"])


class Tasmota(HttpPlug):
    name = "Tasmota"

    async def read(self) -> float:
        r = await self.client.get(f"http://{self.host}/cm", params={"cmnd": "Status 10"})
        return float(r.json()["StatusSNS"]["ENERGY"]["Power"])


class Kasa(Plug):
    name = "TP-Link Kasa"

    def __init__(self, host: str):
        self.host = host
        self.dev = None

    async def read(self) -> float:
        from kasa import Discover, Module  # optional dependency: pip install python-kasa
        if self.dev is None:
            self.dev = await Discover.discover_single(self.host)
        await self.dev.update()
        return float(self.dev.modules[Module.Energy].current_consumption or 0.0)


class PushPlug(Plug):
    """Readings pushed over the LAN by a sensor (sample-and-hold between pushes)."""
    name = "pushed sensor"

    def __init__(self, stale_s: float = 30.0):
        self.w: float | None = None
        self.t = 0.0
        self.stale_s = stale_s
        self.source = ""

    def push(self, w: float, source: str = "") -> None:
        self.w, self.t, self.source = float(w), time.time(), source

    async def read(self) -> float:
        if self.w is None or time.time() - self.t > self.stale_s:
            raise RuntimeError("no reading from sensor in the last 30 s")
        return self.w


def make_plug(spec: str, sim: Simulator) -> Plug:
    kind, _, host = spec.partition(":")
    kinds = {"sim": None, "push": None, "shelly": ShellyGen2, "shelly1": ShellyGen1, "tasmota": Tasmota, "kasa": Kasa}
    if kind not in kinds:
        raise SystemExit(f"unknown plug '{spec}'. Use one of: sim, push, shelly:<ip>, shelly1:<ip>, tasmota:<ip>, kasa:<ip>")
    if kind == "sim":
        return SimPlug(sim)
    if kind == "push":
        return PushPlug()
    return kinds[kind](host)
