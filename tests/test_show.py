"""Presenter mode: the story moves only when the presenter presses a key."""
import asyncio

import pytest

from kettle.clock import Clock
from kettle.cloud.engine import Engine
from kettle.cloud.grid import Grid
from kettle.cloud.notify import Notifier
from kettle.cloud.store import Store
from kettle.escalation import Step


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.delenv("KETTLE_DB", raising=False)
    monkeypatch.delenv("TWILIO_FROM", raising=False)
    e = Engine(Clock(), Notifier(), Store(), Grid(), demo=True)
    e.setup_demo()
    return e


def test_show_story_step_by_step(engine):
    async def go():
        st = await engine.show_setup(usual="8:30", phones={"priya": "+14035550000"})
        h = engine.homes["margaret"]
        assert st["usual"] == "8:30" and st["clock"] == "8:18"
        assert engine.members["priya"]["member"].phone == "+14035550000"
        assert engine.notifier.only == {"+14035550000"}

        st = await engine.show_step("next")                       # 8:31: ask Margaret
        assert st["clock"] == "8:31" and h.escalation.step == Step.CHECK_SELF
        assert any(o["channel"] == "sms" and o["to"] == "Margaret" for o in engine.outbox)
        # no timers in presenter mode: an hour of silence changes nothing
        engine.clock.set(engine.clock.now() + 3600)
        await engine.tick()
        assert h.escalation.step == Step.CHECK_SELF and not engine.notes["priya"]
        await engine.show_step("reset")
        await engine.show_step("next")

        await engine.show_step("next")                            # ask the nearest neighbour
        assert h.escalation.step == Step.ASK_NEIGHBOUR and engine.notes["priya"][0]["kind"] == "ask"
        assert not engine.notes["tom"]

        st = await engine.show_step("next")                       # 20 min later: family
        assert st["clock"] == "8:54" and h.escalation.step == Step.ASK_FAMILY
        assert engine.notes["daniel"][0]["kind"] == "ask_family" and not engine.notes["tom"]

        await engine.show_step("next")                            # she makes tea (no device: cloud-side event)
        assert h.escalation.step == Step.RESOLVED
        for m in ("priya", "daniel"):
            assert engine.notes[m][0]["kind"] == "resolved" and "kettle" in engine.notes[m][0]["title"]
        texts = [o for o in engine.outbox if o["channel"] == "sms" and "kettle just came on" in o["text"]]
        assert {o["to"] for o in texts} == {"Priya", "Daniel"}
    asyncio.run(go())


def test_show_button_press_ends_it_early(engine):
    async def go():
        await engine.show_setup()
        await engine.show_step("ask_self")
        await engine.show_step("ask_neighbour")
        await engine.self_ok("margaret", "device")
        assert engine.homes["margaret"].escalation.step == Step.RESOLVED
        assert "pressed" in engine.notes["priya"][0]["title"]
        st = await engine.show_step("ask_family")                 # nothing left to escalate
        assert st["step"] == "resolved" and all(n["kind"] == "resolved" for n in engine.notes["daniel"])
    asyncio.run(go())


def test_phone_cards_follow_the_story(engine):
    from kettle.cloud.cards import act, card

    async def go():
        await engine.show_setup()
        assert card(engine, "priya")["tone"] == "calm" and card(engine, "priya")["glow"]
        assert card(engine, "margaret")["title"].startswith("Good morning")
        await engine.show_step("ask_self")
        m = card(engine, "margaret")
        assert m["tone"] == "alert" and m["buttons"][0]["id"] == "im_fine"
        await engine.show_step("ask_neighbour")
        p = card(engine, "priya")
        assert p["title"] == "Can you knock on Margaret's door?" and "2 min away" in p["body"]
        assert [b["id"] for b in p["buttons"]] == ["going", "all_good", "cant"]
        assert card(engine, "daniel")["tone"] == "calm"           # family isn't asked yet
        await act(engine, "priya", "going", p["ref"])
        assert card(engine, "priya")["kicker"] == "On your way"
        await act(engine, "margaret", "im_fine")                  # she taps "I'm fine" on her phone
        for c in ("priya", "daniel"):
            assert card(engine, c)["tone"] == "good" and "phone" in card(engine, c)["title"]
        assert card(engine, "margaret")["tone"] == "good"
        await act(engine, "daniel", "glow")
        assert card(engine, "margaret")["tone"] == "warm"
    asyncio.run(go())


def test_relay_registrations_and_taps(engine):
    from kettle.cloud.relay import Relay

    async def go():
        await engine.show_setup()
        r = Relay(engine, "https://example.invalid", "s")
        r._apply_registrations({"priya": {"name": "Priya", "number": "+14035550000"}, "margaret": {"number": None}})
        assert engine.members["priya"]["member"].phone == "+14035550000"
        assert engine.notifier.only == {"+14035550000"}
        assert engine.members["daniel"]["member"].phone == "+17805550123"   # unregistered: the fictional one
        await r._handle({"who": "host", "action": "next"})
        assert engine.homes["margaret"].escalation.step == Step.CHECK_SELF
        await r._handle({"who": "margaret", "action": "im_fine"})
        assert engine.homes["margaret"].escalation.step == Step.RESOLVED
        r._apply_registrations({})                                          # host removed everyone
        assert engine.members["priya"]["member"].phone == "+15875550142"
        assert set(r._cards()) == {"margaret", "priya", "daniel"}
    asyncio.run(go())
