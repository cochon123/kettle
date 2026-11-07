# Architecture

## The privacy boundary is the architecture

```
          ┌──────────────────────── Margaret's home (LAN) ─────────────────────────┐
          │                                                                          │
          │  smart plug ──1 Hz watts──▶  EDGE HUB  (kettle/edge/hub.py, a Raspberry Pi)│
          │  or ESP32 on meter LED       ├─ detector (kettle/detect.py)               │
          │                              ├─ store-and-forward queue (internet drops)  │
          │  kitchen display ◀──local WS─┤─ local trace (last 10 min, RAM only)       │
          │  "I'm fine" button ─────────▶│                                            │
          └──────────────────────────────┼────────────────────────────────────────────┘
                                         │  WebSocket, events only:
                                         │  {"kind":"on","label":"kettle","dp_w":1490,...}
                                         ▼
          ┌──────────────────────────── Kettle cloud (kettle/cloud) ─────────────────┐
          │  engine.py      rhythm model per person · escalation state machine        │
          │  grid.py        AESO Current Supply Demand · ECCC weather + alerts · replay│
          │  store.py       TimescaleDB: events hypertable, daily_activity cont. agg.  │
          │  notify.py      Twilio voice ("press 1") + SMS                            │
          └──────────────┬───────────────────────────────────────────┬───────────────┘
                         │ WebSocket (+ SMS link)                    │ WebSocket
                         ▼                                           ▼
                  circle app (PWA, phones)                    stage (presenter)
```

- **No raw readings in the cloud.** There is no table, endpoint or message type for watts. If a device sends `{"type":"samples"}` anyway, the cloud logs a warning and drops it (`app.py`). A test checks the schema has no readings table.
- **An event is a summary**: kind, label, step size, duration, flatness and confidence. Never a waveform.
- **The person is asked first**, owns their circle, and can pause Kettle from the kitchen display ("I'm away today"). The circle is told when Kettle is paused.

## Edge detector (`kettle/detect.py`)

Streaming steady-state edge detection, after Hart (1992) and adapted for low sample rates:

1. Keep a steady level. A sample outside `max(abs_tol, rel_tol·level)` opens a candidate level.
2. If the candidate persists for `confirm_samples` **and** `confirm_s`, commit an edge `dP`. Spikes such as motor inrush revert to the old level and are ignored.
3. A positive edge opens a cycle. A negative edge closes the open cycle whose `dP` matches best (within 25% or 150 W), giving duration and flatness (the coefficient of variation of power while on, from steady samples only).
4. Score the cycle against soft-band signatures ([`signatures.py`](../kettle/signatures.py)): kettle (NA 950–1650 W, 40–480 s, very flat), microwave (flickers), toaster, TV, furnace blower, fridge.

The detector emits a provisional `on` event at the rising edge, which is what resolves an escalation within about 2 s, and a confirmed `cycle` event at the falling edge ("just boiled").

The same module runs live on the hub and offline in the REFIT evaluation, so the accuracy we quote is the accuracy of the code we ship.

## Rhythm model (`kettle/rhythm.py`)

- A "Kettle day" runs from 04:00 to 04:00. First human activity is the first human-labelled event after 04:00.
- Over the last 28 days: `usual = median`, `spread = max(1.4826·MAD, 10 min)`. Weekdays and weekends are learned separately once there are at least 4 days of each.
- `deadline = usual + clamp(k·spread, min_margin, max_margin)`: standard is k = 3 with a 45–180 min margin; cold mode is k = 2 with 30–120 min.
- Fewer than 5 days of data means the model is still learning and the deadline is fixed at 11:00.
- In TimescaleDB, the `daily_activity` continuous aggregate computes the same per-day first activity incrementally (`time_bucket('1 day', time, 'America/Edmonton', offset => 4 h)`).

## Escalation (`kettle/escalation.py`)

Pure functions of `(state, now)` that return actions, so they're deterministic, testable and demo-clock friendly.

| Step | Action | Production timeout | Demo timeout |
|---|---|---|---|
| check_self | call the person ("press 1"), pulse the kitchen light ("press or say I'm fine") | 3 min | 20 s |
| ask_neighbour | nearest available neighbour: [I'm going] [All good] [I can't]; "can't" moves straight on | 10 min each | 60 s |
| neighbour_going | everyone else is told; follow-up "did you see her?" [She's OK] [She needs help → 911] | 20 min | 150 s |
| ask_family | family members, with the explanation | 15 min | 90 s |
| welfare | suggest a police welfare check (403-266-1234), 911 in an emergency | – | – |

Any human activity, an "I'm fine" press, or a neighbour's "All good" resolves the escalation, and everyone involved is told *"Margaret's kettle just came on ☕"*.

Broadcast checks (grid emergency, a home going dark in a cold snap) ask the whole circle at once and never escalate on their own.

## Cold mode

The trigger is an ECCC weather alert containing "cold" for the Calgary bbox, or a temperature at or below −25 °C, or a manual switch. It:
- swaps to the `COLD` policy (asks sooner),
- treats a Kettle that stays offline (`offline_grace`) as a possible power cut and asks the circle,
- in the Jan 13 2024 replay, sends every circle the "check on Margaret" message at 18:44, when the province's emergency alert went out.

## Timekeeping

`kettle/clock.py` runs in real time, or as an **openly labelled** demo clock that can be set and accelerated. The stage, circle and kitchen display all show "demo time" whenever it isn't real time. Calgary times use `zoneinfo` `America/Edmonton`, which correctly gives UTC−7 in January 2024 and permanent UTC−6 from November 2026.
