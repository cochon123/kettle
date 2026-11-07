"""Appliance signature library.

A signature is three soft bands: step size (W), on-duration (s) and flatness
(coefficient of variation of the power while on). A resistive kettle is a big,
very flat step lasting a few minutes; a microwave flickers (magnetron cycling,
turntable); a TV is small and long; a furnace blower is medium and runs for
5-30 minutes at a time, more often the colder it gets.

Bands are deliberately wide and explainable. They were tuned against labelled
REFIT appliance channels (UK) and published North American appliance ratings
(120 V kettles are limited to about 1500 W).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

# Labels that count as "a person did something".
HUMAN_LABELS = {"kettle", "microwave", "toaster", "tv", "cooking", "hair_dryer", "human_unknown"}
# Resistive loads whose *repeated* same-size cycles within minutes mean a thermostat
# (oven, tumble dryer, heater, immersion), not a person: the detector relabels those
# repeats "cycling" (not in HUMAN_LABELS). The first cycle of a session keeps its label.
REPEAT_SENSITIVE = {"kettle", "toaster", "human_unknown"}


def _soft(x: float, lo: float, hi: float, soft: float = 0.15) -> float:
    """1 inside [lo, hi], decaying smoothly (in log space) outside."""
    if x <= 0:
        return 0.0
    if lo <= x <= hi:
        return 1.0
    edge = lo if x < lo else hi
    d = abs(math.log(x / edge)) / max(soft, 1e-6)
    return math.exp(-d * d)


@dataclass(frozen=True)
class Signature:
    label: str
    dp: tuple[float, float]
    dur: tuple[float, float] | None = None
    cv_max: float | None = None
    cv_min: float | None = None
    prior: float = 1.0
    dp_soft: float = 0.15

    def score(self, dp: float, duration_s: float | None, cv: float | None) -> float:
        s = self.prior * _soft(dp, *self.dp, soft=self.dp_soft)
        if duration_s is not None and self.dur is not None:
            s *= _soft(max(duration_s, 1.0), *self.dur, soft=0.35)
        if cv is not None:
            if self.cv_max is not None and cv > self.cv_max:
                s *= math.exp(-((cv - self.cv_max) / max(self.cv_max, 0.01)) ** 2)
            if self.cv_min is not None and cv < self.cv_min:
                s *= math.exp(-((self.cv_min - cv) / max(self.cv_min, 0.01)) ** 2)
        return s


UK = [
    Signature("kettle", (1800, 3300), (40, 420), cv_max=0.08, prior=1.0),
    Signature("microwave", (700, 1700), (20, 1200), cv_min=0.05, prior=0.8),
    Signature("toaster", (750, 1600), (60, 420), cv_max=0.08, prior=0.5),
    Signature("tv", (40, 350), (600, 6 * 3600), prior=0.4),
    Signature("fridge", (50, 250), (300, 3600), prior=0.6),
    Signature("human_unknown", (500, 6000), (10, 4 * 3600), prior=0.15),
]

NA = [
    Signature("kettle", (950, 1650), (40, 480), cv_max=0.06, prior=1.0),
    Signature("microwave", (900, 1800), (20, 1200), cv_min=0.05, prior=0.8),
    Signature("toaster", (700, 1500), (60, 420), cv_max=0.06, prior=0.4),
    Signature("tv", (40, 350), (600, 6 * 3600), prior=0.4),
    Signature("furnace_blower", (250, 900), (240, 2400), cv_max=0.10, prior=0.7),
    Signature("fridge", (50, 250), (300, 3600), prior=0.6),
    Signature("human_unknown", (500, 6000), (10, 4 * 3600), prior=0.15),
]


def calibrated(sig: Signature, step_w: float, tol: float = 0.10) -> Signature:
    """A copy of ``sig`` whose power band is centred on one measured step (setup calibration)."""
    return replace(sig, dp=(step_w * (1 - tol), step_w * (1 + tol)), dp_soft=0.05)


def library_for(region: str, channel_kind: str) -> list[Signature]:
    """Signature set for a channel. A plug channel already knows its appliance."""
    if channel_kind.startswith("plug:"):
        label = channel_kind.split(":", 1)[1]
        return [Signature(label, (300, 4000) if label in ("kettle", "microwave", "toaster") else (15, 4000))]
    return list(UK if region == "uk" else NA)
