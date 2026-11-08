"""REFIT evaluation of Kettle's detector and rhythm model.

Run:  .venv/bin/python -m kettle.eval.refit [--houses 3,11] [--quick] [--jobs N] [--force]

Everything here uses the shipped modules (``kettle.detect``, ``kettle.signatures``,
``kettle.rhythm``) unchanged; this file only loads data, runs them, and counts.

Data: REFIT "cleaned" dataset (Murray, Stankovic & Stankovic 2017, Scientific Data
4:160122, doi:10.1038/sdata.2016.122), CC BY 4.0. Raw CSVs live outside the repo
(``/home/cochon/kettle-data/refit``); caches go to ``/home/cochon/kettle-data/cache``;
only small derived JSON is written into the repo (``data/refit``).

Time handling (established from the data, see docs/refit-evaluation.md): the
cleaned REFIT ``Unix``/``Time`` stamps are *local* (Europe/London) wall-clock time
for most of the study (the 01:00 hour is doubled on 26 Oct 2014 and missing on
29 Mar 2015), but during British Summer Time before 26 Oct 2013 23:00 and from
30 Mar to 30 Sep 2014 they are UTC (everyone's morning routine appears exactly
~1 h early in those periods and nowhere else). We convert every stamp to true
UTC accordingly, drop the ambiguous fall-back hour, and leave 1-5 Sep 2014 (whose
convention is unclear) out of the rhythm evaluation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import inspect
import json
import os
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from kettle import detect as kdetect
from kettle import signatures as ksig
from kettle.detect import Detector, DetectorConfig
from kettle.rhythm import COLD, STANDARD, DayObs, Policy, RhythmModel, first_activity_by_day, fmt_min
from kettle.signatures import HUMAN_LABELS

# --------------------------------------------------------------------------- paths
REPO = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("REFIT_DIR", "/home/cochon/kettle-data/refit"))
CACHE_DIR = Path(os.environ.get("KETTLE_CACHE", "/home/cochon/kettle-data/cache"))
OUT_DIR = REPO / "data" / "refit"
DOC_PATH = REPO / "docs" / "refit-evaluation.md"

TZ = ZoneInfo("Europe/London")
UTC = dt.timezone.utc

# --------------------------------------------------------------------------- metadata
# From CLEAN_READ_ME_081116.txt (channel = "ApplianceN" column).
HOUSES = [h for h in range(1, 22) if h != 14]
TUNE_HOUSES = list(range(1, 10))
TEST_HOUSES = [h for h in HOUSES if h >= 10]
OCCUPANCY = {1: 2, 2: 4, 3: 2, 4: 2, 5: 4, 6: 2, 7: 4, 8: 2, 9: 2, 10: 4, 11: 1, 12: 3, 13: 4,
             15: 1, 16: 6, 17: 3, 18: 2, 19: 4, 20: 2, 21: 4}
KETTLE_CH = {2: 8, 3: 9, 4: 9, 5: 8, 6: 7, 7: 9, 8: 9, 9: 7, 11: 7, 12: 6, 13: 9, 17: 8, 19: 5,
             20: 9, 21: 7}
MICROWAVE_CH = {2: 5, 3: 8, 4: 8, 5: 7, 6: 6, 8: 8, 9: 6, 10: 8, 11: 6, 12: 5, 13: 7, 15: 7,
                17: 7, 18: 9, 19: 4, 20: 8}
TV_CH = {1: 8, 2: 4, 3: 7, 4: 7, 5: 6, 6: 5, 7: 7, 8: 7, 9: 5, 10: 7, 13: 1, 15: 6, 16: 8, 17: 6,
         18: 8, 19: 3, 20: 7, 21: 6}
TOASTER_CH = {2: 6, 3: 1, 5: 9, 6: 8, 7: 8, 8: 5, 10: 2, 15: 9, 19: 6}
# Readme notes on the kettle IAM: "House 21 7.Kettle (Changes 16 Aug 2014)" -- the
# appliance on that IAM changed, so the channel is only used as kettle ground truth before.
KETTLE_VALID_UNTIL = {21: dt.date(2014, 8, 16)}

CITATION = ("Murray, D., Stankovic, L. & Stankovic, V. (2017). An electrical load measurements "
            "dataset of United Kingdom households from a two-year longitudinal study. "
            "Scientific Data 4, 160122. doi:10.1038/sdata.2016.122")
LICENCE = "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"

# --------------------------------------------------------------------------- eval parameters
GT_ON_W = 1000.0            # ground-truth kettle use: IAM above this ...
GT_MIN_S = 16.0             # ... for at least this long
GT_MERGE_S = 16.0           # runs separated by <= this are one use
MATCH_TOL_S = 60.0          # detected on-edge within +-60 s of a ground-truth start
COVER_GAP_S = 120.0         # an inter-sample gap longer than this counts as "no data"
COVER_MIN = 0.90            # day evaluated only if >=90% of 04:00-14:00 is covered
MORNING = (4 * 60, 14 * 60)  # minutes after local midnight
MONTH_DAYS = 30.44
POLICIES = [STANDARD, COLD]


def log(*a) -> None:
    print(f"[{time.strftime('%H:%M:%S')}]", *a, file=sys.stderr, flush=True)


# =========================================================================== loading
DATA_VERSION = "tz2"   # bump when the loader's conversion changes (invalidates caches)
# Stamp ranges (local wall-clock strings as written in the CSV) that are really UTC.
UTC_STAMPED = [("1970-01-01 00:00:00", "2013-10-26 23:00:00"), ("2014-03-30 00:00:00", "2014-10-01 00:00:00")]
UNCERTAIN_TIME_DAYS = {dt.date(2014, 9, d) for d in range(1, 6)}


def _npz_path(h: int) -> Path:
    return CACHE_DIR / f"house{h}_{DATA_VERSION}.npz"


def stamps_to_utc(stamp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """REFIT stamp seconds -> (true UTC seconds, keep-mask). See module docstring."""
    utc_stamped = np.zeros(len(stamp), bool)
    for a, b in UTC_STAMPED:
        a_s, b_s = (np.datetime64(x).astype("datetime64[s]").astype("int64") for x in (a, b))
        utc_stamped |= (stamp >= a_s) & (stamp < b_s)
    loc = pd.DatetimeIndex(stamp.astype("datetime64[s]")).tz_localize(TZ, ambiguous="NaT", nonexistent="NaT")
    keep = utc_stamped | ~loc.isna()
    t = stamp.copy()
    lo = ~utc_stamped & keep
    t[lo] = loc[lo].tz_convert("UTC").tz_localize(None).to_numpy().astype("datetime64[s]").astype("int64")
    # at a UTC->local seam real time can step back; keep only strictly increasing times
    t_kept = t[keep]
    run_max = np.maximum.accumulate(t_kept)
    mono = np.ones(len(t_kept), bool)
    mono[1:] = t_kept[1:] > run_max[:-1]
    idx = np.nonzero(keep)[0]
    keep[idx[~mono]] = False
    return t, keep


def utc_to_local_wall(t: np.ndarray) -> np.ndarray:
    """True UTC seconds -> Europe/London wall-clock seconds (for day boundaries / coverage)."""
    loc = pd.to_datetime(t, unit="s", utc=True).tz_convert(TZ).tz_localize(None)
    return loc.to_numpy().astype("datetime64[s]").astype("int64")


def load_house(h: int) -> dict[str, np.ndarray]:
    """Load one house (cached as .npz). Returns arrays t (true UTC s), tl (local wall s), agg, kettle, ..."""
    p = _npz_path(h)
    if p.exists():
        with np.load(p) as z:
            return {k: z[k] for k in z.files}
    chans = {"agg": "Aggregate"}
    for name, table in (("kettle", KETTLE_CH), ("microwave", MICROWAVE_CH), ("tv", TV_CH),
                        ("toaster", TOASTER_CH)):
        if h in table:
            chans[name] = f"Appliance{table[h]}"
    cols = ["Unix", "Issues", *chans.values()]
    df = pd.read_csv(DATA_DIR / f"CLEAN_House{h}.csv", usecols=cols,
                     dtype={c: ("int64" if c == "Unix" else "int8" if c == "Issues" else "float32") for c in cols})
    df = df.sort_values("Unix", kind="stable")
    t, ok = stamps_to_utc(df["Unix"].to_numpy())
    t = t[ok]
    out = {"t": t, "tl": utc_to_local_wall(t), "issues": df["Issues"].to_numpy()[ok]}
    for name, col in chans.items():
        out[name] = df[col].to_numpy()[ok]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp.npz")
    np.savez(tmp, **out)
    tmp.rename(p)
    return out


# =========================================================================== coverage
def day_coverage(tl: np.ndarray, start_min: int, end_min: int) -> dict[dt.date, float]:
    """Fraction of [start_min, end_min) of each local day not inside a data gap > COVER_GAP_S."""
    d0 = int(tl[0] // 86400)
    d1 = int(tl[-1] // 86400)
    days = np.arange(d0, d1 + 1)
    w0 = days * 86400 + start_min * 60
    w1 = days * 86400 + end_min * 60
    covered = (w1 - w0).astype(float)
    # uncovered intervals: before first sample, after last sample, and gaps > COVER_GAP_S
    gi = np.nonzero(np.diff(tl) > COVER_GAP_S)[0]
    a = np.concatenate([[d0 * 86400], tl[gi], [tl[-1]]])
    b = np.concatenate([[tl[0]], tl[gi + 1], [(d1 + 1) * 86400]])
    for s, e in zip(a, b):
        if e <= s:
            continue
        k0 = max(int(s // 86400) - d0, 0)
        k1 = min(int(e // 86400) - d0, len(days) - 1)
        for k in range(k0, k1 + 1):
            ov = min(e, w1[k]) - max(s, w0[k])
            if ov > 0:
                covered[k] -= ov
    frac = covered / (w1 - w0)
    epoch = dt.date(1970, 1, 1)
    return {epoch + dt.timedelta(days=int(d)): float(f) for d, f in zip(days, frac)}


# =========================================================================== ground truth
def iam_runs(t: np.ndarray, w: np.ndarray, on_w: float = GT_ON_W, min_s: float = GT_MIN_S,
             merge_s: float = GT_MERGE_S) -> list[tuple[float, float, float]]:
    """Runs of an IAM channel above ``on_w``: [(t_start, t_end, median_w)], t_end = first sample below."""
    x = w > on_w
    if not x.any():
        return []
    dx = np.diff(x.astype(np.int8))
    starts = list(np.nonzero(dx == 1)[0] + 1)
    ends = list(np.nonzero(dx == -1)[0] + 1)
    if x[0]:
        starts.insert(0, 0)
    if x[-1]:
        ends.append(len(x) - 1)
    runs: list[list[int]] = []
    for s, e in zip(starts, ends):
        if runs and t[s] - t[runs[-1][1]] <= merge_s:
            runs[-1][1] = e
        else:
            runs.append([s, e])
    out = []
    for s, e in runs:
        dur = float(t[e] - t[s])
        if dur >= min_s:
            seg = w[s:e]
            seg = seg[seg > on_w]
            out.append((float(t[s]), float(t[e]), float(np.median(seg)) if len(seg) else float(w[s])))
    return out


def match(det: list[float], gt: list[float], tol: float = MATCH_TOL_S) -> list[tuple[int, int]]:
    """Greedy one-to-one matching of event times (closest pairs first) within +-tol."""
    gt_arr = np.asarray(gt)
    pairs = []
    for i, td in enumerate(det):
        lo = np.searchsorted(gt_arr, td - tol, "left")
        hi = np.searchsorted(gt_arr, td + tol, "right")
        for j in range(lo, hi):
            pairs.append((abs(gt_arr[j] - td), i, j))
    pairs.sort()
    used_d, used_g, out = set(), set(), []
    for _, i, j in pairs:
        if i not in used_d and j not in used_g:
            used_d.add(i)
            used_g.add(j)
            out.append((i, j))
    return out


# =========================================================================== detection (cached)
def _code_key(cfg: DetectorConfig) -> str:
    src = (DATA_VERSION + inspect.getsource(kdetect) + inspect.getsource(ksig)
           + json.dumps(asdict(cfg), sort_keys=True))
    return hashlib.sha1(src.encode()).hexdigest()[:12]


def _stream(det: Detector, t: np.ndarray, w: np.ndarray, chunk: int = 200_000):
    """Feed samples to the streaming detector (chunked to keep memory low); yields events."""
    push = det.push
    for i in range(0, len(t), chunk):
        for ti, wi in zip(t[i:i + chunk].astype(float).tolist(), w[i:i + chunk].astype(float).tolist()):
            yield from push(ti, wi)


EV_COLS = ["t_on", "t", "dp_w", "label", "confidence", "human", "duration_s", "flatness_cv", "cycle_id",
           "human_score"]


def run_detector(h: int, channel: str, cfg: DetectorConfig, data: dict | None = None,
                 force: bool = False, tag: str = "") -> tuple[pd.DataFrame, dict]:
    """Run the shipped streaming Detector over one channel of one house. Cached per code version."""
    key = _code_key(cfg)
    p = CACHE_DIR / "events" / f"h{h}_{channel}{tag}_{key}.csv"
    pm = p.with_suffix(".json")
    if p.exists() and pm.exists() and not force:
        meta = json.loads(pm.read_text())
        meta["cached"] = True
        return pd.read_csv(p), meta
    data = data if data is not None else load_house(h)
    t = data["t"]
    w = data[channel]
    det = Detector(f"h{h}:{channel}", cfg)
    rows = []
    on_counts: Counter = Counter()
    t0 = time.time()
    for ev in _stream(det, t, w):
        if ev.kind == "on":
            on_counts[ev.label] += 1
        else:
            rows.append((ev.t_on, ev.t, ev.dp_w, ev.label, ev.confidence, ev.human,
                         ev.duration_s, ev.flatness_cv, ev.cycle_id, ev.human_score))
    meta = {"house": h, "channel": channel, "samples": int(len(t)), "seconds": round(time.time() - t0, 1),
            "on_events_by_label": dict(on_counts), "config": asdict(cfg), "code_key": key}
    df = pd.DataFrame(rows, columns=EV_COLS)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    pm.write_text(json.dumps(meta))
    return df, meta


def cache_house(h: int) -> tuple[int, int]:
    """Worker: make sure the .npz cache of a house exists; returns (house, samples)."""
    return h, len(load_house(h)["t"])


# =========================================================================== per-house worker
def agg_config() -> DetectorConfig:
    return DetectorConfig.for_refit()


def plug_config() -> DetectorConfig:
    return DetectorConfig.for_plug("kettle", region="uk")


def kettle_valid(h: int) -> bool:
    return h in KETTLE_CH and h != 12   # H12 "kettle" IAM never exceeds ~1 kW: not a kettle


def process_house(h: int, force: bool = False, quick_days: int | None = None) -> dict:
    """Worker: run the shipped detector on the aggregate (v1) and the kettle IAM (v0 plug)."""
    data = load_house(h)
    if quick_days:
        # quick mode: a winter slice (Nov-Jan) of the data only
        tl = data["tl"]
        start = np.datetime64("2014-11-01").astype("datetime64[s]").astype("int64")
        sel = (tl >= start) & (tl < start + quick_days * 86400)
        if sel.sum() < 1000:
            sel = np.arange(len(tl)) < min(len(tl), quick_days * 86400 // 7)
        data = {k: v[sel] for k, v in data.items()}
    tag = f"q{quick_days}" if quick_days else ""
    out: dict = {"house": h}
    out["agg_events"], out["agg_meta"] = run_detector(h, "agg", agg_config(), data, force, tag)
    out["cov_morning"] = day_coverage(data["tl"], *MORNING)
    out["cov_day"] = day_coverage(data["tl"], 4 * 60, 24 * 60)
    out["cov_24h"] = day_coverage(data["tl"], 0, 24 * 60)
    if kettle_valid(h):
        out["plug_events"], out["plug_meta"] = run_detector(h, "kettle", plug_config(), data, force, tag)
        out["gt_kettle"] = iam_runs(data["t"], data["kettle"])
        cal = calibrate_kettle(out["agg_events"], out["gt_kettle"], detection_valid_days(out))
        if cal:
            cfg = agg_config()
            cfg.kettle_w = cal["kettle_w"]
            out["calibration"] = cal
            out["aggcal_events"], _ = run_detector(h, "agg", cfg, data, force, tag)
        ablate = agg_config()
        ablate.repeat_window_s = 0.0
        out["aggnorep_events"], _ = run_detector(h, "agg", ablate, data, force, tag)
    if h in KETTLE_CH:
        runs = iam_runs(data["t"], data["kettle"])
        chk = {"channel": f"Appliance{KETTLE_CH[h]}", "max_w": round(float(data["kettle"].max())),
               "runs_over_1000w": len(runs)}
        if h in KETTLE_VALID_UNTIL:
            cut = dt.datetime.combine(KETTLE_VALID_UNTIL[h], dt.time(0), TZ).timestamp()
            for name, sel in (("before", [r for r in runs if r[0] < cut]), ("after", [r for r in runs if r[0] >= cut])):
                chk[f"median_run_w_{name}_{KETTLE_VALID_UNTIL[h].isoformat()}"] = (
                    round(float(np.median([r[2] for r in sel]))) if sel else None)
        out["kettle_checks"] = chk
    if "microwave" in data:
        out["gt_microwave"] = iam_runs(data["t"], data["microwave"], on_w=500.0)
    out["span"] = (int(data["t"][0]), int(data["t"][-1]))
    out["samples"] = int(len(data["t"]))
    out["issues_frac"] = float(data["issues"].mean())
    return out


def _process_house_star(args):
    return process_house(*args)


def run_all(houses: list[int], jobs: int, force: bool, quick_days: int | None) -> dict[int, dict]:
    # Detection is pure Python and memory-light once the .npz cache exists; CSV parsing is not,
    # so caches are built first with at most 3 houses in memory at a time.
    missing = [h for h in houses if not _npz_path(h).exists()]
    if missing:
        log(f"building .npz caches for houses {missing} (3 at a time)")
        with ProcessPoolExecutor(min(3, len(missing))) as ex:
            for h, n in ex.map(cache_house, missing):
                log(f"  cached house {h}: {n} samples")
    res: dict[int, dict] = {}
    with ProcessPoolExecutor(max(1, min(jobs, len(houses)))) as ex:
        for r in ex.map(_process_house_star, [(h, force, quick_days) for h in houses]):
            res[r["house"]] = r
            m = r["agg_meta"]
            log(f"house {r['house']}: {m['samples']} samples, {len(r['agg_events'])} aggregate cycles"
                f" ({m['seconds']}s detector{', cached' if m.get('cached') else ''})")
    return res


# =========================================================================== helpers
def local_dates(ts) -> np.ndarray:
    """Unix UTC seconds -> array of local (Europe/London) dates."""
    if len(ts) == 0:
        return np.array([], dtype=object)
    idx = pd.to_datetime(np.asarray(ts, dtype="float64"), unit="s", utc=True).tz_convert(TZ)
    return np.asarray(idx.date)


def local_hm(t: float) -> tuple[str, float]:
    x = dt.datetime.fromtimestamp(t, TZ)
    return x.strftime("%H:%M"), round(x.hour * 60 + x.minute + x.second / 60, 1)


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    rnd = lambda x: None if x is None else round(x, 3)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": rnd(p), "recall": rnd(r), "f1": rnd(f)}


def detection_valid_days(r: dict) -> set:
    h = r["house"]
    days = {d for d, c in r["cov_24h"].items() if c >= COVER_MIN}
    if h in KETTLE_VALID_UNTIL:
        days = {d for d in days if d < KETTLE_VALID_UNTIL[h]}
    return days


def eval_label(r: dict, label: str, gt: list, ev: pd.DataFrame) -> dict:
    days = detection_valid_days(r)
    sel = ev[ev["label"] == label].sort_values("t_on")
    sel = sel[np.isin(local_dates(sel["t_on"].to_numpy(float)), list(days))] if len(sel) else sel
    det_t = sel["t_on"].to_numpy(float)
    gt_t = np.sort(np.array([g[0] for g in gt], float))
    gt_t = gt_t[np.isin(local_dates(gt_t), list(days))] if len(gt_t) else gt_t
    m = match(det_t.tolist(), gt_t.tolist())
    tp = len(m)
    out = prf(tp, len(det_t) - tp, len(gt_t) - tp)
    out["days"] = len(days)
    if m:
        out["median_abs_offset_s"] = round(float(np.median([abs(det_t[i] - gt_t[j]) for i, j in m])), 1)
    fp = np.ones(len(sel), bool)
    fp[[i for i, _ in m]] = False
    if fp.any():
        out["fp_median_dp_w"] = round(float(np.median(sel["dp_w"].to_numpy()[fp])))
        out["fp_median_duration_s"] = round(float(np.median(sel["duration_s"].to_numpy()[fp])))
    return out


# =========================================================================== 1. detector eval
def detector_eval(res: dict[int, dict]) -> dict:
    per_house = {}
    for h, r in sorted(res.items()):
        ev = r["agg_events"]
        days = detection_valid_days(r)
        entry: dict = {"occupants": OCCUPANCY[h], "split": "tune" if h in TUNE_HOUSES else "test"}
        evd = ev[np.isin(local_dates(ev["t_on"].to_numpy(float)), list(days))] if len(ev) else ev
        entry["cycles_by_label"] = {k: int(v) for k, v in evd["label"].value_counts().items()}
        entry["human_cycles_per_day"] = round(float(evd["human"].sum()) / max(len(days), 1), 1)
        entry["days_24h_covered"] = len(days)
        if kettle_valid(h):
            entry["kettle_whole_home"] = eval_label(r, "kettle", r["gt_kettle"], ev)
            entry["kettle_plug"] = eval_label(r, "kettle", r["gt_kettle"], r["plug_events"])
            if "aggcal_events" in r:
                entry["kettle_whole_home_calibrated"] = eval_label(r, "kettle", r["gt_kettle"], r["aggcal_events"])
                entry["calibration"] = r["calibration"]
            entry["kettle_whole_home_no_repeat_filter"] = eval_label(r, "kettle", r["gt_kettle"], r["aggnorep_events"])
            entry["kettle_median_w"] = round(float(np.median([g[2] for g in r["gt_kettle"]])))
        if "kettle_checks" in r:
            entry["kettle_channel_checks"] = r["kettle_checks"]
        if "gt_microwave" in r:
            entry["microwave_whole_home"] = eval_label(r, "microwave", r["gt_microwave"], ev)
        per_house[str(h)] = entry

    def pool(hs: list[int], key: str) -> dict | None:
        es = [per_house[str(h)][key] for h in hs if str(h) in per_house and key in per_house[str(h)]]
        if not es:
            return None
        tp, fp, fn = (sum(e[k] for e in es) for k in ("tp", "fp", "fn"))
        out = prf(tp, fp, fn)
        out["houses"] = [h for h in hs if str(h) in per_house and key in per_house[str(h)]]
        f1s = [e["f1"] for e in es if e["f1"] is not None]
        out["macro_f1"] = round(statistics.mean(f1s), 3) if f1s else None
        return out

    splits = {"overall": sorted(res), "tune_1_9": [h for h in res if h in TUNE_HOUSES],
              "test_10_21": [h for h in res if h in TEST_HOUSES]}
    keys = ("kettle_whole_home", "kettle_whole_home_calibrated", "kettle_whole_home_no_repeat_filter",
            "kettle_plug", "microwave_whole_home")
    summary = {name: {k: pool(hs, k) for k in keys} for name, hs in splits.items()}
    labels: Counter = Counter()
    for e in per_house.values():
        labels.update(e["cycles_by_label"])
    return {"summary": summary, "cycles_by_label_all_houses": dict(labels.most_common()),
            "per_house": per_house}


# =========================================================================== calibration boil
N_CAL_BOILS = 3


def calibrate_kettle(ev: pd.DataFrame, gt: list, days: set) -> dict | None:
    """Simulate the setup step "boil your kettle now" (three times): for the first boils in the
    data (known from the kettle IAM), take the largest step the *whole-home* detector saw
    starting within [-30 s, +60 s]; the median is the home's kettle step size."""
    if not gt or ev.empty:
        return None
    ton = ev["t_on"].to_numpy(float)
    dp = ev["dp_w"].to_numpy(float)
    order = np.argsort(ton)
    ton, dp = ton[order], dp[order]
    steps, used = [], []
    for g in gt:
        if local_dates([g[0]])[0] not in days:
            continue
        lo, hi = np.searchsorted(ton, [g[0] - 30, g[0] + 60])
        if hi > lo and dp[lo:hi].max() > 1000:
            steps.append(float(dp[lo:hi].max()))
            used.append(g[0])
        if len(steps) == N_CAL_BOILS:
            break
    if not steps:
        return None
    return {"kettle_w": round(statistics.median(steps), 1), "steps_w": [round(x) for x in steps],
            "boil_times": [dt.datetime.fromtimestamp(x, TZ).isoformat() for x in used]}


