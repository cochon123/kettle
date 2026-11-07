"""A clock that can run in real time or as an openly-labelled accelerated demo clock."""

from __future__ import annotations

import datetime as dt
import time
from zoneinfo import ZoneInfo

CALGARY = ZoneInfo("America/Edmonton")


class Clock:
    def __init__(self, tz: dt.tzinfo = CALGARY):
        self.tz = tz
        self.demo = False
        self.speed = 1.0
        self._real0 = time.time()
        self._sim0 = self._real0

    def now(self) -> float:
        if not self.demo:
            return time.time()
        return self._sim0 + (time.time() - self._real0) * self.speed

    def local(self, t: float | None = None) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.now() if t is None else t, self.tz)

    def set(self, t: float, speed: float | None = None) -> None:
        self.demo = True
        self._real0, self._sim0 = time.time(), t
        if speed is not None:
            self.speed = speed

    def set_speed(self, speed: float) -> None:
        self.set(self.now(), speed)

    def set_local(self, date: dt.date, hhmm: str, speed: float | None = None) -> None:
        h, m = (int(x) for x in hhmm.split(":"))
        self.set(dt.datetime.combine(date, dt.time(h, m), self.tz).timestamp(), speed)

    def real(self) -> None:
        self.demo, self.speed = False, 1.0

    def to_dict(self) -> dict:
        loc = self.local()
        return {"t": self.now(), "demo": self.demo, "speed": self.speed,
                "local": loc.isoformat(timespec="seconds"), "hhmm": loc.strftime("%-H:%M"),
                "date": loc.date().isoformat(), "tz": str(self.tz)}
