"""Core logic tests: detector, rhythm model, escalation. Run: .venv/bin/python -m pytest -q"""
import datetime as dt
import random

from kettle.detect import Detector, DetectorConfig, detect_series
from kettle.escalation import DEMO, Escalation, Member, Step
from kettle.rhythm import COLD, STANDARD, DayObs, RhythmModel, first_activity_by_day, fmt_min


def wave(segments, dt_s=1.0, noise=3.0, seed=1):
    rnd = random.Random(seed)
    t, out = 0.0, []
    for watts, seconds in segments:
        for _ in range(int(seconds / dt_s)):
            out.append((t, watts + rnd.gauss(0, noise)))
            t += dt_s
    return out


# ---------------------------------------------------------------- detector
def test_plug_kettle_on_and_cycle():
    evs = list(detect_series(wave([(0.5, 20), (1500, 90), (0.5, 20)]), "kettle", DetectorConfig.for_plug()))
    kinds = [(e.kind, e.label) for e in evs]
    assert kinds == [("on", "kettle"), ("cycle", "kettle")]
    cyc = evs[1]
    assert 85 <= cyc.duration_s <= 95
    assert cyc.human and cyc.flatness_cv < 0.03


def test_plug_ignores_short_spike():
    evs = list(detect_series(wave([(0.5, 20), (1500, 1), (0.5, 20)]), "kettle", DetectorConfig.for_plug()))
    assert evs == []


def test_events_carry_no_raw_samples():
    evs = list(detect_series(wave([(0.5, 20), (1500, 60), (0.5, 20)]), "kettle", DetectorConfig.for_plug()))
    d = evs[-1].to_dict()
    assert not any(isinstance(v, list) for v in d.values()), "an event must be a summary, never a waveform"


def test_uk_aggregate_kettle_8s():
    # REFIT-like: 8 s samples, 300 W base, 3 kW kettle for ~3 min
    evs = list(detect_series(wave([(300, 400), (3300, 176), (300, 400)], dt_s=8, noise=10), "home", DetectorConfig.for_refit()))
    labels = [e.label for e in evs if e.kind == "cycle"]
    assert "kettle" in labels


# ---------------------------------------------------------------- rhythm
def days(start, mins):
    return [DayObs(start + dt.timedelta(days=i), m, "kettle") for i, m in enumerate(mins)]


def test_learning_then_learned():
    start = dt.date(2026, 10, 5)  # a Monday
    m = RhythmModel().fit(days(start, [470, 475, 480]))
    b = m.baseline(start + dt.timedelta(days=3))
    assert not b.learned and b.deadline_min == STANDARD.default_deadline_min
    m.fit(days(start, [470, 475, 480, 468, 490, 472, 478]))
    b = m.baseline(start + dt.timedelta(days=7))
    assert b.learned and 465 <= b.usual_min <= 485
    assert b.deadline_min - b.usual_min >= STANDARD.min_margin_min


def test_median_is_robust_to_one_odd_day():
    start = dt.date(2026, 10, 5)
    m = RhythmModel().fit(days(start, [472, 470, 475, 1300, 471, 474, 473]))
    b = m.baseline(start + dt.timedelta(days=7))
    assert abs(b.usual_min - 473) <= 2


def test_cold_mode_asks_sooner():
    start = dt.date(2026, 10, 5)
    m = RhythmModel().fit(days(start, [460, 470, 480, 490, 500, 470, 480, 475, 485, 465]))
    d = start + dt.timedelta(days=10)
    assert m.baseline(d, COLD).deadline_min < m.baseline(d, STANDARD).deadline_min


def test_night_activity_is_not_the_morning():
    import zoneinfo
    z = zoneinfo.ZoneInfo("America/Edmonton")
    t_night = dt.datetime(2026, 11, 4, 2, 30, tzinfo=z).timestamp()
    t_morning = dt.datetime(2026, 11, 4, 7, 52, tzinfo=z).timestamp()
    out = first_activity_by_day([(t_night, "kettle"), (t_morning, "kettle")], z)
    assert fmt_min(out[dt.date(2026, 11, 4)][0]) == "7:52"


# ---------------------------------------------------------------- escalation
def circle():
    return [Member("priya", "Priya", "neighbour", distance_min=2), Member("tom", "Tom", "neighbour", distance_min=4),
            Member("daniel", "Daniel", "family")]


def esc(pronoun="she"):
    return Escalation("h", "Margaret", "morning", "Margaret's morning hasn't started.", "No kettle by 10:40. Usually 7:52.",
                      circle(), 0, DEMO, pronoun=pronoun)


def test_asks_person_first_then_nearest_neighbour():
    e = esc()
    acts = e.start(0)
    assert {a["type"] for a in acts} == {"call_person", "device"}
    assert e.tick(DEMO.self_s - 1) == []
    acts = e.tick(DEMO.self_s)
    asked = [a for a in acts if a["type"] == "notify"]
    assert asked[0]["member"] == "priya" and "2 min away" in asked[0]["title"]


def test_kettle_resolves_and_tells_everyone_involved():
    e = esc()
    e.start(0); e.tick(DEMO.self_s)
    e.on_response(30, "priya", "going")
    acts = e.on_activity(40, "kettle", "Margaret's kettle just came on ☕")
    assert e.step == Step.RESOLVED
    told = {a["member"] for a in acts if a["type"] == "notify"}
    assert told == {"priya", "daniel"}


def test_cant_moves_to_next_neighbour_then_family_then_welfare():
    e = esc("they")
    e.start(0); e.tick(DEMO.self_s)
    acts = e.on_response(25, "priya", "cant")
    assert any(a.get("member") == "tom" for a in acts)
    e.tick(25 + DEMO.neighbour_s)
    assert e.step == Step.ASK_FAMILY
    acts = e.tick(25 + DEMO.neighbour_s + DEMO.family_s)
    assert e.step == Step.WELFARE and "403-266-1234" in acts[0]["body"]
    assert "them" in acts[0]["body"]


def test_person_can_say_im_fine():
    e = esc()
    e.start(0)
    e.on_self_ok(5, "device")
    assert e.step == Step.RESOLVED and "I'm fine" in e.resolution