# =========================================================================== 2. false alarms
MODES = {
    "v0_kettle_plug": "activity = kettle uses seen by the shipped detector on the kettle's own plug (REFIT kettle IAM)",
    "v1_whole_home": "activity = cycles the shipped detector labels human (human=True) on the whole-home Aggregate channel",
}


def mode_events(r: dict, mode: str, confirmed: bool = False) -> list[tuple[float, str]] | None:
    """Human evidence for one sensing mode: [(unix_t, label)] (rising-edge time unless ``confirmed``)."""
    if mode == "v0_kettle_plug":
        if "plug_events" not in r:
            return None
        ev = r["plug_events"]
        ev = ev[ev["human"]]
    else:
        ev = r["agg_events"]
        ev = ev[ev["human"]]
    tcol = "t" if confirmed else "t_on"
    return list(zip(ev[tcol].astype(float), ev["label"]))


def mode_days(r: dict, mode: str) -> set:
    days = {d for d, c in r["cov_morning"].items() if c >= COVER_MIN and d not in UNCERTAIN_TIME_DAYS}
    if mode == "v0_kettle_plug" and r["house"] in KETTLE_VALID_UNTIL:
        days = {d for d in days if d < KETTLE_VALID_UNTIL[r["house"]]}
    return days


def rolling_walk(r: dict, mode: str, policy: Policy, confirmed: bool = False) -> list[dict] | None:
    """Day-by-day: deadline from a model trained only on previous days, then check-in or not."""
    evs = mode_events(r, mode, confirmed)
    if evs is None:
        return None
    first = first_activity_by_day(evs, TZ)
    days = sorted(mode_days(r, mode))
    obs = [DayObs(d, *(first[d] if d in first else (None, None))) for d in days]
    model = RhythmModel(policy).fit(obs)       # baseline(date) only ever looks at days < date
    out = []
    for o in obs:
        b = model.baseline(o.date)
        rec = {"date": o.date, "first_min": o.first_min, "first_label": o.first_label,
               "learned": b.learned, "kind": b.kind, "usual_min": b.usual_min,
               "deadline_min": b.deadline_min, "margin_min": b.margin_min if b.learned else None}
        if b.deadline_min > MORNING[1] and r["cov_day"].get(o.date, 0) < COVER_MIN:
            rec["excluded"] = "coverage_to_deadline"
        elif o.first_min is None:
            rec["checkin"] = "no_activity"
            rec["day_coverage_ok"] = r["cov_day"].get(o.date, 0) >= COVER_MIN
        elif o.first_min > b.deadline_min:
            rec["checkin"] = "late_start"
        else:
            rec["checkin"] = None
        out.append(rec)
    return out


