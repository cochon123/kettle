"""The phone app's single card: one sentence, one action.

The engine knows a lot (rhythm bands, event feeds, escalation logs); a phone
held by a neighbour should show almost none of it. `card()` boils a
character's state down to:

    {who, tone, kicker, title, body, why, buttons, glow, buzz, clock}

tone   calm | alert | good | warm
buzz   changes whenever something new arrives that should vibrate the phone
The same cards are served locally (/api/p/me) and relayed to the Vercel site,
so both look identical.
"""

from __future__ import annotations

import time

URGENT = {"ask", "ask_family", "welfare", "need_help", "grid", "dark", "heat", "followup"}
CHARACTERS = {
    "margaret": {"name": "Margaret", "line": "lives alone in Bridgeland", "role": "person"},
    "priya": {"name": "Priya", "line": "neighbour, next door", "role": "neighbour"},
    "daniel": {"name": "Daniel", "line": "her son, in Edmonton", "role": "family"},
}


def _p(home: dict) -> dict:
    from ..escalation import PRONOUNS
    return PRONOUNS.get(home.get("pronoun", "she"), PRONOUNS["they"])


def member_card(engine, mid: str) -> dict:
    st = engine.member_state(mid)
    me, home, notes = st["me"], st["homes"][0], st["notes"]
    person, p = home["person"], _p(home)
    clock = st["clock"]["hhmm"]
    base = {"who": {"id": mid, "name": me["name"], "line": CHARACTERS.get(mid, {}).get("line", me.get("relation", ""))},
            "person": person, "clock": clock, "buzz": notes[0]["id"] if notes else 0, "glow": None}
    now = time.time()
    for n in notes:
        kind, ref = n["kind"], {"escalation": n.get("escalation"), "note": n["id"]}
        if n.get("buttons") and not n.get("answered") and kind in URGENT:
            return base | _alert(n, home, me, person, p) | {"ref": ref}
        if kind == "going_ack" and not n.get("answered") and now - n["t_real"] < 900:
            return base | {"tone": "calm", "kicker": "On your way", "title": f"Thank you, {me['name']}.",
                           "body": f"The others know you're going. When you've seen {person}, tell us how {p['subj']} is.",
                           "why": None, "buttons": n["buttons"], "ref": ref}
        if kind == "resolved" and now - n["t_real"] < 40:
            return base | {"tone": "good", "kicker": "All good", "title": n["title"],
                           "body": "Thank you for being there.", "why": None, "buttons": []}
    return base | _calm(engine, mid, home, me, person, p)


def _alert(n: dict, home: dict, me: dict, person: str, p: dict) -> dict:
    kind, away = n["kind"], me.get("distance_min")
    btns = n["buttons"]
    if kind == "ask":
        reason = n["body"].replace("No kettle by", "No kettle yet at").rstrip(".")
        return {"tone": "alert", "kicker": "Kettle needs you", "title": f"Can you knock on {person}'s door?",
                "body": f"{reason}. You're {away:g} min away." if away is not None else f"{reason}.",
                "why": f"Kettle asked {person} first. No answer.", "buttons": btns}
    if kind == "ask_family":
        reason = n["body"].split(" Can you call")[0].replace("No kettle by", "No kettle yet at").rstrip(".")
        return {"tone": "alert", "kicker": "Kettle needs you", "title": f"Can you call {person}?",
                "body": f"{reason}. No neighbour has been able to check.", "why": None, "buttons": btns}
    kicker = {"welfare": "Still no answer", "need_help": "Help needed", "followup": "Quick question",
              "grid": "Alberta grid emergency", "dark": "Power may be out", "heat": "Is the heat on?"}.get(kind, "Kettle")
    title = n["title"]
    if title.lower().startswith(kicker.lower() + ":"):           # "Alberta grid emergency: rotating…" under the same kicker
        title = title[len(kicker) + 1:].strip()
        title = title[:1].upper() + title[1:]
    return {"tone": "alert", "kicker": kicker, "title": title.replace(" -", " −"), "body": n.get("body") or None, "why": None,
            "buttons": btns}


