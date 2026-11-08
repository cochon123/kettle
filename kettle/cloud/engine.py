"""The Kettle cloud engine.

Receives appliance *events* from homes (never raw power), keeps each person's
rhythm model, decides when a day looks wrong, runs the escalation and talks to
the circle. Everything time-related goes through `Clock`, so the demo can be
scrubbed and accelerated openly.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import itertools
import json
import logging
import pathlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..clock import Clock
from ..escalation import DEMO, PRODUCTION, Escalation, Member, Step, Timings, PRONOUNS
from ..rhythm import COLD, DAY_START_MIN, STANDARD, DayObs, RhythmModel, fmt_min
from .grid import COLD_C, Grid
from .notify import Notifier
from .store import Store

log = logging.getLogger("kettle.engine")
ROOT = pathlib.Path(__file__).resolve().parents[2]
Send = Callable[[dict], Awaitable[None]]

ICON = {"kettle": "☕", "microwave": "🍲", "toaster": "🍞", "tv": "📺", "furnace_blower": "🔥"}
NICE = {"kettle": "kettle", "microwave": "microwave", "toaster": "toaster", "tv": "TV", "activity": "activity",
        "furnace_blower": "furnace", "human_unknown": "an appliance", "cooking": "stove"}


def kettle_day(local: dt.datetime) -> dt.date:
    """Kettle days run 04:00 -> 04:00."""
    return (local - dt.timedelta(minutes=DAY_START_MIN)).date()


def minutes(local: dt.datetime) -> float:
    m = local.hour * 60 + local.minute + local.second / 60
    return m if m >= DAY_START_MIN else m + 24 * 60


@dataclass
class Home:
    id: str
    person: str
    pronoun: str
    kind: str                         # "live" (a real Kettle device) | "replay" (REFIT household replay)
    label: str
    pos: dict
    area: str
    sensing: str = "v0"               # v0 kettle plug | v1 whole-home meter
    circle: list[Member] = field(default_factory=list)
    model: RhythmModel = field(default_factory=RhythmModel)
    seed_days: list[dict] = field(default_factory=list)    # REFIT days used to seed the model
    seed_source: dict | None = None
    replay_events: list[dict] = field(default_factory=list)  # [{min,label,...}] replayed by time of day
    replay_baseline: dict | None = None
    day: dt.date | None = None
    events: list[dict] = field(default_factory=list)       # today's events (and a little of yesterday)
    first_today: dict | None = None
    escalation: Escalation | None = None
    past: list[dict] = field(default_factory=list)          # resolved escalations today
    asked_today: bool = False
    paused_until: float | None = None
    device_online: bool = False
    device_seen: float | None = None
    device_info: dict = field(default_factory=dict)
    offline_since: float | None = None
    dark_notified: bool = False
    last_blower_t: float | None = None
    glow: dict | None = None
    ringing_until: float | None = None
    replay_cursor: int = 0
    heat_asked_day: dt.date | None = None

    @property
    def p(self) -> dict:
        return PRONOUNS.get(self.pronoun, PRONOUNS["they"])


class Engine:
    def __init__(self, clock: Clock, notifier: Notifier, store: Store, grid: Grid, demo: bool = True):
        self.clock, self.notifier, self.store, self.grid = clock, notifier, store, grid
        self.timings: Timings = DEMO if demo else PRODUCTION
        self.homes: dict[str, Home] = {}
        self.members: dict[str, dict] = {}            # id -> {member, home_ids, pos, avatar}
        self.notes: dict[str, list[dict]] = {}         # member id -> notifications, newest first
        self.outbox: deque[dict] = deque(maxlen=80)    # everything sent, for the stage + audit
        self.flashes: deque[dict] = deque(maxlen=30)   # transient animations for the stage
        self.devices: dict[str, Send] = {}
        self.circle_conns: dict[str, set[Send]] = {}
        self.stage_conns: set[Send] = set()
        self.cold_mode = "auto"
        self.grid_check: dict | None = None
        self.refit = self._load_json("data/refit/summary.json")
        self._note_ids = itertools.count(1)
        self._dirty_members: set[str] = set()
        self._glow_last: dict[str, float] = {}
        self.offline_grace_s = 8.0 if demo else 120.0
        # In a cold snap a gas furnace's blower cycles every few minutes; this long without one is unusual.
        self.blower_gap_s = 90 * 60.0

    # ================================================================== setup
    @staticmethod
    def _load_json(rel: str) -> Any:
        p = ROOT / rel
        try:
            return json.loads(p.read_text()) if p.exists() else None
        except Exception as e:
            log.warning("could not read %s: %s", rel, e)
            return None

    def add_member(self, m: Member, home_ids: list[str], pos: dict, avatar: str = "") -> None:
        self.members[m.id] = {"member": m, "home_ids": home_ids, "pos": pos, "avatar": avatar or m.name[:1]}
        self.notes.setdefault(m.id, [])
        for hid in home_ids:
            h = self.homes[hid]
            if all(x.id != m.id for x in h.circle):
                h.circle.append(m)

    def setup_demo(self) -> None:
        """Margaret's live home + her circle, and REFIT households replayed on the map."""
        margaret = Home(id="margaret", person="Margaret", pronoun="she", kind="live",
                        label="Live Kettle device (kettle plug)", pos={"x": 548, "y": 300}, area="Bridgeland")
        self.homes[margaret.id] = margaret
        self._seed_margaret(margaret)
        circle = [
            (Member("priya", "Priya", "neighbour", "next door", "+15875550142", 2), {"x": 574, "y": 286}, "P"),
            (Member("tom", "Tom", "neighbour", "across the street", "+15875550199", 4), {"x": 512, "y": 334}, "T"),
            (Member("daniel", "Daniel", "family", "son, in Edmonton", "+17805550123", None), {"x": 640, "y": 40}, "D"),
        ]
        for m, pos, av in circle:
            self.add_member(m, ["margaret"], pos, av)

        replay = self._load_json("data/refit/homes_replay.json") or {}
        houses = replay.get("homes") or replay.get("houses") or (replay if isinstance(replay, list) else [])
        spots = [({"x": 300, "y": 210}, "Bowness"), ({"x": 690, "y": 420}, "Inglewood"),
                 ({"x": 420, "y": 470}, "Killarney"), ({"x": 760, "y": 200}, "Renfrew"),
                 ({"x": 230, "y": 380}, "Wildwood"), ({"x": 620, "y": 520}, "Ramsay")]
        for i, hh in enumerate(houses[:len(spots)]):
            pos, area = spots[i]
            hid = f"refit{hh.get('house')}"
            occ = hh.get("occupants", hh.get("occupancy"))
            label = f"REFIT House {hh.get('house')}, real UK household" + (f" ({occ} occupant{'s' if occ != 1 else ''})" if occ else "")
            home = Home(id=hid, person=f"House {hh.get('house')}", pronoun="they", kind="replay", label=label,
                        pos=pos, area=area, sensing="v1",
                        replay_events=sorted(hh.get("events", []), key=lambda e: e.get("min", 0)),
                        replay_baseline=hh.get("baseline"))
            home.seed_source = {"house": hh.get("house"), "date": hh.get("date")}
            self.homes[hid] = home

    def _seed_margaret(self, h: Home) -> None:
        data = self._load_json("data/refit/margaret_baseline.json")
        if not data:
            log.warning("data/refit/margaret_baseline.json missing: Margaret starts in learning mode")
            return
        days = data.get("days", [])
        out = []
        for d in days:
            # v0 = what a plug on the kettle would have seen (REFIT's labelled kettle channel)
            uses = d.get("kettle_iam_uses") or d.get("kettle_uses") or []
            mins = [u.get("min") if isinstance(u, dict) else u for u in uses]
            mins = [m for m in mins if m is not None and m >= DAY_START_MIN]
            first = d.get("v0_first_min") if d.get("v0_first_min") is not None else (min(mins) if mins else None)
            kettle_events = [{"min": u.get("min"), "label": "kettle", "dp_w": u.get("dp_w"),
                              "duration_s": u.get("duration_s")} for u in uses if isinstance(u, dict)]
            out.append({"date": d.get("date"), "first_min": first, "first_label": "kettle" if first else None,
                        "events": kettle_events, "events_v1": d.get("events", []),
                        "first_any": d.get("first_min"), "first_any_label": d.get("first_label")})
        h.seed_days = out
        h.seed_source = {"house": data.get("house", 11), "occupants": data.get("occupants"),
                         "window": data.get("window"), **(data.get("provenance") or {})}
        self._reseed(h, kettle_day(self.clock.local()))

    def _reseed(self, h: Home, today: dt.date) -> None:
        """Place the seeded REFIT days as 'the last N days' before today, keeping weekdays aligned."""
        if not h.seed_days:
            return
        try:
            last = max(dt.date.fromisoformat(d["date"]) for d in h.seed_days)
        except Exception:
            return
        shift_days = (today - last).days - 1
        shift_days -= shift_days % 7          # whole weeks, so Mondays stay Mondays
        obs = [DayObs(dt.date.fromisoformat(d["date"]) + dt.timedelta(days=shift_days), d["first_min"], d["first_label"])
               for d in h.seed_days if d.get("first_min") is not None]
        h.model.fit(obs)

    # ================================================================== helpers
    def policy(self):
        return COLD if self.cold_active() else STANDARD

    def cold_info(self) -> dict:
        wx = self.weather()
        temp = wx.get("temp_c")
        alert = self.grid.cold_alert() if not self.grid.replay.active else None
        auto = (temp is not None and temp <= COLD_C) or alert is not None
        active = self.cold_mode == "on" or (self.cold_mode == "auto" and auto)
        if self.cold_mode == "on":
            reason = "Cold mode switched on"
        elif alert:
            reason = f"Environment Canada: {alert.get('headline')}"
        elif temp is not None and temp <= COLD_C:
            reason = f"{temp:g} °C in Calgary (cold mode at {COLD_C:g} °C or below)"
        else:
            reason = None
        return {"mode": self.cold_mode, "active": active, "reason": reason, "temp_c": temp,
                "wind_chill": wx.get("wind_chill"), "threshold_c": COLD_C}

    def cold_active(self) -> bool:
        return self.cold_info()["active"]

    def weather(self) -> dict:
        if self.grid.replay.active:
            w = (self.grid.replay.at(self.clock.now()) or {}).get("weather") or {}
            return {"temp_c": w.get("temp_c"), "wind_chill": w.get("wind_chill"),
                    "source": "ECCC archive, CALGARY INTL A", "observed": w.get("t")}
        return self.grid.weather

    def baseline(self, h: Home, date: dt.date | None = None) -> dict:
        date = date or kettle_day(self.clock.local())
        if h.kind == "replay" and h.replay_baseline:
            return h.replay_baseline
        return h.model.baseline(date, self.policy()).to_dict()

    def _sentence(self, h: Home, ev: dict) -> str:
        label = ev.get("label", "")
        name = NICE.get(label, label.replace("_", " "))
        icon = ICON.get(label, "")
        if label == "kettle":
            return f"{h.person}'s kettle just boiled {icon}" if ev.get("kind") == "cycle" else f"{h.person}'s kettle just came on {icon}"
        if label == "tv":
            return f"{h.person}'s TV just came on {icon}"
        if label == "activity":
            return f"Activity at {h.person}'s home"
        return f"{h.person} just used the {name} {icon}".strip()

    def _now_min(self) -> tuple[dt.date, float]:
        loc = self.clock.local()
        return kettle_day(loc), minutes(loc)

    # ================================================================== inputs
    async def device_hello(self, home_id: str, send: Send, info: dict) -> None:
        h = self.homes.get(home_id)
        if not h:
            return
        self.devices[home_id] = send
        h.device_online, h.device_seen, h.device_info = True, time.time(), info
        if h.offline_since and h.dark_notified:
            self._log_out("device", h.person, f"{h.person}'s Kettle is back online.", "ws")
        h.offline_since, h.dark_notified = None, False
        await send({"type": "clock", **self.clock.to_dict()})
        if h.escalation and h.escalation.active and h.escalation.step == Step.CHECK_SELF:
            await send({"type": "checkin", "text": f"Press here if you're fine, {h.person}."})
        await self.broadcast()

    async def device_gone(self, home_id: str, send: Send) -> None:
        if self.devices.get(home_id) is send:
            self.devices.pop(home_id, None)
            h = self.homes.get(home_id)
            if h:
                h.device_online, h.offline_since = False, time.time()
            await self.broadcast()

    async def device_heartbeat(self, home_id: str) -> None:
        h = self.homes.get(home_id)
        if h:
            h.device_seen = time.time()

    async def ingest(self, home_id: str, ev: dict, source: str = "device") -> None:
        h = self.homes.get(home_id)
        if not h:
            return
        ev = dict(ev)
        ev["source"] = source
        if self.clock.demo and source == "device":
            # Device clocks are real time; in demo mode we place the event on the demo clock.
            ev["t_device"] = ev.get("t")
            dur = ev.get("duration_s")
            ev["t"] = self.clock.now()
            if ev.get("t_on") is not None:
                ev["t_on"] = ev["t"] - (dur or 0)
        loc = self.clock.local(ev["t"])
        ev["hhmm"] = loc.strftime("%-H:%M")
        ev["min"] = round(minutes(loc), 1)
        ev["text"] = self._sentence(h, ev)
        h.events.append(ev)
        h.events = h.events[-200:]
        await self.store.event(home_id, ev)
        if ev.get("label") == "furnace_blower":
            h.last_blower_t = ev["t"]
        if ev.get("human"):
            day, _ = self._now_min()
            if h.first_today is None and kettle_day(loc) == day and ev["min"] >= DAY_START_MIN:
                h.first_today = {"t": ev["t"], "hhmm": ev["hhmm"], "min": ev["min"], "label": ev.get("label")}
            if h.escalation and h.escalation.active:
                await self.run(h, h.escalation.on_activity(ev["t"], ev.get("label", ""), ev["text"]))
            elif ev.get("label") == "kettle" and ev.get("kind") == "cycle" and h.past:
                # The follow-up everyone is waiting for: "...just boiled".
                last = h.past[-1]
                if ev["t"] - (last.get("resolved_at") or 0) < 15 * 60:
                    for mid in set(last.get("asked", [])) | {m.id for m in h.circle if m.role == "family"}:
                        self._note(mid, {"kind": "resolved", "title": ev["text"], "body": "All good. Thank you for being there.",
                                         "buttons": [], "home_id": h.id, "escalation": last["id"]})
            self.flashes.append({"type": "activity", "home": h.id, "label": ev.get("label"), "t": time.time(),
                                 "text": ev["text"], "kind": ev.get("kind")})
        await self.broadcast()

    async def self_ok(self, home_id: str, via: str = "device") -> None:
        h = self.homes.get(home_id)
        if h and h.escalation and h.escalation.active:
            await self.run(h, h.escalation.on_self_ok(self.clock.now(), via))
            await self.broadcast()

    async def respond(self, member_id: str, escalation_id: int, response: str) -> dict:
        for h in self.homes.values():
            e = h.escalation
            if e and e.id == escalation_id:
                for n in self.notes.get(member_id, []):
                    if n.get("escalation") == escalation_id and n.get("buttons"):
                        n["answered"] = response
                if not e.active:
                    return {"ok": True, "note": "already resolved"}
                await self.run(h, e.on_response(self.clock.now(), member_id, response))
                self._dirty_members.add(member_id)
                await self.broadcast()
                return {"ok": True, "step": e.step.value}
        return {"ok": False, "error": "no such active alert"}

    async def glow(self, member_id: str, home_id: str) -> dict:
        h, info = self.homes.get(home_id), self.members.get(member_id)
        if not (h and info):
            return {"ok": False}
        now = time.time()
        if now - self._glow_last.get(member_id, 0) < 10:
            return {"ok": True, "throttled": True}
        self._glow_last[member_id] = now
        name = info["member"].name
        h.glow = {"from": name, "member": member_id, "until": now + 60}
        dev = self.devices.get(home_id)
        if dev:
            await dev({"type": "glow", "from": name, "text": f"{name} is thinking of you"})
        self._log_out("device", h.person, f"Warm glow in {h.person}'s kitchen: “{name} is thinking of you.”", "ws")
        self.flashes.append({"type": "thread", "from": member_id, "to": home_id, "t": now, "kind": "glow"})
        await self.broadcast()
        return {"ok": True, "delivered": bool(dev)}

    async def set_pause(self, home_id: str, hours: float | None) -> None:
        h = self.homes.get(home_id)
        if not h:
            return
        h.paused_until = None if not hours else self.clock.now() + hours * 3600
        txt = (f"{h.person} paused Kettle until {self.clock.local(h.paused_until).strftime('%a %-H:%M')}."
               if h.paused_until else f"{h.person} switched Kettle back on.")
        for m in h.circle:
            self._note(m.id, {"kind": "info", "title": txt, "body": "", "buttons": [], "home_id": h.id})
        await self.broadcast()

    def join(self, name: str, home_id: str = "margaret") -> Member:
        """Join a circle from an invite link (e.g. a judge's phone). Joins as the nearest neighbour."""
        base = "".join(c for c in name.lower() if c.isalnum())[:12] or "guest"
        mid, i = base, 2
        while mid in self.members:
            mid, i = f"{base}{i}", i + 1
        m = Member(mid, name.strip()[:24] or "Guest", "neighbour", "joined by invite", None, 1)
        h = self.homes[home_id]
        self.add_member(m, [home_id], {"x": h.pos["x"] - 30, "y": h.pos["y"] - 26}, name[:1].upper())
        return m

    # ================================================================== the loop
    async def run(self, h: Home, actions: list[dict]) -> None:
        for a in actions:
            t = a["type"]
            if t == "call_person":
                # timings are demo-clock seconds; the ring animation runs in real seconds
                h.ringing_until = time.time() + max((self.timings.self_s - 2) / max(self.clock.speed, 1e-6), 1.0)
                r = await self.notifier.call(getattr(self, "person_phone", {}).get(h.id), a["text"],
                                             gather_path=f"/twilio/gather/{h.id}")
                self._log_out("voice", h.person, a["text"], r["via"])
                self.flashes.append({"type": "ring", "home": h.id, "t": time.time()})
            elif t == "device":
                dev = self.devices.get(h.id)
                if dev:
                    await dev({"type": a["cmd"], "text": a.get("text", "")})
                if a["cmd"] == "checkin_end":
                    h.ringing_until = None
                if a["cmd"] in ("checkin",):
                    self._log_out("device", h.person, a.get("text", ""), "ws" if dev else "offline")
            elif t == "notify":
                self._note(a["member"], {k: a[k] for k in ("kind", "title", "body", "buttons", "escalation", "home_id")})
                m = self.members.get(a["member"], {}).get("member")
                if m and a["kind"] in ("ask", "ask_family", "welfare", "need_help", "grid", "dark", "heat"):
                    link = f"{self.notifier.public_url}/circle/?m={m.id}" if self.notifier.public_url else ""
                    r = await self.notifier.sms(m.phone, f"{a['title']} {a['body']} {link}".strip())
                    self._log_out("sms", m.name, a["title"], r["via"])
                elif m:
                    self._log_out("push", m.name, a["title"], "ws")
            elif t == "thread":
                self.flashes.append({"type": "thread", "from": a["from"], "to": a["to"], "t": time.time(), "kind": "going"})
        e = h.escalation
        if e:
            await self.store.escalation(e.to_dict())
            if not e.active and (not h.past or h.past[-1]["id"] != e.id):
                h.past.append(e.to_dict())

    def _note(self, member_id: str, note: dict) -> None:
        if member_id not in self.notes:
            return
        note = dict(note, id=next(self._note_ids), t=self.clock.now(), t_real=time.time(),
                    hhmm=self.clock.local().strftime("%-H:%M"))
        if note.get("kind") in ("resolved",) and note.get("escalation"):
            for n in self.notes[member_id]:   # close any open question about this alert
                if n.get("escalation") == note["escalation"] and n.get("buttons") and not n.get("answered"):
                    n["answered"] = "closed"
        self.notes[member_id].insert(0, note)
        del self.notes[member_id][40:]
        self._dirty_members.add(member_id)

    def _log_out(self, channel: str, to: str, text: str, via: str) -> None:
        self.outbox.appendleft({"t": self.clock.now(), "hhmm": self.clock.local().strftime("%-H:%M"),
                                "channel": channel, "to": to, "text": text, "via": via})

    async def tick(self) -> None:
        now = self.clock.now()
        loc = self.clock.local()
        day, now_min = kettle_day(loc), minutes(loc)
        for h in self.homes.values():
            if h.day != day:
                self._new_day(h, day)
            if h.kind == "replay":
                self._advance_replay(h, now_min)
                continue
            # device presence: a dark Kettle in a cold snap is itself a reason to check
            if (not h.device_online and h.offline_since and not h.dark_notified and self.cold_active()
                    and time.time() - h.offline_since > self.offline_grace_s and h.circle):
                h.dark_notified = True
                await self._broadcast_check(h, "dark",
                    f"{h.person}'s Kettle lost power at {self.clock.local(now - (time.time() - h.offline_since)).strftime('%-H:%M')}.",
                    f"{h.p['poss'].capitalize()} home may be without heat. It's {self._temp_str()} outside.")
            paused = h.paused_until and now < h.paused_until
            if (h.sensing == "v1" and self.cold_active() and h.last_blower_t and not paused
                    and now - h.last_blower_t > self.blower_gap_s and h.heat_asked_day != day and h.circle):
                h.heat_asked_day = day
                mins = int((now - h.last_blower_t) / 60)
                await self._broadcast_check(h, "heat",
                    f"{h.person}'s furnace hasn't run for {mins // 60} h {mins % 60:02d} min.",
                    f"It's {self._temp_str()} outside. The heat may be off. Can someone check {h.p['obj']} home is warm?")
            e = h.escalation
            if e and e.active:
                await self.run(h, e.tick(now))
            elif not paused and h.first_today is None and not h.asked_today and h.circle:
                b = h.model.baseline(day, self.policy())
                if now_min >= b.deadline_min:
                    await self._start_morning(h, b, now, now_min)
        for item in self.grid.replay.due(now):
            self.flashes.append({"type": "timeline", "t": time.time(), "item": item})
            if "Emergency text alert" in item["text"]:
                for h in self.homes.values():
                    if h.circle and h.kind == "live":
                        last = h.events[-1] if h.events else None
                        lastline = f"Last activity: {NICE.get(last['label'], last['label'])} at {last['hhmm']}." if last else "No activity seen yet today."
                        await self._broadcast_check(h, "grid",
                            f"Alberta grid emergency: rotating outages possible. It's {self._temp_str()}.",
                            f"{h.person} lives alone. {lastline} A quick call or knock tonight would help.")
        await self.broadcast()

    def _temp_str(self) -> str:
        t = self.weather().get("temp_c")
        return f"{t:g} °C" if t is not None else "very cold"

    def _new_day(self, h: Home, day: dt.date) -> None:
        if h.day is not None and day == h.day + dt.timedelta(days=1) and h.kind == "live":
            first = h.first_today
            h.model.observe(DayObs(h.day, first["min"] if first else None, first["label"] if first else None))
        elif h.kind == "live" and h.seed_days:
            self._reseed(h, day)        # the demo clock jumped: the REFIT seed is "the last 14 days" again
        h.day = day
        h.first_today, h.asked_today, h.past = None, False, []
        h.events = [e for e in h.events if self.clock.now() - e["t"] < 6 * 3600 and kettle_day(self.clock.local(e["t"])) == day]
        if h.escalation and not h.escalation.active:
            h.escalation = None
        h.replay_cursor = 0

    def _advance_replay(self, h: Home, now_min: float) -> None:
        # replay homes: real REFIT events, placed on today's date at their real time of day
        if h.replay_cursor == 0 and h.events and h.events[-1]["min"] > now_min:
            h.events, h.first_today = [], None   # clock went backwards: rewind
        while h.replay_cursor < len(h.replay_events) and h.replay_events[h.replay_cursor].get("min", 0) <= now_min:
            ev = h.replay_events[h.replay_cursor]
            h.replay_cursor += 1
            m = ev.get("min", 0)
            if m < DAY_START_MIN:
                continue
            # Whole-home detection is only trustworthy for the kettle (REFIT: microwave precision 0.09),
            # so everything else is shown honestly as "activity".
            label = "kettle" if ev.get("label") == "kettle" else "activity"
            e = {"t": self.clock.now() - (now_min - m) * 60, "min": m, "hhmm": fmt_min(m), "label": label,
                 "human": True, "kind": "cycle", "dp_w": ev.get("dp_w"), "duration_s": ev.get("duration_s"),
                 "source": "refit-replay"}
            e["text"] = self._sentence(h, e)
            h.events.append(e)
            if h.first_today is None:
                h.first_today = {"t": e["t"], "hhmm": e["hhmm"], "min": m, "label": e["label"]}
        if h.replay_cursor and h.events and h.events[-1]["min"] > now_min + 1:
            h.replay_cursor, h.events, h.first_today = 0, [], None

    async def _start_morning(self, h: Home, b, now: float, now_min: float) -> None:
        what = "No kettle" if h.sensing == "v0" else "No kettle, no lights, no TV"
        expl = (f"{what} by {fmt_min(now_min)}. Usually {fmt_min(b.usual_min)}." if b.learned
                else f"{what} by {fmt_min(now_min)}. (Kettle is still learning {h.p['poss']} routine.)")
        if self.cold_active():
            expl += f" Cold mode: {self._temp_str()}."
        e = Escalation(h.id, h.person, "morning", f"{h.person}'s morning hasn't started.", expl,
                       h.circle, now, self.timings, pronoun=h.pronoun)
        h.escalation, h.asked_today = e, True
        await self.run(h, e.start(now))

    async def _broadcast_check(self, h: Home, reason: str, headline: str, body: str) -> None:
        now = self.clock.now()
        if h.escalation and h.escalation.active:
            return
        e = Escalation(h.id, h.person, reason, headline, body, h.circle, now, self.timings, pronoun=h.pronoun)
        e.step, e.step_since = Step.ASK_NEIGHBOUR, now
        e._log(now, "detect", f"{headline} {body}")
        e.asked = [m.id for m in h.circle]
        h.escalation = e
        acts = [{"type": "device", "cmd": "checkin", "text": f"{h.person}, are you warm and OK? Press here."}] if reason == "grid" else []
        for m in h.circle:
            acts.append({"type": "notify", "member": m.id, "kind": reason, "title": headline, "body": body,
                         "escalation": e.id, "home_id": h.id,
                         "buttons": [{"id": "going", "label": "I'll check on her" if h.pronoun == "she" else "I'll check in", "style": "primary"},
                                     {"id": "all_good", "label": f"I know {h.p['is']} OK", "style": "secondary"}]})
        e.timings = Timings(self_s=10**9, neighbour_s=10**9, going_s=self.timings.going_s, family_s=10**9)
        await self.run(h, acts)

    # ================================================================== demo controls
    async def demo_reset(self, hhmm: str = "6:30", speed: float = 1.0) -> None:
        self.grid.replay.active, self.grid.replay.fired = False, []
        self.cold_mode = "auto"
        today = dt.datetime.now(self.clock.tz).date()
        self.clock.set_local(today, hhmm, speed)
        for h in self.homes.values():
            h.day = None
            h.escalation, h.past, h.glow, h.ringing_until, h.paused_until = None, [], None, None, None
            h.events, h.first_today = [], None
        for mid in self.notes:
            self.notes[mid] = []
            self._dirty_members.add(mid)
        self.outbox.clear()
        self.flashes.clear()
        for dev in self.devices.values():
            await dev({"type": "checkin_end"})
            await dev({"type": "clock", **self.clock.to_dict()})
        await self.tick()

    async def demo_replay(self, speed: float = 240.0, start: str = "17:30") -> None:
        """January 13 2024 in Calgary, with real AESO + ECCC data. At x240 from 17:30, 18:44 arrives in ~18 s."""
        await self.demo_reset()
        self.grid.replay.active, self.grid.replay.fired = True, []
        self.cold_mode = "auto"           # it switches itself on: -29.7 °C at 17:00
        self.clock.set_local(dt.date(2024, 1, 13), start, speed)
        day = kettle_day(self.clock.local())
        for h in self.homes.values():
            h.day = None
            self._new_day(h, day)
            if h.kind == "live":
                h.asked_today = True      # an evening scenario: the morning check isn't the story here
        await self.tick()
        h = self.homes.get("margaret")
        if h and h.seed_days:
            # Margaret's real (REFIT House 11) day so far, so her afternoon isn't empty.
            src = next((d for d in reversed(h.seed_days) if d.get("events")), None)
            now_min = minutes(self.clock.local())
            for ev in (src or {}).get("events", []):
                m = ev.get("min", 0)
                if DAY_START_MIN <= m <= now_min:
                    await self.ingest(h.id, {"t": self.clock.now() - (now_min - m) * 60, "label": ev.get("label"),
                                             "human": True, "kind": "cycle", "dp_w": ev.get("dp_w"),
                                             "duration_s": ev.get("duration_s"), "channel": "kettle"}, source="refit-replay")

    async def demo_clock(self, hhmm: str | None, speed: float | None) -> None:
        if hhmm:
            self.clock.set_local(self.clock.local().date() if not self.clock.local().hour < 4 else kettle_day(self.clock.local()),
                                 hhmm, speed)
        elif speed is not None:
            self.clock.set_speed(speed)
        for dev in self.devices.values():
            await dev({"type": "clock", **self.clock.to_dict()})
        await self.tick()

    async def demo_jump(self, home_id: str = "margaret", after_min: float = 4.0, speed: float | None = None) -> str:
        """Jump the demo clock to a few minutes past this person's learned deadline (optionally setting speed)."""
        h = self.homes[home_id]
        day = kettle_day(self.clock.local())
        b = h.model.baseline(day, self.policy())
        target = min(b.deadline_min + after_min, 23 * 60 + 50)
        hhmm = fmt_min(target)
        await self.demo_clock(hhmm, speed)
        return hhmm

    async def demo_device(self, home_id: str, msg: dict) -> bool:
        dev = self.devices.get(home_id)
        if dev:
            await dev(msg)
        return bool(dev)

    async def grid_alert_now(self) -> None:
        for h in self.homes.values():
            if h.circle and h.kind == "live":
                await self._broadcast_check(h, "grid", f"Alberta grid emergency: rotating outages possible. It's {self._temp_str()}.",
                                            f"{h.person} lives alone. A quick call or knock tonight would help.")
        await self.broadcast()

    # ================================================================== views
    def home_view(self, h: Home, private: bool = False) -> dict:
        day, now_min = self._now_min()
        b = self.baseline(h, day)
        paused = bool(h.paused_until and self.clock.now() < h.paused_until)
        e = h.escalation
        if paused:
            status, text = "paused", f"Paused until {self.clock.local(h.paused_until).strftime('%a %-H:%M')}"
        elif e and e.active:
            status = "alert" if e.reason == "morning" else e.reason
            text = {"check_self": f"Kettle is asking {h.person}…", "ask_neighbour": "Asking a neighbour to knock",
                    "neighbour_going": "A neighbour is on the way", "ask_family": "Asking family",
                    "welfare": "Welfare check suggested", "needs_help": "Needs help"}.get(e.step.value, e.step.value)
            if e.reason in ("grid", "dark", "heat"):
                text = e.headline
        elif h.first_today:
            f = h.first_today
            status, text = "ok", f"Morning started {f['hhmm']} · {NICE.get(f['label'], f['label'])}"
        elif b.get("usual_min") and now_min < b["usual_min"]:
            status, text = "early", f"Not up yet · usually {b.get('usual')}"
        elif not b.get("learned", True):
            status, text = "waiting", f"Learning {h.person}'s routine · Kettle asks at {b.get('deadline')}"
        else:
            status, text = "waiting", f"Usually {b.get('usual') or '–'} · Kettle asks at {b.get('deadline')}"
        v = {
            "id": h.id, "person": h.person, "pronoun": h.pronoun, "kind": h.kind, "label": h.label,
            "area": h.area, "pos": h.pos, "sensing": h.sensing, "status": status, "status_text": text,
            "first_today": h.first_today, "baseline": b, "now_min": now_min,
            "events": [{k: ev.get(k) for k in ("t", "hhmm", "min", "label", "human", "kind", "text", "duration_s", "dp_w")}
                       for ev in h.events if ev.get("human") or ev.get("label") == "furnace_blower"][-40:],
            "escalation": e.to_dict() if e else None,
            "past": h.past[-3:],
            "paused": paused, "glow": h.glow if (h.glow and time.time() < h.glow["until"]) else None,
            "device": {"online": h.device_online, "seen": h.device_seen, "info": h.device_info,
                       "dark": bool(h.offline_since and not h.device_online and h.dark_notified)},
            "ringing": bool(h.ringing_until and time.time() < h.ringing_until),
            "seed": h.seed_source,
            "circle": [m.to_dict() for m in h.circle] if not private else [m.name for m in h.circle],
        }
        return v

    def grid_view(self) -> dict:
        if self.grid.replay.active:
            return {"mode": "replay", **self.grid.replay.at(self.clock.now()), "fired": self.grid.replay.fired}
        return {"mode": "live", "aeso": self.grid.live, "weather": self.grid.weather, "alerts": self.grid.alerts,
                "errors": self.grid.errors}

    def stage_state(self) -> dict:
        return {
            "type": "state", "clock": self.clock.to_dict(), "cold": self.cold_info(), "grid": self.grid_view(),
            "homes": [self.home_view(h) for h in self.homes.values()],
            "members": [{"id": mid, "name": x["member"].name, "role": x["member"].role, "relation": x["member"].relation,
                         "distance_min": x["member"].distance_min, "pos": x["pos"], "avatar": x["avatar"],
                         "homes": x["home_ids"], "online": bool(self.circle_conns.get(mid))}
                        for mid, x in self.members.items()],
            "outbox": list(self.outbox)[:25], "flashes": [f for f in self.flashes if time.time() - f["t"] < 8],
            "refit": self.refit, "timings": self.timings.__dict__, "store": self.store.status,
            "twilio": self.notifier.via, "real_time": time.time(),
        }

    def member_state(self, mid: str) -> dict:
        info = self.members[mid]
        m: Member = info["member"]
        return {
            "type": "state", "clock": self.clock.to_dict(), "cold": self.cold_info(),
            "me": m.to_dict() | {"avatar": info["avatar"]},
            "homes": [self.home_view(self.homes[hid], private=True) for hid in info["home_ids"]],
            "notes": self.notes.get(mid, [])[:20],
        }

    async def broadcast(self) -> None:
        if self.stage_conns:
            s = self.stage_state()
            for send in list(self.stage_conns):
                try:
                    await send(s)
                except Exception:
                    self.stage_conns.discard(send)
        dirty, self._dirty_members = self._dirty_members, set()
        for mid, conns in list(self.circle_conns.items()):
            if not conns:
                continue
            st = self.member_state(mid)
            st["buzz"] = mid in dirty
            for send in list(conns):
                try:
                    await send(st)
                except Exception:
                    conns.discard(send)
