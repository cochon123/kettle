"""Escalation state machine: ask the person, then a neighbour, then family, then a welfare check.

Pure logic, no I/O: every method takes `now` and returns a list of *actions*
(dicts) that the cloud service executes (phone call, SMS, push to the circle
app, light on the kitchen device). That makes it deterministic and testable,
and lets the demo clock run at any speed.

    CHECK_SELF ──(no answer)──▶ ASK_NEIGHBOUR ──(nobody)──▶ ASK_FAMILY ──▶ WELFARE
        │                          │   "I'm going"
        │                          ▼
        │                     NEIGHBOUR_GOING ──(follow-up)──▶ "Did you see her?"
        └──── any activity / "I'm fine" / "All good" ────────────────▶ RESOLVED
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field, asdict
from enum import Enum

WELFARE_LINE = "Calgary Police non-emergency line, 403-266-1234"

PRONOUNS = {
    "she": {"subj": "she", "obj": "her", "poss": "her", "is": "she's", "Is": "She's", "Subj": "She"},
    "he": {"subj": "he", "obj": "him", "poss": "his", "is": "he's", "Is": "He's", "Subj": "He"},
    "they": {"subj": "they", "obj": "them", "poss": "their", "is": "they're", "Is": "They're", "Subj": "They"},
}


class Step(str, Enum):
    CHECK_SELF = "check_self"
    ASK_NEIGHBOUR = "ask_neighbour"
    NEIGHBOUR_GOING = "neighbour_going"
    ASK_FAMILY = "ask_family"
    WELFARE = "welfare"
    NEEDS_HELP = "needs_help"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class Timings:
    self_s: float = 180.0        # wait for "I'm fine" after calling / lighting the device
    neighbour_s: float = 600.0   # each neighbour's turn before we also ask the next
    going_s: float = 1200.0      # then ask the neighbour who went: "did you see her?"
    family_s: float = 900.0      # family's turn before suggesting a welfare check


PRODUCTION = Timings()
DEMO = Timings(self_s=20.0, neighbour_s=60.0, going_s=150.0, family_s=90.0)


@dataclass
class Member:
    id: str
    name: str
    role: str                    # "neighbour" | "family"
    relation: str = ""
    phone: str | None = None
    distance_min: float | None = None   # walking minutes to the person's door
    available: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


_ids = itertools.count(1)

def buttons_ask(p: dict) -> list[dict]:
    return [{"id": "going", "label": "I'm going", "style": "primary"},
            {"id": "all_good", "label": f"All good, I know {p['is']} fine", "style": "secondary"},
            {"id": "cant", "label": "I can't right now", "style": "quiet"}]


def buttons_followup(p: dict) -> list[dict]:
    return [{"id": "ok", "label": f"{p['Is']} OK", "style": "primary"},
            {"id": "need_help", "label": f"{p['Subj']} needs help" if p["subj"] != "they" else "They need help",
             "style": "danger"}]


@dataclass
class Escalation:
    home_id: str
    person: str                       # "Margaret"
    reason: str                       # "morning" | "heat" | "grid"
    headline: str                     # "Margaret's morning hasn't started."
    explanation: str                  # "No kettle, no lights by 10:40. Usually 7:52."
    circle: list[Member]
    started_at: float
    timings: Timings = PRODUCTION
    pronoun: str = "she"
    id: int = field(default_factory=lambda: next(_ids))
    step: Step = Step.CHECK_SELF
    step_since: float = 0.0
    asked: list[str] = field(default_factory=list)
    declined: list[str] = field(default_factory=list)
    responder: str | None = None
    resolution: str | None = None
    resolved_at: float | None = None
    log: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------ public API
    @property
    def p(self) -> dict:
        return PRONOUNS.get(self.pronoun, PRONOUNS["they"])

    @property
    def active(self) -> bool:
        return self.step not in (Step.RESOLVED,)

    def start(self, now: float) -> list[dict]:
        self.step, self.step_since = Step.CHECK_SELF, now
        self._log(now, "detect", f"{self.explanation}")
        self._log(now, "self", f"Calling {self.person} and pulsing the light on {self.p['poss']} Kettle: “Press or say I'm fine.”")
        return [
            {"type": "call_person", "text": self._call_script()},
            {"type": "device", "cmd": "checkin", "text": f"Good morning, {self.person}. Press here if you're fine."},
        ]

    def tick(self, now: float) -> list[dict]:
        if not self.active:
            return []
        t = self.timings
        elapsed = now - self.step_since
        if self.step == Step.CHECK_SELF and elapsed >= t.self_s:
            self._log(now, "self", f"No answer from {self.person} after {self._dur(t.self_s)}.")
            return self._ask_next_neighbour(now)
        if self.step == Step.ASK_NEIGHBOUR and elapsed >= t.neighbour_s:
            return self._ask_next_neighbour(now)
        if self.step == Step.NEIGHBOUR_GOING and elapsed >= t.going_s:
            self.step_since = now + 10 ** 9  # follow up once
            m = self._m(self.responder)
            self._log(now, "followup", f"Asking {m.name}: did you see {self.person}?")
            return [self._notify(m, "followup", f"Were you able to see {self.person}?",
                                 f"Let the circle know how {self.p['subj']} {'are' if self.p['subj'] == 'they' else 'is'}.",
                                 buttons_followup(self.p))]
        if self.step == Step.ASK_FAMILY and elapsed >= t.family_s:
            self.step, self.step_since = Step.WELFARE, now
            self._log(now, "welfare", f"Nobody has reached {self.person}. Suggesting a welfare check.")
            return [self._notify(m, "welfare", f"Nobody has been able to reach {self.person}.",
                                 f"Please call {self.p['obj']}, or request a welfare check: {WELFARE_LINE}. In an emergency call 911.",
                                 [{"id": "ok", "label": f"I reached {self.p['obj']}, {self.p['is']} OK", "style": "primary"},
                                  {"id": "tel:4032661234", "label": "Call non-emergency line", "style": "secondary"}])
                    for m in self._family()]
        return []

    def on_activity(self, now: float, label: str, sentence: str | None = None) -> list[dict]:
        if not self.active:
            return []
        text = sentence or f"{self.person}'s {label.replace('_', ' ')} just came on."
        return self._resolve(now, "activity", text)

    def on_self_ok(self, now: float, via: str = "device") -> list[dict]:
        if not self.active:
            return []
        how = {"device": f"pressed “I'm fine” on {self.p['poss']} Kettle",
               "phone": f"answered the call: {self.p['is']} fine"}.get(via, via)
        return self._resolve(now, "self", f"{self.person} {how}.")

    def on_response(self, now: float, member_id: str, response: str) -> list[dict]:
        if not self.active:
            return []
        m = self._m(member_id)
        if m is None:
            return []
        if response == "going":
            self.step, self.step_since, self.responder = Step.NEIGHBOUR_GOING, now, m.id
            self._log(now, "going", f"{m.name} is on the way ({self._away(m)}).")
            acts = [self._notify(m, "going_ack", f"Thank you, {m.name}.",
                                 "We've told the others you're on your way. We'll check in with you shortly.",
                                 buttons_followup(self.p))]
            acts += [self._notify(o, "update", f"{m.name} is going to check on {self.person}.",
                                  "No need to do anything right now.", [])
                     for o in self._involved() if o.id != m.id]
            acts.append({"type": "thread", "from": m.id, "to": self.home_id})
            return acts
        if response in ("all_good", "ok"):
            what = {"all_good": f"{m.name} says {self.person} is fine.",
                    "ok": f"{m.name} saw {self.person}: {self.p['is']} OK."}[response]
            return self._resolve(now, "member", what, by=m.id)
        if response == "cant":
            self.declined.append(m.id)
            self._log(now, "cant", f"{m.name} can't go right now.")
            return self._ask_next_neighbour(now)
        if response == "need_help":
            self.step, self.step_since = Step.NEEDS_HELP, now
            self._log(now, "help", f"{m.name} says {self.person} needs help. Showing 911 and alerting family.")
            acts = [self._notify(m, "need_help", "Call 911 now if it's an emergency.",
                                 f"Stay with {self.person} if you can. {self.p['poss'].capitalize()} family has been alerted.",
                                 [{"id": "tel:911", "label": "Call 911", "style": "danger"}])]
            acts += [self._notify(f, "need_help", f"{m.name} is with {self.person}: {self.p['subj']} need{'' if self.p['subj'] == 'they' else 's'} help.",
                                  f"Call {m.name}{' at ' + m.phone if m.phone else ''}.", [])
                     for f in self._family()]
            return acts
        return []

    def to_dict(self) -> dict:
        return {
            "id": self.id, "home_id": self.home_id, "person": self.person, "reason": self.reason,
            "headline": self.headline, "explanation": self.explanation, "step": self.step.value,
            "step_since": self.step_since if self.step_since < 10 ** 9 else None,
            "started_at": self.started_at, "asked": self.asked, "declined": self.declined,
            "responder": self.responder, "resolution": self.resolution, "resolved_at": self.resolved_at,
            "log": self.log, "timings": asdict(self.timings),
        }

    # ------------------------------------------------------------ internals
    def _m(self, mid: str | None) -> Member | None:
        return next((m for m in self.circle if m.id == mid), None)

    def _family(self) -> list[Member]:
        return [m for m in self.circle if m.role == "family"]

    def _involved(self) -> list[Member]:
        ids = set(self.asked) | {m.id for m in self._family()}
        return [m for m in self.circle if m.id in ids]

    def _away(self, m: Member) -> str:
        return f"{m.distance_min:g} min away" if m.distance_min is not None else "nearby"

    def _dur(self, s: float) -> str:
        return f"{int(s)} s" if s < 90 else f"{round(s / 60)} min"

    def _call_script(self) -> str:
        return (f"Hello {self.person}, it's Kettle. We haven't seen your morning start yet. "
                f"If you're fine, press 1, or press the glowing button on your Kettle.")

    def _log(self, now: float, kind: str, text: str) -> None:
        self.log.append({"t": now, "kind": kind, "text": text, "step": self.step.value})

    def _notify(self, m: Member, kind: str, title: str, body: str, buttons: list[dict]) -> dict:
        return {"type": "notify", "member": m.id, "kind": kind, "title": title, "body": body,
                "buttons": buttons, "escalation": self.id, "home_id": self.home_id}

    def _ask_next_neighbour(self, now: float) -> list[dict]:
        acts: list[dict] = []
        if self.step == Step.CHECK_SELF:
            acts.append({"type": "device", "cmd": "checkin_keep", "text": f"Press here if you're fine, {self.person}."})
        candidates = sorted((m for m in self.circle if m.role == "neighbour" and m.available
                             and m.id not in self.asked and m.id not in self.declined),
                            key=lambda m: m.distance_min if m.distance_min is not None else 99)
        if candidates:
            m = candidates[0]
            self.asked.append(m.id)
            self.step, self.step_since = Step.ASK_NEIGHBOUR, now
            self._log(now, "ask", f"Asking {m.name}, {self._away(m)}: “Can you knock?”")
            acts.append(self._notify(m, "ask", f"{self.headline} You're {self._away(m)}. Can you knock?",
                                     self.explanation, buttons_ask(self.p)))
            return acts
        if self.step in (Step.ASK_FAMILY, Step.WELFARE):
            return acts
        self.step, self.step_since = Step.ASK_FAMILY, now
        fam = self._family()
        self._log(now, "family", f"No neighbour could go. Asking family: {', '.join(m.name for m in fam) or 'none listed'}.")
        for m in fam:
            if m.id not in self.asked:
                self.asked.append(m.id)
            acts.append(self._notify(m, "ask_family", f"{self.headline} No neighbour has been able to check.",
                                     f"{self.explanation} Can you call {self.person}?",
                                     [{"id": "ok", "label": f"I reached {self.p['obj']}, {self.p['is']} OK", "style": "primary"},
                                      buttons_followup(self.p)[1]]))
        return acts

    def _resolve(self, now: float, how: str, text: str, by: str | None = None) -> list[dict]:
        self.step, self.resolution, self.resolved_at = Step.RESOLVED, text, now
        self._log(now, "resolved", text)
        acts: list[dict] = [{"type": "device", "cmd": "checkin_end"}]
        for m in self._involved():
            acts.append(self._notify(m, "resolved", text, "All good. Thank you for being there.", []))
        return acts