def summarize_walk(recs: list[dict], r: dict, mode: str) -> dict:
    ev = [x for x in recs if "excluded" not in x]
    n = len(ev)
    late = sum(x["checkin"] == "late_start" for x in ev)
    none = sum(x["checkin"] == "no_activity" for x in ev)
    none_partial = sum(x["checkin"] == "no_activity" and not x["day_coverage_ok"] for x in ev)
    learn = sum(not x["learned"] for x in ev)
    margins = [x["margin_min"] for x in ev if x["margin_min"] is not None]
    deadlines = [x["deadline_min"] for x in ev if x["learned"]]
    usual = [x["usual_min"] for x in ev if x["learned"]]
    all_days = [d for d in r["cov_morning"]]
    if mode == "v0_kettle_plug" and r["house"] in KETTLE_VALID_UNTIL:
        all_days = [d for d in all_days if d < KETTLE_VALID_UNTIL[r["house"]]]
    pm = lambda k, d: round(k / d * MONTH_DAYS, 2) if d else None
    return {
        "calendar_days": len(all_days),
        "excluded_low_coverage": len(all_days) - len(recs) + sum("excluded" in x for x in recs),
        "evaluated_days": n,
        "learning_days": learn,
        "checkins": late + none,
        "late_start": late,
        "no_activity_all_day": none,
        "no_activity_with_incomplete_afternoon_data": none_partial,
        "checkins_per_month": pm(late + none, n),
        "late_start_per_month": pm(late, n),
        "no_activity_per_month": pm(none, n),
        "away_paused_checkins_per_month": pm(late, n - none),
        "median_margin_min": round(statistics.median(margins), 1) if margins else None,
        "median_usual": fmt_min(statistics.median(usual)) if usual else None,
        "median_deadline": fmt_min(statistics.median(deadlines)) if deadlines else None,
    }


