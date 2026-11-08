"""Relay to the public phone site (Vercel): the laptop stays the hub, and only ever calls out.

Every second the hub POSTs every character's card to <site>/api/hub/sync and
gets back what happened on the phones since the last sync: taps ("I'm going",
"I'm fine", "Thinking of you"), host commands (next / restart) and who is
registered with which phone number. Nothing on the laptop is reachable from
the internet.

    KETTLE_SITE=https://kettle-demo.vercel.app KETTLE_SITE_SECRET=… python -m kettle cloud
(`python -m kettle show` reads them from ~/.config/kettle/site.json.)
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from .cards import CHARACTERS, act, card

log = logging.getLogger("kettle.relay")


class Relay:
    def __init__(self, engine, site: str, secret: str, interval: float = 1.0):
        self.engine, self.site, self.secret, self.interval = engine, site.rstrip("/"), secret, interval
        self.ok_at: float | None = None
        self.err: str | None = None
        self.registered: dict[str, dict] = {}
        self._orig_phones = {mid: x["member"].phone for mid, x in engine.members.items()}

    def status(self) -> dict:
        return {"site": self.site, "online": bool(self.ok_at and time.time() - self.ok_at < 5), "err": self.err,
                "registered": {c: {"name": r.get("name"), "has_number": bool(r.get("number"))}
                               for c, r in self.registered.items()}}

    def _cards(self) -> dict:
        out = {}
        for c in CHARACTERS:
            try:
                out[c] = card(self.engine, c)
            except KeyError:
                pass
        return out

    def _hub(self) -> dict:
        e = self.engine
        show = e.show or {}
        h = e.homes.get("margaret")
        return {"clock": e.clock.local().strftime("%-H:%M"), "show_step": show.get("step"),
                "escalation": h.escalation.step.value if h and h.escalation else None,
                "twilio": e.notifier.via, "outbox": list(e.outbox)[:8], "t": time.time()}

    def _apply_registrations(self, regs: dict) -> None:
        if regs == self.registered:
            return
        self.registered = regs
        e = self.engine
        numbers = []
        for mid, x in e.members.items():
            num = (regs.get(mid) or {}).get("number")
            x["member"].phone = num or self._orig_phones.get(mid)
            if num:
                numbers.append(num)
        if not hasattr(e, "person_phone"):
            e.person_phone = {}
        e.person_phone["margaret"] = (regs.get("margaret") or {}).get("number") or None
        if e.person_phone["margaret"]:
            numbers.append(e.person_phone["margaret"])
        # only phones registered on the site ever get a real text
        e.notifier.only = set(numbers) or {"+0"}
        log.info("relay: registered %s", {c: bool(r.get("number")) for c, r in regs.items()})

    async def _handle(self, a: dict) -> None:
        e = self.engine
        kind = a.get("action")
        try:
            if a.get("who") == "host":
                if e.show and kind in ("next", "reset"):
                    await e.show_step(kind)
                return
            await act(e, a.get("who", ""), kind, a.get("ref"))
        except Exception as ex:
            log.warning("relay: action %s failed: %s", a, ex)

    async def run(self) -> None:
        self.engine.phone_site = self.site
        async with httpx.AsyncClient(timeout=8) as http:
            while True:
                t0 = time.time()
                try:
                    r = await http.post(f"{self.site}/api/hub/sync", headers={"authorization": f"Bearer {self.secret}"},
                                        json={"cards": self._cards(), "hub": self._hub()})
                    r.raise_for_status()
                    d = r.json()
                    self._apply_registrations(d.get("registrations") or {})
                    acted = False
                    for a in d.get("actions") or []:
                        await self._handle(a)
                        acted = True
                    if acted:
                        await self.engine.broadcast()
                    self.ok_at, self.err = time.time(), None
                except Exception as ex:
                    if self.err is None:
                        log.warning("relay: %s unreachable: %s", self.site, ex)
                    self.err = str(ex)[:160]
                # answer taps quickly: sync again soon after an action, otherwise once a second
                await asyncio.sleep(max(0.15, self.interval - (time.time() - t0)))