def _calm(engine, mid: str, home: dict, me: dict, person: str, p: dict) -> dict:
    glow = home.get("glow")
    sent = glow if glow and glow.get("member") == mid else None
    b, status = home.get("baseline") or {}, home["status"]
    first = home.get("first_today")
    if first:
        title, body = f"{person} is up.", f"Kettle on at {first['hhmm']}."
    elif status in ("alert", "grid", "dark", "heat"):
        title, body = f"Kettle is checking on {person}.", _sentence(home["status_text"])
        if home["status_text"].startswith("Kettle is asking"):
            body = f"No kettle yet this morning. Kettle is asking {p['obj']} first."
    elif status == "paused":
        title, body = f"{person} paused Kettle.", _sentence(home["status_text"])
    else:
        usual = b.get("usual")
        title = f"{person}'s morning hasn't started yet."
        body = f"{p['Subj']} usually makes tea around {usual}." if usual else "Kettle is learning her routine."
    out = {"tone": "calm", "kicker": None, "title": title, "body": body, "why": None, "buttons": []}
    out["glow"] = {"sent": bool(sent), "label": "Thinking of you",
                   "hint": (f"A warm light is glowing in {person}'s kitchen." if sent
                            else f"Lights a warm glow in {person}'s kitchen. No reply needed.")}
    return out


def _sentence(text: str) -> str:
    return text if text.endswith((".", "…", "!", "?")) else text + "."


def person_card(engine, home_id: str = "margaret") -> dict:
    h = engine.homes[home_id]
    clock = engine.clock.local().strftime("%-H:%M")
    base = {"who": {"id": home_id, "name": h.person, "line": CHARACTERS.get(home_id, {}).get("line", "")},
            "person": h.person, "clock": clock, "glow": None, "why": None}
    e, now = h.escalation, time.time()
    if e and e.active and e.reason == "morning":
        return base | {"tone": "alert", "kicker": "Good morning", "buzz": f"esc{e.id}",
                       "title": f"Good morning, {h.person}. Are you OK?",
                       "body": "Tap the button, or press the big button in your kitchen.",
                       "buttons": [{"id": "im_fine", "label": "I'm fine", "style": "primary"}],
                       "ref": {"escalation": e.id}}
    if e and e.active:
        return base | {"tone": "alert", "kicker": "Kettle", "buzz": f"esc{e.id}", "title": f"{h.person}, are you OK?",
                       "body": e.headline, "buttons": [{"id": "im_fine", "label": "I'm fine", "style": "primary"}],
                       "ref": {"escalation": e.id}}
    if h.glow and now < h.glow["until"]:
        return base | {"tone": "warm", "kicker": None, "buzz": f"glow{int(h.glow['until'])}",
                       "title": f"{h.glow['from']} is thinking of you.", "body": "No reply needed.", "buttons": []}
    if h.past and h.past[-1].get("resolved_at") and engine.clock.now() - h.past[-1]["resolved_at"] < 600:
        return base | {"tone": "good", "kicker": "All good", "buzz": f"ok{h.past[-1]['id']}",
                       "title": f"Thank you, {h.person}.", "body": "Your circle knows you're fine.", "buttons": []}
    return base | {"tone": "calm", "kicker": None, "buzz": 0, "title": f"Good morning, {h.person}.",
                   "body": "Nothing to do. Kettle quietly keeps an eye out.", "buttons": []}


def card(engine, who: str) -> dict:
    if who in engine.homes:
        return person_card(engine, who)
    if who in engine.members:
        return member_card(engine, who)
    raise KeyError(who)


async def act(engine, who: str, action: str, ref: dict | None = None) -> dict:
    """A tap on a phone: im_fine (Margaret), glow, or an answer to the alert on screen."""
    ref = ref or {}
    if who in engine.homes:
        if action == "im_fine":
            await engine.self_ok(who, "app")
            return {"ok": True}
        return {"ok": False, "error": "unknown action"}
    if who not in engine.members:
        return {"ok": False, "error": "unknown character"}
    if action == "glow":
        return await engine.glow(who, engine.members[who]["home_ids"][0])
    if ref.get("escalation") is not None:
        return await engine.respond(who, int(ref["escalation"]), action)
    return {"ok": False, "error": "nothing to answer"}