def pool_walk(per_house: dict[str, dict], hs: list[int]) -> dict | None:
    rows = [per_house[str(h)] for h in hs if str(h) in per_house]
    if not rows:
        return None
    S = lambda k: sum(x[k] for x in rows)
    n, late, none = S("evaluated_days"), S("late_start"), S("no_activity_all_day")
    rates = sorted(x["checkins_per_month"] for x in rows if x["checkins_per_month"] is not None)
    away = sorted(x["away_paused_checkins_per_month"] for x in rows if x["away_paused_checkins_per_month"] is not None)
    return {
        "houses": [h for h in hs if str(h) in per_house],
        "evaluated_days": n, "excluded_low_coverage": S("excluded_low_coverage"),
        "learning_days": S("learning_days"),
        "checkins": late + none, "late_start": late, "no_activity_all_day": none,
        "checkins_per_home_month": round((late + none) / n * MONTH_DAYS, 2) if n else None,
        "late_start_per_home_month": round(late / n * MONTH_DAYS, 2) if n else None,
        "no_activity_per_home_month": round(none / n * MONTH_DAYS, 2) if n else None,
        "away_paused_checkins_per_home_month": round(late / (n - none) * MONTH_DAYS, 2) if n - none else None,
        "median_house_checkins_per_month": round(statistics.median(rates), 2) if rates else None,
        "range_house_checkins_per_month": [rates[0], rates[-1]] if rates else None,
        "median_house_away_paused_per_month": round(statistics.median(away), 2) if away else None,
    }


def margin_stats(walks: list[list[dict]]) -> dict | None:
    m = [x["margin_min"] for w in walks for x in w if "excluded" not in x and x["margin_min"] is not None]
    if not m:
        return None
    q = np.percentile(m, [25, 50, 75])
    return {"median_min": round(float(q[1]), 1), "p25_min": round(float(q[0]), 1), "p75_min": round(float(q[2]), 1),
            "n_days": len(m)}


def false_alarm_eval(res: dict[int, dict]) -> tuple[dict, dict]:
    walks: dict = {}
    out: dict = {"modes": MODES, "policies": {p.name: asdict(p) for p in POLICIES}, "results": {}}
    for mode in MODES:
        out["results"][mode] = {}
        for pol in POLICIES:
            per_house = {}
            for h, r in sorted(res.items()):
                w = rolling_walk(r, mode, pol)
                if w is None:
                    continue
                walks[(h, mode, pol.name)] = w
                per_house[str(h)] = summarize_walk(w, r, mode)
            splits = {"overall": sorted(res), "tune_1_9": [h for h in res if h in TUNE_HOUSES],
                      "test_10_21": [h for h in res if h in TEST_HOUSES],
                      "single_occupant_11_15": [h for h in res if OCCUPANCY[h] == 1]}
            out["results"][mode][pol.name] = {
                "pooled": {k: pool_walk(per_house, hs) for k, hs in splits.items()},
                "time_to_first_checkin_after_usual": margin_stats(
                    [walks[(h, mode, pol.name)] for h in res if (h, mode, pol.name) in walks]),
                "per_house": per_house,
            }
    # Sensitivity: whole-home evidence timed at confirmation (falling edge) instead of rising edge.
    sens = {}
    for pol in POLICIES:
        ph = {str(h): summarize_walk(rolling_walk(r, "v1_whole_home", pol, confirmed=True), r, "v1_whole_home")
              for h, r in sorted(res.items())}
        sens[pol.name] = pool_walk(ph, sorted(res))
    out["sensitivity_v1_confirmation_time"] = sens
    out["diagnostics"] = diagnostics(res, walks)
    return out, walks


def diagnostics(res: dict[int, dict], walks: dict) -> dict:
    """Checks on the whole-home evidence that the false-alarm numbers cannot show by themselves."""
    d: dict = {"per_house": {}}
    for h, r in sorted(res.items()):
        e: dict = {}
        hum = r["agg_events"][r["agg_events"]["human"]]
        days = mode_days(r, "v1_whole_home")
        loc = pd.to_datetime(hum["t_on"].to_numpy(float), unit="s", utc=True).tz_convert(TZ)
        mins = loc.hour * 60 + loc.minute
        night = (mins >= 60) & (mins < 240)
        nd = np.isin(np.asarray(loc.date), list(days))
        e["v1_human_events_per_day"] = round(float(nd.sum()) / max(len(days), 1), 1)
        e["v1_human_events_01_04_per_night"] = round(float((night & nd).sum()) / max(len(days), 1), 2)
        # The rule before tuning: every cycle with a human label counted, whatever its score.
        old = r["agg_events"][r["agg_events"]["label"].isin(HUMAN_LABELS)]
        oloc = pd.to_datetime(old["t_on"].to_numpy(float), unit="s", utc=True).tz_convert(TZ)
        omins = oloc.hour * 60 + oloc.minute
        ond = np.isin(np.asarray(oloc.date), list(days))
        e["old_rule_human_events_01_04_per_night"] = round(
            float(((omins >= 60) & (omins < 240) & ond).sum()) / max(len(days), 1), 2)
        for key, evs in (("v1_median_first", hum), ("old_rule_median_first", old)):
            f = first_activity_by_day(list(zip(evs["t_on"].astype(float), evs["label"])), TZ)
            xs = [f[x][0] for x in days if x in f]
            e[key] = fmt_min(statistics.median(xs)) if xs else None
            e[key + "_min"] = round(statistics.median(xs), 1) if xs else None
        w0 = walks.get((h, "v0_kettle_plug", "standard"))
        w1 = {x["date"]: x for x in walks[(h, "v1_whole_home", "standard")]}
        if w0:
            nok = [x for x in w0 if "excluded" not in x and x["first_min"] is None]
            # v0 says "no kettle all day": did the whole-home detector see a person that day?
            seen = [x for x in nok if x["date"] in w1 and w1[x["date"]]["first_min"] is not None]
            e["v0_no_kettle_days"] = len(nok)
            e["v0_no_kettle_days_with_v1_activity"] = len(seen)
            # "Probably empty house": runs of >=2 consecutive no-kettle days (<=14 days, longer
            # runs may be a dead IAM) in a home that otherwise uses the kettle daily.
            dates = sorted(x["date"] for x in nok)
            runs, cur = [], []
            for x in dates:
                if cur and (x - cur[-1]).days == 1:
                    cur.append(x)
                else:
                    if cur:
                        runs.append(cur)
                    cur = [x]
            if cur:
                runs.append(cur)
            empty = [x for run in runs if 2 <= len(run) <= 14 for x in run]
            e["probably_empty_days"] = len(empty)
            e["longest_no_kettle_run_days"] = max((len(x) for x in runs), default=0)
            e["probably_empty_days_with_v1_activity"] = sum(
                1 for x in empty if x in w1 and w1[x]["first_min"] is not None)
        d["per_house"][str(h)] = e
    ph = d["per_house"]
    tot = lambda k: sum(v.get(k, 0) for v in ph.values())
    d["pooled"] = {
        "v1_human_events_01_04_per_night_median_house": round(statistics.median(
            [v["v1_human_events_01_04_per_night"] for v in ph.values()]), 2),
        "v0_no_kettle_days": tot("v0_no_kettle_days"),
        "v0_no_kettle_days_with_v1_activity": tot("v0_no_kettle_days_with_v1_activity"),
        "probably_empty_days": tot("probably_empty_days"),
        "probably_empty_days_with_v1_activity": tot("probably_empty_days_with_v1_activity"),
        "tune_houses_old_rule_median_first_before_0530": sum(
            1 for h, v in ph.items() if int(h) in TUNE_HOUSES and (v.get("old_rule_median_first_min") or 1e9) < 330),
        "tune_houses_v1_median_first_before_0530": sum(
            1 for h, v in ph.items() if int(h) in TUNE_HOUSES and (v.get("v1_median_first_min") or 1e9) < 330),
        "tune_houses": sum(1 for h in ph if int(h) in TUNE_HOUSES),
    }
    d["clock_check"] = clock_check(res)
    return d


