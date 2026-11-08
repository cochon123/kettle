"""v1 path: power estimated from meter LED pulses (as the ESP32 firmware does) still yields a kettle event."""
from kettle.detect import Detector, DetectorConfig


def pulse_power_series(profile, wh_per_pulse=1.0):
    """profile: list of (watts, seconds). Returns 1 Hz (t, watts) estimated like kettle-sense.ino."""
    pulses, energy, t = [], 0.0, 0.0
    total = sum(s for _, s in profile)
    seg = iter(profile)
    w, left = next(seg)
    while t < total:
        energy += w * 0.1 / 3600
        if energy >= wh_per_pulse:
            energy -= wh_per_pulse
            pulses.append(t)
        t += 0.1
        left -= 0.1
        if left <= 1e-9:
            try:
                w, left = next(seg)
            except StopIteration:
                break
    out = []
    for sec in range(int(total)):
        past = [p for p in pulses if p <= sec]
        if len(past) < 2:
            continue
        interval = past[-1] - past[-2]
        p = 3600 * wh_per_pulse / max(interval, 0.05)
        since = sec - past[-1]
        if since > interval:
            p = min(p, 3600 * wh_per_pulse / since)
        out.append((float(sec), p))
    return out


def test_kettle_visible_through_meter_pulses():
    series = pulse_power_series([(350, 300), (1850, 150), (350, 300)])
    det = Detector("home", DetectorConfig(region="na"))
    events = [e for t, w in series for e in det.push(t, w)]
    ons = [e for e in events if e.kind == "on" and e.human]
    assert ons, f"no human ON event from pulse-derived power: {[e.to_dict() for e in events]}"
    assert 1300 <= ons[0].dp_w <= 1700
