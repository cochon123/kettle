<img src="assets/icon.svg" width="64" height="64" alt="">

# Kettle

**No cameras. No wearables. No buttons. Just the kettle.**

Kettle turns a home's electricity use into a quiet "I'm okay" signal for seniors who live alone. When a morning doesn't start the way it usually does, Kettle asks the person first, then a neighbour in their circle: *"Margaret's morning hasn't started. You're 2 min away. Can you knock?"* It doesn't call a call centre.

Built for **Hack the Change 2026** (Calgary), Prompt 1: *health, social connection and well-being in our communities.*

---

## Run the demo (60 seconds)

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[db,eval,dev]"   # or: pip install -e .
.venv/bin/python -m kettle demo                   # cloud :8700 + edge hub :8701, simulated kettle plug
```

| Screen | URL | Who sees it |
|---|---|---|
| Stage (presenter) | http://localhost:8700/stage/ | the room. Press **D** for presenter controls |
| Circle app (phone) | http://localhost:8700/circle/?m=priya | a neighbour. Also `?m=tom`, `?m=daniel`, or `?join=1` (code `margaret`) |
| Kitchen display | http://localhost:8701/hub/ | Margaret. Served by the edge hub, LAN only |
| Pitch deck | http://localhost:8700/deck/ | the room. Arrow keys; every number is loaded from `data/` |

Before presenting, run `.venv/bin/python scripts/preflight.py`. It checks the plug, the device link, the circle socket, the data and the live feeds, then prints the URLs for the phones.

With a real smart plug on a real kettle:

```bash
.venv/bin/python -m kettle demo --plug shelly:192.168.1.50     # or tasmota:<ip>, shelly1:<ip>, kasa:<ip>
```

The full stage run-of-show, with keystrokes and fallbacks, is in [docs/demo-script.md](docs/demo-script.md).

## How it works

```
 Margaret's home (edge)                                    Cloud                                 Circle