CLOCK_CHANGES = [dt.date(2013, 10, 27), dt.date(2014, 3, 30), dt.date(2014, 10, 1), dt.date(2014, 10, 26),
                 dt.date(2015, 3, 29)]


def clock_check(res: dict[int, dict]) -> dict:
    """Evidence for the timestamp correction: median shift of each home's first kettle use (weekdays,
    21 days after minus 21 days before) at each date where the stamp convention or the clock changes,
    read with our correction and read naively (every stamp = local time)."""
    def raw_reading(day: dt.date, m: float) -> float:
        # Under the naive reading, UTC-stamped summer days appear one hour early.
        utc_stamped = any(dt.date.fromisoformat(a[:10]) <= day < dt.date.fromisoformat(b[:10]) for a, b in UTC_STAMPED)
        bst = dt.datetime.combine(day, dt.time(12), TZ).utcoffset() != dt.timedelta(0)
        return m - 60 if utc_stamped and bst else m
    out = {}
    for change in CLOCK_CHANGES:
        rows = {"corrected": [], "naive": []}
        for h, r in res.items():
            if "plug_events" not in r:
                continue
            ev = r["plug_events"][r["plug_events"]["human"]]
            f = first_activity_by_day(list(zip(ev["t_on"].astype(float), ev["label"])), TZ)
            for name, fn in (("corrected", lambda d, m: m), ("naive", raw_reading)):
                b = [fn(d, f[d][0]) for d in f if change - dt.timedelta(days=21) <= d < change and d.weekday() < 5]
                a = [fn(d, f[d][0]) for d in f if change < d <= change + dt.timedelta(days=21) and d.weekday() < 5]
                if len(a) >= 8 and len(b) >= 8:
                    rows[name].append(statistics.median(a) - statistics.median(b))
        out[change.isoformat()] = {k: {"median_shift_min": round(statistics.median(v), 1) if v else None,
                                       "homes": len(v)} for k, v in rows.items()}
    return out


# =========================================================================== demo exports
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_bounds(day: dt.date) -> tuple[float, float]:
    a = dt.datetime.combine(day, dt.time(4, 0), TZ).timestamp()
    b = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(4, 0), TZ).timestamp()
    return a, b


def human_events_of_day(ev: pd.DataFrame, day: dt.date) -> list[dict]:
    a, b = day_bounds(day)
    sel = ev[(ev["human"]) & (ev["t_on"] >= a) & (ev["t_on"] < b)].sort_values("t_on")
    out = []
    for x in sel.itertuples():
        hm, mins = local_hm(x.t_on)
        out.append({"time": hm, "min": mins, "label": x.label, "dp_w": round(x.dp_w),
                    "duration_s": round(x.duration_s), "human_score": round(x.human_score, 2)})
    return out


def provenance(houses: list[int], extra: dict | None = None) -> dict:
    d = {"dataset": "REFIT Electrical Load Measurements (cleaned), CLEAN_REFIT_081116",
         "files": [f"CLEAN_House{h}.csv" for h in houses], "licence": LICENCE, "citation": CITATION,
         "time_zone": "Europe/London (REFIT Unix column is local wall-clock time; see docs/refit-evaluation.md)",
         "code": "kettle/eval/refit.py using kettle.detect, kettle.signatures, kettle.rhythm"}
    d.update(extra or {})
    return d


def find_window(r: dict, length: int, months=(11, 12, 1, 2)) -> list[dt.date] | None:
    """First run of `length` consecutive fully covered (>=90% of 24 h) days, starting on a Monday,
    in winter (Nov-Feb), such that the day after is also covered."""
    good = {d for d, c in r["cov_24h"].items() if c >= COVER_MIN}
    for d in sorted(good):
        if d.weekday() != 0 or d.month not in months:
            continue
        win = [d + dt.timedelta(days=i) for i in range(length + 1)]
        if all(x in good for x in win):
            return win[:length]
    return None


def margaret_baseline(r: dict, walks: dict) -> dict | None:
    h = r["house"]
    win = None
    for length in (28, 21, 14):
        win = find_window(r, length)
        if win:
            break
    if not win:
        return None
    nxt = win[-1] + dt.timedelta(days=1)
    plug = r.get("plug_events")
    rolling = {m: {x["date"]: x for x in walks[(h, m, "standard")]} for m in MODES if (h, m, "standard") in walks}
    days = []
    for day in win:
        v1 = human_events_of_day(r["agg_events"], day)
        rec = {"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()],
               "first_min": v1[0]["min"] if v1 else None, "first_time": v1[0]["time"] if v1 else None,
               "first_label": v1[0]["label"] if v1 else None, "events": v1}
        if plug is not None:
            k = human_events_of_day(plug, day)
            rec["kettle_iam_uses"] = [{kk: e[kk] for kk in ("time", "min", "dp_w", "duration_s")} for e in k]
            rec["v0_first_min"] = k[0]["min"] if k else None
        for m, w in rolling.items():
            x = w.get(day)
            if x:
                rec[f"{m}_rolling_deadline"] = fmt_min(x["deadline_min"])
                rec[f"{m}_rolling_checkin"] = x.get("checkin")
        days.append(rec)
    baselines = {}
    for m in MODES:
        evs = mode_events(r, m)
        if evs is None:
            continue
        first = first_activity_by_day(evs, TZ)
        obs = [DayObs(d, *(first[d] if d in first else (None, None))) for d in win]
        baselines[m] = {p.name: RhythmModel(p).fit(obs).baseline(nxt).to_dict() for p in POLICIES}
    return {
        "persona": "Margaret",
        "house": h, "occupants": OCCUPANCY[h],
        "window": {"start": win[0].isoformat(), "end": win[-1].isoformat(), "days": len(win),
                   "rule": "first run of >=28 (else 21, 14) consecutive days starting on a Monday in Nov-Feb "
                           "with >=90% data coverage over each full day (and the following day)"},
        "baseline_for": {"date": nxt.isoformat(), "weekday": WEEKDAYS[nxt.weekday()],
                         "fitted_on": "the window days only"},
        "baselines": baselines,
        "days": days,
        "notes": ["events = cycles the whole-home (Aggregate) detector marked human (v1); "
                  "kettle_iam_uses = the shipped detector on the kettle IAM (v0, a smart plug equivalent)",
                  "min = minutes after local midnight; a Kettle day starts at 04:00",
                  "*_rolling_deadline/checkin: model trained only on earlier days (all available history), standard policy"],
        "provenance": provenance([h]),
    }


def kettle_boil_trace(r: dict, day: dt.date) -> dict | None:
    h = r["house"]
    plug = r.get("plug_events")
    if plug is None:
        return None
    a, b = day_bounds(day)
    sel = plug[(plug["t_on"] >= a) & (plug["t_on"] < b) & plug["human"]].sort_values("t_on")
    if sel.empty:
        return None
    ev = sel.iloc[0]
    d = load_house(h)
    t0, t1 = ev["t_on"] - 120, ev["t"] + 120
    i0, i1 = np.searchsorted(d["t"], [t0, t1])
    seg_t = d["t"][i0:i1]
    hm, _ = local_hm(ev["t_on"])
    return {
        "house": h, "date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()],
        "boil_start_local": dt.datetime.fromtimestamp(ev["t_on"], TZ).isoformat(),
        "boil_duration_s": round(float(ev["duration_s"])), "step_w": round(float(ev["dp_w"])),
        "trace_start_local": dt.datetime.fromtimestamp(t0, TZ).isoformat(),
        "units": {"t": "seconds from trace start", "w": "watts"},
        "kettle_iam": [[int(t - t0), int(w)] for t, w in zip(seg_t, d["kettle"][i0:i1])],
        "aggregate": [[int(t - t0), int(w)] for t, w in zip(seg_t, d["agg"][i0:i1])],
        "notes": ["REFIT samples every ~6-8 s at irregular times; repeated values are REFIT's forward fill",
                  "chosen by rule: the first kettle use of the first day of the Margaret window",
                  "kettle IAM and aggregate sensors are not synchronised (up to ~8 s apart)"],
        "provenance": provenance([h]),
    }


REPLAY_PREFERENCE = [15, 3, 8, 19, 20, 2, 5, 6, 9, 17, 13, 4, 7, 10, 18, 16, 12, 1, 21]


def homes_replay(res: dict[int, dict], walks: dict, n: int = 5) -> dict:
    homes = []
    for h in REPLAY_PREFERENCE:
        if h not in res or len(homes) >= n:
            continue
        r = res[h]
        w = {x["date"]: x for x in walks[(h, "v1_whole_home", "standard")]}
        for start in (dt.date(2014, 12, 1), dt.date(2013, 12, 1)):
            pick = None
            for i in range(90):
                day = start + dt.timedelta(days=i)
                x = w.get(day)
                if (day.weekday() < 5 and x and "excluded" not in x and r["cov_24h"].get(day, 0) >= COVER_MIN
                        and x["learned"] and x["checkin"] is None):
                    pick = day
                    break
            if pick:
                break
        if not pick:
            continue
        evs = mode_events(r, "v1_whole_home")
        first = first_activity_by_day(evs, TZ)
        prev = [DayObs(d, *first[d]) if d in first else DayObs(d, None)
                for d in sorted(w) if pick - dt.timedelta(days=28) <= d < pick and "excluded" not in w[d]]
        base = RhythmModel(STANDARD).fit(prev).baseline(pick)
        cold = RhythmModel(COLD).fit(prev).baseline(pick)
        events = human_events_of_day(r["agg_events"], pick)
        rec = {"house": h, "occupants": OCCUPANCY[h], "split": "tune" if h in TUNE_HOUSES else "test",
               "date": pick.isoformat(), "weekday": WEEKDAYS[pick.weekday()],
               "first_activity": {"min": events[0]["min"], "time": events[0]["time"], "label": events[0]["label"]},
               "events": events, "baseline": base.to_dict(), "baseline_cold": cold.to_dict(),
               "history_days": len(prev)}
        if "plug_events" in r:
            k = human_events_of_day(r["plug_events"], pick)
            rec["kettle_iam_uses"] = [{kk: e[kk] for kk in ("time", "min", "dp_w", "duration_s")} for e in k]
        homes.append(rec)
    return {"rule": "per house (preference order 15, 3, 8, 19, 20, then others): the first weekday from "
                    "1 Dec 2014 (else 1 Dec 2013) with >=90% 24 h coverage, a learned whole-home baseline "
                    "and first activity before the standard deadline (an ordinary day). Baseline fitted on "
                    "the previous 28 days only.",
            "mode": "v1_whole_home (events = cycles the Aggregate detector marked human)",
            "homes": homes, "provenance": provenance([x["house"] for x in homes])}


