"""Streaming appliance-event detector.

This is the code that runs *inside the home* (on the edge hub). It turns a raw
power stream (watts over time) into a small number of discrete appliance events.
Only those events ever leave the house; the raw samples never do.

Algorithm (a streaming variant of Hart's steady-state edge detection):

1. Track the current steady power level of the channel.
2. When a sample departs from that level by more than a tolerance, open a
   *candidate* level. If the candidate persists (enough samples AND enough
   seconds), commit an *edge* with  dP = candidate_level - previous_level.
   Short spikes (motor inrush, sensor glitches) never persist, so they are ignored.
3. Positive edges open an appliance *cycle*. A later negative edge whose
   magnitude matches an open cycle closes it, giving duration and flatness.
4. Each cycle is scored against a small signature library (power band,
   duration band, flatness) to label it: kettle, microwave, toaster, tv,
   furnace_blower, fridge, ...

It is deliberately simple, explainable and cheap: it runs on a Raspberry Pi,
and the same file is used for the live demo and for the REFIT evaluation, so
the numbers we quote are the numbers of the code we ship.

Works with any sample rate (1 Hz smart plug, 8 s REFIT, 10 s meter pulse).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Callable, Iterable, Iterator

from .signatures import Signature, library_for, calibrated, HUMAN_LABELS, REPEAT_SENSITIVE


@dataclass
class DetectorConfig:
    min_step_w: float = 150.0          # smallest edge we care about
    rel_tol: float = 0.04              # steady-state tolerance as fraction of level
    abs_tol_w: float = 40.0            # ... and absolute floor
    confirm_samples: int = 2           # samples a new level must persist
    confirm_s: float = 2.0             # seconds a new level must persist
    max_open_s: float = 6 * 3600       # forget unmatched ON edges after this
    match_rel: float = 0.25            # ON/OFF magnitude match tolerance (relative)
    match_abs_w: float = 150.0         # ... absolute
    max_gap_s: float = 120.0           # data gap that resets the detector
    region: str = "na"                 # "na" (120 V appliances) or "uk" (230 V)
    channel_kind: str = "aggregate"    # "aggregate" (whole home) or "plug:<label>"
    # Thermostat cycling (oven, tumble dryer, heaters): a cycle of the same size that ended
    # less than repeat_window_s before this one started is relabelled "cycling" (not human)
    # instead of kettle / toaster / human_unknown. 0 disables (plugs know their appliance).
    repeat_window_s: float = 600.0
    repeat_rel: float = 0.15
    # Optional per-home calibration: the kettle's step size measured once at setup
    # ("boil the kettle now"). Narrows the kettle band to kettle_w * (1 +- kettle_tol).
    kettle_w: float | None = None
    kettle_tol: float = 0.10
    # A cycle counts as human evidence only if its human_score (share of signature evidence
    # on human labels x best human match) reaches this. On a whole-home channel, TV-sized and
    # "unknown" big loads are mostly fridges, pumps and heaters (tuned on REFIT houses 1-9).
    min_human_score: float = 0.5

    @classmethod
    def for_plug(cls, label: str = "kettle", region: str = "na") -> "DetectorConfig":
        # A plug sees one appliance, so we can afford a low threshold and fast confirm.
        return cls(min_step_w=40.0, abs_tol_w=25.0, confirm_samples=2, confirm_s=1.5,
                   region=region, channel_kind=f"plug:{label}", repeat_window_s=0.0,
                   min_human_score=0.0)

    @classmethod
    def for_refit(cls) -> "DetectorConfig":
        # REFIT aggregate: 8 s samples, UK 230 V appliances.
        return cls(min_step_w=150.0, confirm_samples=1, confirm_s=0.0, region="uk",
                   max_gap_s=300.0)


@dataclass
class Event:
    kind: str                 # "on" (provisional, at the rising edge) | "cycle" (confirmed, at the falling edge)
    channel: str
    t: float                  # unix seconds of the edge (on-edge for "on", off-edge for "cycle")
    dp_w: float               # step size in watts
    label: str
    confidence: float
    human: bool               # does this count as a sign of a person being active?
    t_on: float | None = None
    duration_s: float | None = None
    flatness_cv: float | None = None
    cycle_id: int | None = None
    alternatives: dict[str, float] = field(default_factory=dict)
    human_score: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items() if v is not None}


@dataclass
class _Cycle:
    id: int
    t_on: float
    dp: float
    base: float
    n: int = 0
    s1: float = 0.0
    s2: float = 0.0
    on_label: str = "unknown"

    def add(self, delta: float) -> None:
        self.n += 1
        self.s1 += delta
        self.s2 += delta * delta

    def cv(self) -> float:
        if self.n < 2:
            return 0.0
        mean = self.s1 / self.n
        var = max(0.0, self.s2 / self.n - mean * mean)
        return math.sqrt(var) / max(abs(mean), 1.0)


class Detector:
    """Feed samples with :meth:`push`; it returns any events those samples completed."""

    def __init__(self, channel: str = "home", config: DetectorConfig | None = None):
        self.channel = channel
        self.cfg = config or DetectorConfig()
        self.sigs: list[Signature] = library_for(self.cfg.region, self.cfg.channel_kind)
        if self.cfg.kettle_w and not self.cfg.channel_kind.startswith("plug:"):
            self.sigs = [calibrated(s, self.cfg.kettle_w, self.cfg.kettle_tol) if s.label == "kettle" else s
                         for s in self.sigs]
        self.recent: deque[tuple[float, float]] = deque()   # (t_off, dp) of recently closed cycles
        self.level: float | None = None
        self.cand: list[tuple[float, float]] = []
        self.open: list[_Cycle] = []
        self.last_t: float | None = None
        self._next_id = 1

    # ------------------------------------------------------------------ helpers
    def _tol(self, level: float) -> float:
        return max(self.cfg.abs_tol_w, self.cfg.rel_tol * abs(level))

    def reset(self) -> None:
        self.level = None
        self.cand.clear()
        self.open.clear()
        self.recent.clear()

    def _scores(self, dp: float, duration_s: float | None, cv: float | None) -> dict[str, float]:
        scores = {s.label: s.score(dp, duration_s, cv) for s in self.sigs}
        return {k: v for k, v in scores.items() if v > 0.02}

    def human_score(self, dp: float, duration_s: float | None, cv: float | None) -> float:
        """How sure we are this was a person: (share of evidence on human labels) x (best human match)."""
        scores = self._scores(dp, duration_s, cv)
        hum = [v for k, v in scores.items() if k in HUMAN_LABELS]
        return (sum(hum) / sum(scores.values())) * max(hum) if hum else 0.0

    def _is_human(self, label: str, hs: float) -> bool:
        return label in HUMAN_LABELS and hs >= self.cfg.min_human_score

    def classify(self, dp: float, duration_s: float | None, cv: float | None) -> tuple[str, float, dict[str, float]]:
        scores = self._scores(dp, duration_s, cv)
        if not scores:
            return "unknown", 0.0, {}
        best = max(scores, key=scores.get)
        total = sum(scores.values())
        conf = scores[best] * (scores[best] / total)
        alts = {k: round(v, 3) for k, v in sorted(scores.items(), key=lambda kv: -kv[1])[:3]}
        return best, conf, alts

    # ------------------------------------------------------------------ main loop
    def push(self, t: float, watts: float) -> list[Event]:
        out: list[Event] = []
        if watts is None or (isinstance(watts, float) and math.isnan(watts)):
            return out
        if self.last_t is not None and t - self.last_t > self.cfg.max_gap_s:
            self.reset()
        self.last_t = t
        self._expire(t)

        if self.level is None:
            self.level = watts
            return out

        if not self.cand:
            if abs(watts - self.level) <= self._tol(self.level):
                # steady: track slow drift, and record the sample for flatness stats
                self.level += 0.1 * (watts - self.level)
                self._feed(watts)
            else:
                self.cand = [(t, watts)]
        else:
            cmean = sum(w for _, w in self.cand) / len(self.cand)
            if abs(watts - cmean) <= self._tol(cmean):
                self.cand.append((t, watts))
            elif abs(watts - self.level) <= self._tol(self.level):
                # it was a spike / flicker: back to the old level
                for _, w in self.cand:
                    self._feed(w)
                self._feed(watts)
                self.cand = []
            else:
                for _, w in self.cand:
                    self._feed(w)
                self.cand = [(t, watts)]  # a different new level; restart candidate

        if self.cand:
            t0 = self.cand[0][0]
            if len(self.cand) >= self.cfg.confirm_samples and (t - t0) >= self.cfg.confirm_s:
                new_level = sum(w for _, w in self.cand) / len(self.cand)
                dp = new_level - self.level
                if abs(dp) >= self.cfg.min_step_w:
                    out.extend(self._edge(t0, dp, self.level))
                self.level = new_level
                for _, w in self.cand:
                    self._feed(w)
                self.cand = []
        return out

    def _feed(self, watts: float) -> None:
        for c in self.open:
            c.add(watts - c.base)

    def _expire(self, t: float) -> None:
        self.open = [c for c in self.open if t - c.t_on <= self.cfg.max_open_s]

    def _shift_bases(self, dp: float) -> None:
        # Another appliance switched while these cycles were open: move their reference
        # level with it, so their flatness only measures their *own* power variation.
        for c in self.open:
            c.base += dp

    def _edge(self, t: float, dp: float, base: float) -> list[Event]:
        if dp > 0:
            self._shift_bases(dp)
            label, conf, alts = self.classify(dp, None, None)
            hs = self.human_score(dp, None, None)
            cyc = _Cycle(id=self._next_id, t_on=t, dp=dp, base=base, on_label=label)
            self._next_id += 1
            self.open.append(cyc)
            return [Event("on", self.channel, t, dp, label, conf, self._is_human(label, hs),
                          t_on=t, cycle_id=cyc.id, alternatives=alts, human_score=hs)]
        mag = -dp
        best, best_err = None, None
        for c in reversed(self.open):
            err = abs(c.dp - mag)
            if err <= max(self.cfg.match_abs_w, self.cfg.match_rel * c.dp):
                if best is None or err < best_err:
                    best, best_err = c, err
        if best is None:
            self._shift_bases(dp)
            return []
        self.open.remove(best)
        self._shift_bases(dp + best.dp)  # residual of an imperfect match belongs to the others
        dur = t - best.t_on
        cv = best.cv()
        label, conf, alts = self.classify(best.dp, dur, cv)
        if self.cfg.repeat_window_s > 0:
            w = self.cfg.repeat_window_s
            while self.recent and self.recent[0][0] < t - 2 * w - dur:
                self.recent.popleft()
            repeated = any(best.t_on - w <= t_off <= best.t_on and abs(d - best.dp) <= self.cfg.repeat_rel * best.dp
                           for t_off, d in self.recent)
            self.recent.append((t, best.dp))
            if repeated and label in REPEAT_SENSITIVE:
                alts = {"cycling": round(conf, 3), **alts}
                label = "cycling"
        hs = self.human_score(best.dp, dur, cv)
        return [Event("cycle", self.channel, t, best.dp, label, conf, self._is_human(label, hs),
                      t_on=best.t_on, duration_s=dur, flatness_cv=cv, cycle_id=best.id,
                      alternatives=alts, human_score=hs)]


def detect_series(samples: Iterable[tuple[float, float]], channel: str = "home",
                  config: DetectorConfig | None = None) -> Iterator[Event]:
    """Offline convenience wrapper: run the streaming detector over a whole series."""
    det = Detector(channel, config)
    for t, w in samples:
        yield from det.push(t, w)