┌────────────────────────────┐   events only    ┌──────────────────────────────┐   push/SMS   ┌──────────────┐
│ $25 plug ─▶ edge hub        │ ───────────────▶ │ rhythm model (per person)     │ ───────────▶ │ neighbour    │
│   1 Hz watts, LAN only      │  "kettle on 7:48"│ escalation state machine      │ ◀─────────── │ "I'm going"  │
│   detector: edges, cycles,  │                  │ AESO + Environment Canada     │   response   │ family       │
│   appliance signatures      │ ◀─────────────── │ TimescaleDB (events, no watts)│              └──────────────┘
│ kitchen display / button    │  check-in, glow  │ Twilio voice + SMS            │
└────────────────────────────┘                  └──────────────────────────────┘
```

1. **Sense, at the edge.** The hub reads a smart plug (v0), or an ESP32 on the meter's pulse LED (v1), over the local network. [`kettle/detect.py`](kettle/detect.py) is a streaming steady-state edge detector (a variant of Hart's NILM method). It pairs ON and OFF edges into appliance cycles and labels them with explainable signatures ([`kettle/signatures.py`](kettle/signatures.py)): power step, duration and flatness. **Raw readings never leave the house.** The cloud has no table for them and drops them if a device sends any.
2. **Learn.** [`kettle/rhythm.py`](kettle/rhythm.py) learns when each person's day usually starts (median and MAD, split into weekdays and weekends) and sets a deadline: `usual + clamp(k·spread, 45 min, 3 h)`. Every alert explains itself: *"No kettle by 10:40. Usually 7:52."*
3. **Respond with dignity.** [`kettle/escalation.py`](kettle/escalation.py) is a pure, tested state machine. It calls the person and pulses the kitchen light ("press or say *I'm fine*"), then asks the nearest neighbour, then the next, then family, then suggests a welfare check (Calgary Police non-emergency, 403-266-1234). Any kettle event resolves it, and everyone involved hears *"Margaret's kettle just came on ☕"*. It also works the other way: **"Thinking of you"** makes a warm light glow in Margaret's kitchen.
4. **Cold mode (the Alberta twist).** Live Environment Canada data (an extreme cold alert, or −25 °C and below) tightens the thresholds. If a Kettle goes dark in a cold snap, the circle is asked to check. The **January 13 2024 replay** runs the real day: AESO hourly pool price and Alberta Internal Load, every System Marginal Price change, and ECCC hourly temperature. At 18:44, when every phone in Alberta buzzed, Kettle sends each circle: *check on Margaret.*

Details: [docs/architecture.md](docs/architecture.md).

## What's real and what's simulated

We tell judges exactly this.

| Piece | Status |
|---|---|
| Detector, rhythm model, escalation, cloud, circle app, kitchen display | **Real, working code**, tested (`pytest`) |
| Smart plug readings | **Real** with a Shelly, Tasmota or Kasa plug. Without one, a simulator produces a realistic waveform that goes through the same detector |
| AESO grid data | **Real**: live Current Supply Demand report, plus archived Jan 10–16 2024 hourly and SMP data ([data/](data/)) |
| Weather / cold alerts | **Real**: live ECCC city page and alerts for Calgary, plus archived hourly CALGARY INTL A |
| REFIT evaluation | **Real measured data**: 20 UK homes, 8 s readings. See [docs/refit-evaluation.md](docs/refit-evaluation.md) |
| Margaret's learned baseline | **Real mornings from REFIT House 11**, a single-occupant home. Margaret is a persona; her routine is a real person's measured routine |
| Map homes besides Margaret | **Real REFIT households replayed** at their real times of day, labelled as such |
| Phone calls and SMS | Real Twilio code. **Simulated** unless `TWILIO_FROM` is set (see below) |
| ESP32 firmware (meter LED / CT clamp, "I'm fine" button, warm LED) | **Compiles** for ESP32 (arduino-cli, core 3.x) in all 4 modes. Not yet flashed to a board. The meter-pulse path is tested in software (`tests/test_meter_pulse.py`) |
| Circle names (Priya, Tom, Daniel) | Personas |
| Pilot homes | **Not done yet.** [docs/pilot-kit.md](docs/pilot-kit.md) has the consent form and protocol |

Kettle is **not a medical device or an emergency service**.

## Repository map

```
kettle/detect.py, signatures.py   edge detector + appliance signatures (shared by the live hub and the REFIT eval)
kettle/rhythm.py                  personal rhythm model
kettle/escalation.py              escalation state machine (pure logic)
kettle/edge/                      the in-home hub: plug drivers, simulator, local UI server
kettle/cloud/                     FastAPI service: engine, AESO/ECCC, TimescaleDB, Twilio
kettle/eval/refit.py              REFIT evaluation (detector accuracy, false check-ins per home per month)
web/stage  web/circle  web/hub    presenter screen, circle PWA, kitchen display (vanilla JS, no build)
firmware/kettle-sense/            ESP32: meter pulse LED or CT clamp, physical "I'm fine" button + warm LED
db/schema.sql                     TimescaleDB hypertables + continuous aggregates
data/                             real AESO / ECCC data and derived REFIT results, with provenance
scripts/fetch_real_data.py        re-fetches the AESO + ECCC data
scripts/preflight.py              pre-show check: everything green before you go on stage
scripts/snap.py                   real-time headless-Chrome screenshots of the UIs
docs/                             architecture, demo script, Q&A, accessibility, pilot kit + consent form, hardware,
                                  data sources, AI disclosure, Devpost draft
```

## Options

| Variable | Purpose |
|---|---|
| `KETTLE_DB=postgresql://kettle:kettle@localhost:5433/kettle` | persist to TimescaleDB (`docker compose up -d`). Without it, everything runs in memory |
| `KETTLE_TWILIO_PROFILE=<twilio-cli profile>` or `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` | Twilio credentials |
| `TWILIO_FROM=+1825…` | a Twilio number you own. Without it, calls and SMS are simulated and shown on stage |
| `KETTLE_MARGARET_PHONE=+1…` | the phone that rings as "Margaret's landline" |
| `KETTLE_PUBLIC_URL=https://…` | public URL, so SMS links work and Twilio can post "press 1" back |
| `KETTLE_DEVICE_KEY`, `KETTLE_INVITE` | device shared key (default `demo-key`), circle invite code (default `margaret`) |
| `KETTLE_DEMO=0` | real clock and production timings (3 min self check, 10 min per neighbour) |

Tests: `.venv/bin/python -m pytest -q`

## Data and licences

- **REFIT**: Murray, Stankovic & Stankovic (2017), *An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study*, Scientific Data 4:160122, [doi:10.1038/sdata.2016.122](https://doi.org/10.1038/sdata.2016.122). CC BY 4.0. Only small derived results are in this repo.
- **AESO**: ETS public reports (Current Supply Demand, Actual/Forecast, Historical SMP).
- **Environment and Climate Change Canada**: historical climate data and MSC GeoMet API, Open Government Licence – Canada.
- Full list: [docs/data-sources.md](docs/data-sources.md).

## AI disclosure

This project was built during the event with AI coding assistance. What was AI-assisted, and how we checked it, is in [docs/ai-disclosure.md](docs/ai-disclosure.md). The product itself uses **no AI model at runtime**. Detection and rhythm are explainable signal processing and statistics.

MIT licensed.