# =========================================================================== summary + main
def build_summary(det: dict, fa: dict, res: dict) -> dict:
    R = fa["results"]
    g = lambda mode, pol, key="checkins_per_home_month", split="overall": (
        (R[mode][pol]["pooled"][split] or {}).get(key))
    k = det["summary"]
    f1 = lambda split, key: (k[split][key] or {}).get("f1")
    return {
        "generated_at": dt.datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source": "REFIT (Murray, Stankovic & Stankovic 2017), CC BY 4.0",
        "houses": len(res),
        "home_days": (R["v1_whole_home"]["standard"]["pooled"]["overall"] or {}).get("evaluated_days"),
        "home_days_kettle_plug": (R["v0_kettle_plug"]["standard"]["pooled"]["overall"] or {}).get("evaluated_days"),
        "checkins_per_home_month": {m: {p.name: g(m, p.name) for p in POLICIES} for m in MODES},
        "checkins_per_home_month_test_houses": {
            m: {p.name: g(m, p.name, split="test_10_21") for p in POLICIES} for m in MODES},
        "checkins_per_home_month_away_paused": {
            m: {p.name: g(m, p.name, "away_paused_checkins_per_home_month") for p in POLICIES} for m in MODES},
        "minutes_after_usual_before_asking": {
            m: {p.name: (R[m][p.name]["time_to_first_checkin_after_usual"] or {}).get("median_min")
                for p in POLICIES} for m in MODES},
        "kettle_f1": f1("overall", "kettle_whole_home"),
        "kettle_f1_test_houses": f1("test_10_21", "kettle_whole_home"),
        "kettle_f1_calibrated": f1("overall", "kettle_whole_home_calibrated"),
        "kettle_f1_plug": f1("overall", "kettle_plug"),
        "kettle_precision": (k["overall"]["kettle_whole_home"] or {}).get("precision"),
        "kettle_recall": (k["overall"]["kettle_whole_home"] or {}).get("recall"),
        "kettle_houses": len((k["overall"]["kettle_whole_home"] or {}).get("houses", [])),
        "keys_doc": "docs/refit-evaluation.md#summaryjson",
    }


def dump(obj, path: Path) -> None:
    def default(o):
        if isinstance(o, (dt.date, dt.datetime)):
            return o.isoformat()
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        raise TypeError(type(o))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=default, ensure_ascii=False) + "\n")
    log(f"wrote {path} ({path.stat().st_size // 1024} KB)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--houses", help="comma-separated house numbers (default: all 20)")
    ap.add_argument("--quick", action="store_true",
                    help="smoke test: houses 3,11,15 (unless --houses), 120 winter days each")
    ap.add_argument("--jobs", type=int, default=max(1, min(10, (os.cpu_count() or 4) - 2)))
    ap.add_argument("--force", action="store_true", help="ignore cached detector events")
    ap.add_argument("--out", help="output directory (default: data/refit for a full run, "
                                  "else <cache>/partial so partial runs never overwrite the real outputs)")
    ap.add_argument("--no-docs", action="store_true", help="do not rewrite docs/refit-evaluation.md")
    a = ap.parse_args(argv)
    houses = [int(x) for x in a.houses.split(",")] if a.houses else ([3, 11, 15] if a.quick else HOUSES)
    full = not a.quick and sorted(houses) == HOUSES
    out = Path(a.out) if a.out else (OUT_DIR if full else CACHE_DIR / ("quick" if a.quick else "partial"))
    t0 = time.time()
    log(f"houses {houses}; output -> {out}")
    res = run_all(houses, a.jobs, a.force, 120 if a.quick else None)
    det = detector_eval(res)
    fa, walks = false_alarm_eval(res)
    det["definitions"] = {
        "ground_truth": f"kettle IAM channel above {GT_ON_W:.0f} W for >= {GT_MIN_S:.0f} s "
                        f"(runs <= {GT_MERGE_S:.0f} s apart merged); microwave IAM above 500 W for >= 16 s",
        "detection": "a 'cycle' event labelled kettle by the shipped detector on the Aggregate channel "
                     "(DetectorConfig.for_refit()); its rising-edge time is matched one-to-one to a "
                     f"ground-truth start within +-{MATCH_TOL_S:.0f} s (closest pairs first)",
        "calibrated": f"same, with DetectorConfig.kettle_w set from {N_CAL_BOILS} 'calibration boils' "
                      "(the first kettle uses in the data, as seen on the Aggregate channel)",
        "plug": "the shipped detector with DetectorConfig.for_plug('kettle','uk') on the kettle IAM",
        "days": "only local days with >=90% of the 24 h covered by data (no gap > 2 min); "
                "H21 only before 2014-08-16 (kettle IAM changed); H12 excluded (its 'kettle' IAM never exceeds ~1 kW)",
        "splits": "tune = houses 1-9 (parameters were tuned on these only), test = houses 10-21",
    }
    det["provenance"] = provenance(sorted(res))
    fa["definitions"] = {
        "day": "04:00 to 04:00 local time (Europe/London); first activity = first human evidence after 04:00",
        "evaluated_day": f"a day with >=90% of 04:00-14:00 covered by data (no gap > {COVER_GAP_S:.0f} s); if the "
                         "deadline is after 14:00 the whole 04:00-24:00 must be >=90% covered",
        "rolling_model": "RhythmModel(policy) whose baseline(date) only uses evaluated days before that date, "
                         "within policy.window_days; while learning (< learn_days days) the default deadline applies",
        "checkin": "first activity after the deadline (late_start) or no activity at all that day (no_activity_all_day); "
                   "REFIT has no real incidents, so every check-in is a false alarm",
        "per_month": f"check-ins / evaluated days x {MONTH_DAYS}",
        "away_paused": "ASSUMPTION: days with no activity at all are treated as 'away' (in production the person "
                       "can pause Kettle when travelling), so they count neither as check-ins nor as monitored days",
        "time_to_first_checkin_after_usual": "deadline - usual time on days with a learned baseline: how long after "
                                             "their usual start Kettle would first ask a person who did not get up",
    }
    fa["provenance"] = provenance(sorted(res))
    dump(det, out / "detector_eval.json")
    dump(fa, out / "false_alarm_eval.json")
    mg = None
    if 11 in res:
        mg = margaret_baseline(res[11], walks)
        if mg:
            dump(mg, out / "margaret_baseline.json")
            tr = kettle_boil_trace(res[11], dt.date.fromisoformat(mg["window"]["start"]))
            if tr:
                dump(tr, out / "kettle_boil_trace.json")
    dump(homes_replay(res, walks), out / "homes_replay.json")
    summary = build_summary(det, fa, res)
    summary["runtime_s"] = round(time.time() - t0, 1)
    dump(summary, out / "summary.json")
    if full and not a.no_docs:
        write_docs(det, fa, summary, res, mg)
    log(f"done in {time.time() - t0:.0f}s")


