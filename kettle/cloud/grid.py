"""Alberta context: live AESO grid state, live Environment Canada weather and alerts,
and the January 13 2024 replay built from real archived data.

Live sources (public, no key):
  AESO Current Supply Demand report  http://ets.aeso.ca/ets_web/ip/Market/Reports/CSDReportServlet
  ECCC city page weather (Calgary)    https://api.weather.gc.ca/collections/citypageweather-realtime/items/ab-52
  ECCC weather alerts (Calgary bbox)  https://api.weather.gc.ca/collections/weather-alerts/items
"""

from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import logging
import pathlib
import re
import time

import httpx

from ..clock import CALGARY

log = logging.getLogger("kettle.grid")
ROOT = pathlib.Path(__file__).resolve().parents[2]

CSD_URL = "http://ets.aeso.ca/ets_web/ip/Market/Reports/CSDReportServlet?contentType=html"
CITY_URL = "https://api.weather.gc.ca/collections/citypageweather-realtime/items/ab-52?f=json"
ALERTS_URL = ("https://api.weather.gc.ca/collections/weather-alerts/items?f=json"
              "&bbox=-114.32,50.84,-113.85,51.22&limit=20")

COLD_C = -25.0  # at or below this, cold mode switches on automatically


def parse_csd(text: str) -> dict:
    rows = re.findall(r"<TR[^>]*>(.*?)</TR>", text, re.S | re.I)
    kv: dict[str, str] = {}
    updated = None
    for r in rows:
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<T[DH][^>]*>(.*?)</T[DH]>", r, re.S | re.I)]
        cells = [c for c in cells if c]
        if len(cells) == 1 and cells[0].startswith("Last Update"):
            updated = cells[0].split(":", 1)[1].strip()
        if len(cells) == 2 and cells[0] not in kv:
            kv[cells[0]] = cells[1]

    def n(k: str) -> float | None:
        try:
            return float(kv[k].replace(",", ""))
        except (KeyError, ValueError):
            return None

    return {
        "source": "AESO Current Supply Demand (live)",
        "url": CSD_URL.split("?")[0],
        "updated": updated,
        "tng_mw": n("Alberta Total Net Generation"),
        "ail_mw": n("Alberta Internal Load (AIL)"),
        "interchange_mw": n("Net Actual Interchange"),
        "reserve_required_mw": n("Contingency Reserve Required"),
        "reserve_dispatched_mw": n("Dispatched Contingency Reserve (DCR)"),
    }


class Grid:
    """Holds the latest grid + weather picture, live or replayed."""

    def __init__(self) -> None:
        self.live: dict = {}
        self.weather: dict = {}
        self.alerts: list[dict] = []
        self.errors: dict[str, str] = {}
        self.replay = Replay.load()

    async def run(self) -> None:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "kettle-hackathon/0.1"}) as c:
            n = 0
            while True:
                await self._poll(c, "aeso", self._aeso)
                if n % 10 == 0:
                    await self._poll(c, "weather", self._weather)
                    await self._poll(c, "alerts", self._alerts)
                n += 1
                await asyncio.sleep(60)

    async def _poll(self, c: httpx.AsyncClient, name: str, fn) -> None:
        try:
            await fn(c)
            self.errors.pop(name, None)
        except Exception as e:  # offline at the venue is fine; we keep the last value
            self.errors[name] = str(e)[:120]
            log.info("%s poll failed: %s", name, e)

    async def _aeso(self, c: httpx.AsyncClient) -> None:
        r = await c.get(CSD_URL)
        self.live = parse_csd(r.text) | {"fetched": time.time()}

    async def _weather(self, c: httpx.AsyncClient) -> None:
        r = await c.get(CITY_URL)
        cc = r.json()["properties"]["currentConditions"]
        temp = cc["temperature"]["value"]["en"]
        chill = (cc.get("windChill") or {}).get("value", {}).get("en")
        if temp is None or temp > 0:
            chill = None   # wind chill is only defined at or below 0 °C (the live feed sometimes carries a stale value)
        self.weather = {
            "source": "Environment and Climate Change Canada (live)",
            "station": cc.get("station", {}).get("value", {}).get("en", "Calgary"),
            "temp_c": temp,
            "wind_chill": chill,
            "condition": (cc.get("condition") or {}).get("en"),
            "observed": cc["timestamp"]["en"], "fetched": time.time(),
        }

    async def _alerts(self, c: httpx.AsyncClient) -> None:
        r = await c.get(ALERTS_URL)
        out = []
        for f in r.json().get("features", []):
            p = f.get("properties", {})
            out.append({"headline": p.get("alert_name_en") or p.get("headline_en") or p.get("alert_short_name_en"),
                        "type": p.get("alert_type"), "expires": p.get("expiration_datetime"),
                        "area": p.get("feature_name_en")})
        self.alerts = out

    def cold_alert(self) -> dict | None:
        for a in self.alerts:
            h = (a.get("headline") or "").lower()
            if "cold" in h:
                return a
        return None


class Replay:
    """The real January 13 2024 day, keyed to the demo clock."""

    def __init__(self, data: dict | None):
        self.data = data
        self.active = False
        self.fired: list[int] = []

    @classmethod
    def load(cls) -> "Replay":
        p = ROOT / "data/jan13_2024.json"
        return cls(json.loads(p.read_text()) if p.exists() else None)

    @staticmethod
    def _local(iso: str) -> float:
        return dt.datetime.fromisoformat(iso).replace(tzinfo=CALGARY).timestamp()

    def at(self, t: float) -> dict:
        d = self.data
        if not d:
            return {}
        hour = None
        for h in d["hourly"]:
            if self._local(h["hour_start"]) <= t:
                hour = h
        wx = None
        for w in d["weather"]:
            if self._local(w["t"]) <= t:
                wx = w
        smp = None
        for s in d["smp"]:
            if self._local(s["t"]) <= t:
                smp = s
        return {
            "source": "AESO + ECCC archived data (replay)",
            "hour": hour, "smp": smp, "weather": wx,
            "series": {
                "hourly": [{"t": self._local(h["hour_start"]), "price": h["pool_price"], "ail": h["ail_mw"]}
                           for h in d["hourly"] if h["hour_start"].startswith("2024-01-13")],
                "temp": [{"t": self._local(w["t"]), "c": w["temp_c"]}
                         for w in d["weather"] if w["t"].startswith("2024-01-13")],
            },
            "timeline": [dict(x, ts=self._local(x["t"])) for x in d["timeline"]],
            "facts": d["facts"], "sources": d["sources"],
        }

    def due(self, t: float) -> list[dict]:
        """Timeline items whose time has just passed (each fires once)."""
        if not (self.active and self.data):
            return []
        out = []
        for i, x in enumerate(self.data["timeline"]):
            if i not in self.fired and self._local(x["t"]) <= t:
                self.fired.append(i)
                out.append(dict(x, ts=self._local(x["t"])))
        return out
