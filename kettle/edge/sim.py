"""Appliance simulator for running Kettle without hardware.

Produces a realistic *power waveform*, which then goes through the real
detector, exactly like a smart plug's readings would. Nothing downstream
knows it is simulated except the label on the screen.

Shapes follow North American 120 V appliances:
  kettle     1500 W resistive element; power sags ~2% as the element heats; auto-off at the boil
  microwave  ~1450 W with magnetron ripple
  toaster    ~900 W, flat, 2.5 min
If a REFIT kettle trace is available (data/refit/kettle_boil_trace.json), the
kettle *shape* (relative ripple and sag) is taken from that real UK boil and
rescaled to 1500 W.
"""

from __future__ import annotations

import json
import math
import pathlib
import random
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Simulator:
    def __init__(self, kettle_s: float = 75.0, standby_w: float = 0.6):
        self.kettle_s = kettle_s
        self.standby_w = standby_w
        self.active: list[dict] = []
        self.shape = self._load_shape()

    @staticmethod
    def _load_shape() -> list[float] | None:
        p = ROOT / "data/refit/kettle_boil_trace.json"
        try:
            d = json.loads(p.read_text())
            pts = d.get("kettle_iam") or d.get("trace") or d.get("points") or d
            ws = [float(w) for _, w in pts]
            on = [w for w in ws if w > 0.5 * max(ws)]
            peak = max(on)
            return [w / peak for w in on] if len(on) > 3 else None
        except Exception:
            return None

    def start(self, appliance: str = "kettle") -> float:
        dur = {"kettle": self.kettle_s, "microwave": 90.0, "toaster": 150.0}.get(appliance, 60.0)
        self.active.append({"kind": appliance, "t0": time.time(), "dur": dur})
        return dur

    @property
    def busy(self) -> bool:
        return bool(self.active)

    def _kettle(self, x: float) -> float:
        if self.shape:
            i = min(int(x * len(self.shape)), len(self.shape) - 1)
            rel = self.shape[i]
        else:
            rel = 1.0 - 0.02 * x
        return 1500.0 * rel + random.gauss(0, 3)

    def sample(self) -> float:
        now = time.time()
        w = self.standby_w + random.gauss(0, 0.05)
        keep = []
        for a in self.active:
            x = (now - a["t0"]) / a["dur"]
            if x >= 1.0:
                continue
            keep.append(a)
            if a["kind"] == "kettle":
                w += self._kettle(x)
            elif a["kind"] == "microwave":
                w += 1450 * (0.92 + 0.08 * math.sin(now * 2 * math.pi / 2.2)) + random.gauss(0, 25)
            elif a["kind"] == "toaster":
                w += 900 + random.gauss(0, 4)
        self.active = keep
        return max(w, 0.0)
