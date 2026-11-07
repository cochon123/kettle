"""Personal rhythm model.

Learns, per person, when their day usually starts ("first human activity
after 04:00"), separately for weekdays and weekends when there is enough data.
It is robust by construction: median and MAD instead of mean and standard
deviation, so one late night or one early flight doesn't move the baseline.

The output is a *deadline*: the time after which "no activity yet" becomes
unusual enough to ask. Every deadline comes with a human sentence explaining it.

    usual = median(first activity)
    spread = max(1.4826 * MAD, min_spread)
    deadline = usual + clamp(k * spread, min_margin, max_margin)

Cold mode tightens k and the margins.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field, asdict

DAY_START_MIN = 4 * 60  # a "day" starts at 04:00 local time


@dataclass(frozen=True)
class Policy:
    name: str = "standard"
    k: float = 3.0
    min_margin_min: float = 45.0
    max_margin_min: float = 180.0
    min_spread_min: float = 10.0
    learn_days: int = 5
    window_days: int = 28
    min_type_days: int = 4
    default_deadline_min: float = 11 * 60.0   # used while still learning


STANDARD = Policy()
COLD = Policy(name="cold", k=2.0, min_margin_min=30.0, max_margin_min=120.0)
POLICIES = {"standard": STANDARD, "cold": COLD}


@dataclass
class DayObs:
    date: dt.date
    first_min: float | None          # minutes after midnight of first human activity, None = no activity
    first_label: str | None = None   # what it was (kettle, tv, ...)

    @property
    def weekend(self) -> bool:
        return self.date.weekday() >= 5


@dataclass
class Baseline:
    learned: bool
    kind: str                 # "weekday" | "weekend" | "all" | "learning"
    n: int
    usual_min: float | None
    spread_min: float | None
    margin_min: float
    deadline_min: float
    policy: str
    days_needed: int = 0
    history: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["usual"] = fmt_min(self.usual_min) if self.usual_min is not None else None
        d["deadline"] = fmt_min(self.deadline_min)
        d["spread"] = round(self.spread_min) if self.spread_min is not None else None
        d["sentence"] = self.sentence()
        return d

    def sentence(self) -> str:
        if not self.learned:
            return (f"Still learning ({self.n} of {self.n + self.days_needed} days). "
                    f"Until then Kettle waits until {fmt_min(self.deadline_min)} before asking.")
        day = {"weekday": "on weekdays", "weekend": "on weekends", "all": ""}[self.kind]
        return (f"First activity usually {fmt_min(self.usual_min)} ± {round(self.spread_min)} min {day}".strip()
                + f". Kettle asks if nothing by {fmt_min(self.deadline_min)}.")


def fmt_min(m: float | None) -> str:
    if m is None:
        return "–"
    m = int(round(m)) % (24 * 60)
    return f"{m // 60}:{m % 60:02d}"


def mad(xs: list[float]) -> float:
    med = statistics.median(xs)
    return statistics.median([abs(x - med) for x in xs])


class RhythmModel:
    def __init__(self, policy: Policy = STANDARD):
        self.policy = policy
        self.days: list[DayObs] = []

    def fit(self, days: list[DayObs]) -> "RhythmModel":
        self.days = sorted(days, key=lambda d: d.date)
        return self

    def observe(self, day: DayObs) -> None:
        self.days = [d for d in self.days if d.date != day.date] + [day]
        self.days.sort(key=lambda d: d.date)

    def baseline(self, date: dt.date, policy: Policy | None = None) -> Baseline:
        p = policy or self.policy
        start = date - dt.timedelta(days=p.window_days)
        window = [d for d in self.days if start <= d.date < date and d.first_min is not None]
        if len(window) < p.learn_days:
            return Baseline(False, "learning", len(window), None, None, 0.0, p.default_deadline_min,
                            p.name, days_needed=p.learn_days - len(window))
        weekend = date.weekday() >= 5
        same = [d.first_min for d in window if d.weekend == weekend]
        if len(same) >= p.min_type_days:
            xs, kind = same, ("weekend" if weekend else "weekday")
        else:
            xs, kind = [d.first_min for d in window], "all"
        usual = statistics.median(xs)
        spread = max(1.4826 * mad(xs), p.min_spread_min)
        margin = min(max(p.k * spread, p.min_margin_min), p.max_margin_min)
        return Baseline(True, kind, len(xs), usual, spread, margin, usual + margin, p.name, history=xs)

    def explain_missing(self, date: dt.date, now_min: float, policy: Policy | None = None,
                        what: str = "No kettle, no lights") -> str:
        b = self.baseline(date, policy)
        if not b.learned:
            return f"{what} by {fmt_min(now_min)}. Kettle is still learning this routine."
        return f"{what} by {fmt_min(now_min)}. Usually {fmt_min(b.usual_min)}."


def first_activity_by_day(events: list[tuple[float, str]], tz: dt.tzinfo) -> dict[dt.date, tuple[float, str]]:
    """events: (unix_t, label) of *human* events. Returns {day: (minutes after midnight, label)}.

    A day runs 04:00 -> 04:00, so a 01:30 cup of tea belongs to the previous day.
    """
    out: dict[dt.date, tuple[float, str]] = {}
    for t, label in sorted(events):
        local = dt.datetime.fromtimestamp(t, tz)
        mins = local.hour * 60 + local.minute + local.second / 60
        day = local.date()
        if mins < DAY_START_MIN:
            continue  # night-time activity is not "the morning started"
        if day not in out:
            out[day] = (mins, label)
    return out