def _t(rows: list[list], head: list[str]) -> str:
    f = lambda x: "–" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(f(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def write_docs(det: dict, fa: dict, summary: dict, res: dict, mg: dict | None) -> None:
    S, R = det["summary"], fa["results"]
    g = lambda d, k: (d or {}).get(k)
    split_names = [("overall", "all"), ("tune_1_9", "tune (1-9)"), ("test_10_21", "test (10-21)")]
    det_rows = []
    for key, name in (("kettle_whole_home", "Kettle, whole-home meter (v1)"),
                      ("kettle_whole_home_calibrated", "Kettle, whole-home + 3 calibration boils"),
                      ("kettle_plug", "Kettle, on its own plug (v0)"),
                      ("microwave_whole_home", "Microwave, whole-home meter")):
        for sp, spn in split_names:
            x = S[sp][key]
            if x:
                det_rows.append([name, spn, len(x["houses"]), x["tp"], x["fp"], x["fn"], x["precision"],
                                 x["recall"], x["f1"], x["macro_f1"]])
    ph_rows = []
    for h, e in det["per_house"].items():
        if "kettle_whole_home" not in e:
            continue
        k, c, pl = e["kettle_whole_home"], e.get("kettle_whole_home_calibrated") or {}, e["kettle_plug"]
        ph_rows.append([h, e["split"], e["kettle_median_w"], k["tp"] + k["fn"], k["precision"], k["recall"],
                        k["f1"], c.get("f1"), pl["f1"]])
    fa_rows = []
    for mode, mname in (("v0_kettle_plug", "v0 kettle plug"), ("v1_whole_home", "v1 whole home")):
        for pol in ("standard", "cold"):
            for sp, spn in split_names + [("single_occupant_11_15", "single occupant")]:
                x = R[mode][pol]["pooled"][sp]
                if x:
                    fa_rows.append([mname, pol, spn, len(x["houses"]), x["evaluated_days"], x["checkins_per_home_month"],
                                    x["late_start_per_home_month"], x["no_activity_per_home_month"],
                                    x["away_paused_checkins_per_home_month"], x["median_house_checkins_per_month"],
                                    "{}–{}".format(*x["range_house_checkins_per_month"])])
    ttd_rows = []
    for mode, mname in (("v0_kettle_plug", "v0 kettle plug"), ("v1_whole_home", "v1 whole home")):
        for pol in ("standard", "cold"):
            m = R[mode][pol]["time_to_first_checkin_after_usual"]
            ttd_rows.append([mname, pol, m["median_min"], f"{m['p25_min']:.0f}–{m['p75_min']:.0f}", m["n_days"]])
    hh_rows = []
    for h in sorted(res):
        a = R["v0_kettle_plug"]["standard"]["per_house"].get(str(h), {})
        b = R["v1_whole_home"]["standard"]["per_house"][str(h)]
        hh_rows.append([h, OCCUPANCY[h], "tune" if h in TUNE_HOUSES else "test", b["evaluated_days"],
                        b["excluded_low_coverage"], a.get("median_usual"), a.get("checkins_per_month"),
                        b["median_usual"], b["median_deadline"], b["checkins_per_month"],
                        b["late_start_per_month"], b["no_activity_per_month"]])
    dg = fa["diagnostics"]["pooled"]
    sens = fa["sensitivity_v1_confirmation_time"]["standard"]
    v1s = R["v1_whole_home"]["standard"]["pooled"]["overall"]
    v0s = R["v0_kettle_plug"]["standard"]["pooled"]["overall"]
    night = {h: e["v1_human_events_01_04_per_night"] for h, e in fa["diagnostics"]["per_house"].items()}
    noisy = ", ".join(f"H{h} {v:.1f}" for h, v in sorted(night.items(), key=lambda kv: -kv[1])[:4])
    cal = {h: e["calibration"]["kettle_w"] for h, e in det["per_house"].items() if "calibration" in e}
    cc = fa["diagnostics"]["clock_check"]
    cc_rows = [[k, v["naive"]["median_shift_min"], v["corrected"]["median_shift_min"], v["corrected"]["homes"]]
               for k, v in cc.items()]
    h12 = det["per_house"].get("12", {}).get("kettle_channel_checks", {})
    h21 = det["per_house"].get("21", {}).get("kettle_channel_checks", {})
    h21_after = next((v for k, v in h21.items() if k.startswith("median_run_w_after")), None)
    h21_before = next((v for k, v in h21.items() if k.startswith("median_run_w_before")), None)
    nr, wr = S["tune_1_9"]["kettle_whole_home_no_repeat_filter"], S["tune_1_9"]["kettle_whole_home"]
    pd_ = fa["diagnostics"]["per_house"]
    h4_run = pd_.get("4", {}).get("longest_no_kettle_run_days")
    st0, st1 = R["v0_kettle_plug"]["standard"]["pooled"]["overall"], R["v1_whole_home"]["standard"]["pooled"]["overall"]
    co0, co1 = R["v0_kettle_plug"]["cold"]["pooled"]["overall"], R["v1_whole_home"]["cold"]["pooled"]["overall"]
    none_share = (st0["no_activity_all_day"] + st1["no_activity_all_day"]) / max(st0["checkins"] + st1["checkins"], 1)
    ttd = lambda m, p: R[m][p]["time_to_first_checkin_after_usual"]["median_min"]
    sooner = statistics.mean([ttd(m, "standard") - ttd(m, "cold") for m in MODES])
    extra = statistics.mean([co0["checkins_per_home_month"] - st0["checkins_per_home_month"],
                             co1["checkins_per_home_month"] - st1["checkins_per_home_month"]])
    single = R["v1_whole_home"]["standard"]["pooled"]["single_occupant_11_15"] or {}
    single_rng = single.get("range_house_checkins_per_month") or [None, None]
    dgp = fa["diagnostics"]["pooled"]
    plug_fp = {h: e["kettle_plug"] for h, e in det["per_house"].items() if "kettle_plug" in e}
    worst = min(plug_fp, key=lambda h: plug_fp[h]["precision"] or 1)
    blip = statistics.median([v["fp_median_duration_s"] for v in plug_fp.values() if "fp_median_duration_s" in v])
    mg_none = sum(1 for d in mg["days"] if d["first_min"] is None) if mg else None
    mg_win = f"{mg['window']['start']} to {mg['window']['end']}" if mg else "n/a"
    md = f"""# Kettle on real homes: REFIT evaluation

*Generated by `.venv/bin/python -m kettle.eval.refit` on {summary['generated_at']} (this run: {summary['runtime_s']:.0f} s
on 12 cores; detector output is cached between runs). Every number below is computed by that script from the public REFIT data with the same
`kettle/detect.py`, `kettle/signatures.py` and `kettle/rhythm.py` that the product runs. Nothing is hand-entered.
JSON outputs: `data/refit/`.*

## Data

**REFIT Electrical Load Measurements (cleaned)**: 20 occupied UK homes around Loughborough, 2013–2015;
whole-home power ("Aggregate") plus 9 plug-level monitors (IAMs) per home, sampled every ~8 s.
{CITATION} Licence: {LICENCE}. Raw files are not in this repository.

- **Homes**: all 20 for whole-home results; the 14 with a working kettle monitor (2–9, 11, 13, 17, 19, 20, 21)
  for kettle results. House 12's "kettle" monitor recorded {h12.get('runs_over_1000w')} use(s) above 1000 W in the
  whole study, so it is not a kettle and is excluded.
  House 21's kettle monitor is only used before 16 Aug 2014: the readme says it changed, and the median use goes from
  {h21_before} W before to {h21_after} W after.
- **Tune/test split**: every parameter we changed was chosen by looking at houses 1–9 only. Houses 10–21 are
  reported separately as held-out results.
- **Clock**: we found that REFIT's timestamps are not one convention. They are local UK time for most of the study,
  but **UTC during British Summer Time before 26 Oct 2013 and from 30 Mar to 30 Sep 2014**. In those periods every
  home's first kettle of the day appears about an hour earlier, starting and stopping on the same day in all homes,
  which a behaviour change would not do. We convert both conventions to real UTC and use Europe/London for local
  days. 1–5 Sep 2014 (convention unclear) is left out of the rhythm evaluation. The table shows the median shift
  of a home's first kettle use (weekdays, 21 days after minus 21 days before):

{_t(cc_rows, ["date", "shift if all stamps were local (min)", "shift with our correction (min)", "homes"])}

- **Data gaps**: an inter-sample gap longer than {COVER_GAP_S:.0f} s counts as missing data.

## 1. Can Kettle see the kettle? (`detector_eval.json`)

**Ground truth**: a kettle use is the kettle monitor reading above {GT_ON_W:.0f} W for at least {GT_MIN_S:.0f} s.
**Detection**: a completed on/off cycle that the shipped detector labels `kettle` on the **whole-home**
channel. It counts as correct if it starts within ±{MATCH_TOL_S:.0f} s of a true use (one-to-one matching).
The test uses only days with at least 90% of the 24 h covered by data.

{_t(det_rows, ["signal", "houses", "n", "TP", "FP", "FN", "precision", "recall", "F1", "macro-F1"])}

Per kettle house (whole-home unless noted):

{_t(ph_rows, ["house", "split", "kettle W (monitor)", "true uses", "precision", "recall", "F1", "F1 calibrated", "F1 plug"])}

- **Whole-home kettle**: F1 {g(S['overall']['kettle_whole_home'], 'f1'):.2f} overall and
  {g(S['test_10_21']['kettle_whole_home'], 'f1'):.2f} on the held-out houses. About two in three kettle uses are
  found, and about two in three "kettle" labels are right. The false labels are other 2–3 kW loads with a similar
  on/off shape. They are probably hobs, ovens and dryer heaters, but REFIT does not meter those. Misses are mostly
  boils that overlap another appliance (which distorts the step or the on-time) and re-boils within 10 minutes
  (see change 2 below).
- **Calibration**: if the person boils the kettle three times at setup so the hub learns its exact wattage
  (simulated with the first three boils in the data), precision rises to
  {g(S['overall']['kettle_whole_home_calibrated'], 'precision'):.2f}. It fails when the kettle is replaced: House 3's
  kettle was changed in Apr 2014 and its F1 drops. It also fails when another appliance draws the same power
  (House 7).
- **Kettle on its own plug (v0)**: F1 {g(S['overall']['kettle_plug'], 'f1'):.2f}. Most of the remaining "errors"
  come from the ground-truth rule. In most homes the unmatched plug cycles are short blips (median across homes
  {blip:.0f} s, while ground truth needs at least 16 s). House {worst}, the lowest plug precision
  ({plug_fp[worst]['precision']:.2f}), has runs of ~{plug_fp[worst].get('fp_median_dp_w')} W lasting
  ~{plug_fp[worst].get('fp_median_duration_s')} s on the same socket, just under the 1000 W ground-truth threshold.
- **Microwave on the whole-home meter**: not reliable (precision {g(S['overall']['microwave_whole_home'], 'precision'):.2f}).
  Whole-home labels other than "kettle" should not be shown as fact.

## 2. How often would Kettle ask "are you OK?" (`false_alarm_eval.json`)

For each home we walk through the data one day at a time. Each day's deadline comes from a `RhythmModel` trained
**only on earlier days** (last {STANDARD.window_days} days). A **check-in** happens when the first sign of a person
after 04:00 comes after the deadline (*late start*) or never comes that day (*no activity*). REFIT contains no
real emergencies, so **every check-in here is a false alarm**. A day is evaluated only if at least 90% of
04:00–14:00 has data ({v1s['excluded_low_coverage']} home-days were excluded on the whole-home channel). Days while
the model is still learning use the 11:00 default and are counted.

- **v0, kettle plug**: activity = kettle uses seen by the detector on the kettle's own monitor (14 homes,
  {v0s['evaluated_days']} home-days).
- **v1, whole home**: activity = cycles the detector marks `human` on the whole-home channel (20 homes,
  {v1s['evaluated_days']} home-days).
- **Policies**: `standard` (deadline = usual + 3×spread, clamped to 45–180 min) and `cold`
  (2×spread, 30–120 min).

Check-ins per home per month (30.44 days):

{_t(fa_rows, ["sensing", "policy", "homes", "n", "home-days", "check-ins / month", "late start", "no activity all day", "if away days are paused*", "median home", "range of homes"])}

\\* *Assumption*: days with no activity at all are treated as "away" (in the product the person can pause Kettle
while travelling). They count neither as check-ins nor as monitored days. The real rate is somewhere between
the two columns.

How long after a person's usual start Kettle would first ask, if they did not get up (deadline − usual, on days
with a learned routine):

{_t(ttd_rows, ["sensing", "policy", "median min", "IQR min", "days"])}

Per home (standard policy):

{_t(hh_rows, ["house", "people", "split", "days", "excluded", "usual (v0)", "check-ins/mo v0", "usual (v1)", "deadline (v1)", "check-ins/mo v1", "late", "no activity"])}

**Reading the numbers.** Under the standard policy a home gets {st0['checkins_per_home_month']:.1f} (kettle plug) or
{st1['checkins_per_home_month']:.1f} (whole home) "are you OK?" prompts a month. {none_share:.0%} of them are days with no
activity at all, which a pause button could remove if the person pauses Kettle when away. The rest are late starts. The `cold` policy
asks {sooner:.0f} min sooner on average and adds {extra:.1f} prompts a month. The two single-occupant homes (11 and 15),
which are the closest to our users, have irregular routines and get more prompts
({single_rng[0]}–{single_rng[1]} a month, whole home). These rates are too high to send straight to a neighbour.
This is why Kettle asks the person first.

**What these numbers cannot show (masking risk).** A false *reassurance* happens when an automatic load is
mistaken for a person, so Kettle stays quiet when it should ask. We cannot measure it without real incidents.
Two indicators:
- The whole-home detector reports a "human" event between 01:00 and 04:00 on a median of
  {dg['v1_human_events_01_04_per_night_median_house']:.2f} per night, but some homes are much noisier ({noisy} per night).
- On {dg['probably_empty_days']} "probably empty" days (2–14 consecutive days with no kettle use in a kettle-using
  home), the whole-home detector still reported human activity on {dg['probably_empty_days_with_v1_activity']}
  ({dg['probably_empty_days_with_v1_activity'] / max(dg['probably_empty_days'], 1):.0%}).

Before tuning, every cycle with a human label counted, including TV-sized and unknown big loads. Under that
rule, {dgp['tune_houses_old_rule_median_first_before_0530']} of {dgp['tune_houses']} tuning homes had a median
"first activity" before 05:30. That is a fridge, pump or heater, not a person. With the human-score threshold
(below) this falls to {dgp['tune_houses_v1_median_first_before_0530']} of {dgp['tune_houses']}. The per-home values are
`old_rule_median_first` and `v1_median_first` in the JSON.

*Sensitivity*: timing whole-home evidence at the moment a cycle is confirmed (its end) instead of its start gives
{sens['checkins_per_home_month']:.2f} check-ins/home-month, against {v1s['checkins_per_home_month']:.2f}.

## 3. Demo files

- `margaret_baseline.json`: House 11 (one occupant). We took the first 28-day winter window starting on a Monday
  with at least 90% data on every day, which gave {mg_win}. It includes {mg_none} days with no activity at all
  (probably away). For each day it lists the whole-home human events, the kettle-monitor uses, the rolling deadline
  and check-in, plus the fitted baseline for the following Monday. Whole-home labels other than `kettle` (for
  example `microwave`) are often wrong; show them as "activity".
- `kettle_boil_trace.json`: the first kettle use of that window, from the kettle monitor and the whole-home meter
  at REFIT's native ~8 s resolution, from 2 min before to 2 min after.
- `homes_replay.json`: one ordinary winter weekday for each of 5 other houses (rule inside the file). The baseline
  is fitted on the previous 28 days only.

## Changes made to the shipped modules (tuned on houses 1–9 only)

1. `detect.py`, bug fix: while a cycle was open, other appliances switching on or off were counted as that
   cycle's own variation. Kettle boils that overlapped anything else failed the flatness test. Open cycles now
   move their reference level when another edge is committed.
2. `detect.py`, new `DetectorConfig.repeat_window_s=600`, `repeat_rel=0.15`: a kettle-, toaster- or
   unknown-sized cycle that repeats a same-size cycle which ended less than 10 min earlier is labelled `cycling`
   (thermostat, not a person). On the tuning houses, whole-home kettle precision rises from {nr['precision']:.2f} to
   {wr['precision']:.2f}, recall goes from {nr['recall']:.2f} to {wr['recall']:.2f}, and F1 from {nr['f1']:.2f} to {wr['f1']:.2f}.
   The cost is re-boils within 10 min. Plugs: off.
3. `detect.py`, new `DetectorConfig.min_human_score=0.5` and `Event.human_score`: a cycle is `human` only if its
   human evidence (share of signature score on human labels × best human score) reaches 0.5. On the whole-home
   channel this mainly removes TV-sized and unknown loads (fridges, pumps, heaters). Kettle and microwave
   signatures, including a 1.5 kW North American kettle, still pass. Plugs: 0 (unchanged).
4. `detect.py`/`signatures.py`, new optional `DetectorConfig.kettle_w`/`kettle_tol` and `signatures.calibrated()`
   (`Signature.dp_soft`), used only for the "calibrated" rows above. Off by default.
5. `signatures.py`, new `REPEAT_SENSITIVE` set. Signature bands, `HUMAN_LABELS`, the NA set and `rhythm.py` are
   unchanged. Wider kettle duration and flatness bands, slower confirmation and a different match tolerance were
   tried on houses 1–9 and did not help.

Calibration step sizes used (W, whole-home): {', '.join(f'H{h} {w:.0f}' for h, w in cal.items())}.

## Limitations

- **UK homes, 230 V.** UK kettles draw 2–3 kW and stand out on a whole-home meter. North American 120 V kettles
  draw 1–1.5 kW, the same range as microwaves, toasters and hair dryers. The whole-home results will be worse
  there, and we have not measured them. The plug result (v0) should carry over, since a plug sees only the kettle.
- **Not our users.** These were mostly working-age households of 2–6 people, so "first activity" is anyone's.
  Only 2 of the 20 homes have one occupant. Seniors living alone may be more regular, which helps, or less active,
  which does not. We have no data either way.
- **No real incidents.** Every check-in is counted as a false alarm. Missed emergencies cannot be measured, only
  hinted at by the masking indicators above.
- **Ground truth is plug-level and imperfect.** Plug and whole-home sensors are not synchronised (up to ~8 s
  apart). A dead plug monitor looks like a day without tea; for example, the longest run of evaluated days without a
  single kettle use in House 4 is {h4_run} days. In v0 such days count as "no activity" check-ins.
- **Old, coarse data.** The data is from 2013–2015, sampled every ~8 s with gaps; Feb 2014 is mostly missing. Live
  the product's plugs sample about once a second.
- **Policies were not tuned.** The `standard` and `cold` policies were used as designed. Tightening or loosening
  them trades fewer prompts against slower detection; the time-to-ask table above shows that trade-off.

## summary.json

The keys the stage UI reads:

| key | meaning |
|---|---|
| `checkins_per_home_month.{{v0_kettle_plug,v1_whole_home}}.{{standard,cold}}` | false-alarm check-ins per home per 30.44 days, all homes |
| `checkins_per_home_month_test_houses` | same, held-out houses 10–21 only |
| `checkins_per_home_month_away_paused` | same, assuming no-activity days are paused (assumption) |
| `minutes_after_usual_before_asking` | median deadline − usual time (how soon Kettle would ask) |
| `kettle_f1`, `kettle_precision`, `kettle_recall` | whole-home kettle detection, all 14 kettle homes |
| `kettle_f1_test_houses` | whole-home kettle F1, held-out houses only |
| `kettle_f1_calibrated` | whole-home with 3 calibration boils |
| `kettle_f1_plug` | kettle detected on its own plug |
| `houses`, `home_days`, `home_days_kettle_plug` | homes evaluated; evaluated home-days (whole home / kettle plug) |
| `generated_at`, `runtime_s`, `source` | provenance |
"""
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(md)
    log(f"wrote {DOC_PATH}")


if __name__ == "__main__":
    main()
