"""Engine integration: demo clock -> morning check -> circle -> kettle resolves."""
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


def test_morning_flow(engine):
    async def go():
        await engine.demo_reset("6:30")
        h = engine.homes["margaret"]
        await engine.tick()
        assert h.escalation is None
        b = h.model.baseline(h.day)
        late = int(b.deadline_min) + 5
        await engine.demo_clock(f"{late // 60}:{late % 60:02d}", 1)
        assert h.escalation and h.escalation.step == Step.CHECK_SELF
        # nobody answers: jump past the self-check timeout
        engine.clock.set(engine.clock.now() + engine.timings.self_s + 1)
        await engine.tick()
        assert h.escalation.step == Step.ASK_NEIGHBOUR
        assert engine.notes["priya"][0]["kind"] == "ask"
        await engine.respond("priya", h.escalation.id, "going")
        assert h.escalation.step == Step.NEIGHBOUR_GOING
        await engine.ingest("margaret", {"kind": "on", "label": "kettle", "human": True, "t": 0, "channel": "kettle"})
        assert h.escalation.step == Step.RESOLVED
        assert "kettle" in engine.notes["priya"][0]["title"]
        assert h.first_today is not None
    asyncio.run(go())


def test_cloud_has_no_raw_reading_storage():
    import pathlib
    sql = (pathlib.Path(__file__).parents[1] / "db/schema.sql").read_text().lower()
    assert "watts" not in sql.replace("-- raw watts never leave the home", "")


def test_replay_reaches_alert_and_asks_circle(engine):
    async def go():
        await engine.demo_replay(speed=1, start="18:43")
        h = engine.homes["margaret"]
        assert h.escalation is None, "no morning check during the evening replay"
        assert engine.cold_active(), "-30.9 C at 18:00 should switch cold mode on"
        engine.clock.set(engine.clock.now() + 120, 1)
        await engine.tick()
        assert h.escalation and h.escalation.reason == "grid"
        assert engine.notes["priya"][0]["kind"] == "grid"
        assert "°C" in engine.notes["priya"][0]["title"]
    asyncio.run(go())


def test_heat_watch_for_whole_home_sensing(engine):
    async def go():
        await engine.demo_reset("7:00")
        engine.cold_mode = "on"
        h = engine.homes["margaret"]
        h.sensing = "v1"
        h.first_today = {"t": engine.clock.now(), "hhmm": "7:00", "min": 420, "label": "kettle"}  # morning fine
        await engine.ingest("margaret", {"kind": "cycle", "label": "furnace_blower", "human": False, "t": 0,
                                         "duration_s": 600, "channel": "home"})
        await engine.tick()
        assert h.escalation is None
        engine.clock.set(engine.clock.now() + engine.blower_gap_s + 60)
        await engine.tick()
        assert h.escalation and h.escalation.reason == "heat"
        assert "furnace" in engine.notes["priya"][0]["title"]
    asyncio.run(go())
