# Devpost submission (draft)

**Title:** `<Team ID>-<Team Name> - Kettle` (use the exact Team ID and Team Name from the event website)

**Tagline:** No cameras. No wearables. No buttons. Just the kettle.

**Deadline:** before Sunday Nov 8, 11:30 AM Alberta Time. The portal's "ABT" and Devpost's "CST" are the same time: Alberta has been on UTC−6 year-round since Nov 1 2026. Upload early anyway.

**Links:** GitHub repo · 2–3 min video · (optional) live demo URL

---

## Inspiration
42% of Canadians aged 85+ live alone. In a BMJ study of people over 90, 80% of those who fell while alone and couldn't get up didn't use their call alarm. Pendants only work if you wear them and press them. But every home already has an honest sensor: the electricity meter. It knows when someone got up and made tea. In Calgary, where most homes heat with gas forced air, it even knows whether the furnace fan is running at −30 °C. Japan's Zojirushi i-Pot has emailed families when an elderly parent uses their hot-water pot since 2001. We wanted the same quiet signal, without a special appliance, answered by neighbours instead of a call centre.

## What it does
- **Senses at the edge.** A $25 smart plug on the kettle (v0), or a $15 ESP32 on the meter's pulse LED (v1). A small hub in the home detects appliance events from their power signatures. **Raw readings never leave the house; only events like "kettle on, 7:48" do.**
- **Learns a personal rhythm.** For example, "first activity 10:14 ± 75 min on weekdays", learned from about a week of mornings. Every alert explains itself.
- **Responds with dignity.** It asks the person first (a phone call and a pulsing light: "press or say *I'm fine*"), then the nearest neighbour in their circle ("You're 2 min away. Can you knock?" [I'm going] [All good]), then family, then suggests a welfare check. The moment the kettle goes on, everyone involved hears "Margaret's kettle just came on ☕".
- **Works the other way too.** "Thinking of you" glows warm in the kitchen.
- **Cold mode.** Live Environment Canada data tightens the thresholds, and a Kettle that goes dark in a cold snap asks the circle to check. We replay **January 13 2024** with real AESO and ECCC data: at 18:44, when Alberta's emergency alert went out, Kettle tells each circle: check on Margaret.

## How we built it
- **Edge (Python):** streaming steady-state edge detector (after Hart's NILM), ON/OFF cycle pairing, soft-band appliance signatures (step, duration, flatness), store-and-forward, local plug drivers (Shelly, Tasmota, Kasa) with no vendor cloud.
- **Firmware (ESP32, Arduino):** meter-pulse or CT-clamp sensing, an on-chip port of the step detector, a physical "I'm fine" button and warm LED. It compiles for ESP32.
- **Cloud (FastAPI):** rhythm model (median and MAD, weekday/weekend, cold policy), a pure tested escalation state machine, WebSockets to the circle and to devices, Twilio voice and SMS.
- **Tiger Data / TimescaleDB:** an `events` hypertable (with no raw readings), a `daily_activity` continuous aggregate that computes each person's first activity per "Kettle day" (04:00 to 04:00, America/Edmonton), and retention policies.
- **Energy data (Voltex):** the live AESO Current Supply Demand report, archived AESO hourly pool price and Alberta Internal Load plus System Marginal Price for Jan 2024, live and archived ECCC weather and alerts, and **REFIT** (20 UK homes, real 8-second measurements) for evaluation.
- **Front-ends:** circle PWA (accessible, large targets, events only), kitchen display (one giant "I'm fine" button, voice "I'm fine"), presenter stage (live trace, rhythm band, Calgary map, frost, Jan 13 replay). Vanilla JS, no build step.

## Evidence
We replayed **REFIT** (20 UK homes, 9,242 home-days of real 8-second data) through the same detector and rhythm code we ship:
- **Kettle detection F1: 0.96** with a plug on the kettle, **0.66** from the whole-home meter (0.69 on held-out houses, 0.72 with three calibration boils).
- **4.7 check-in calls per home per month** with a kettle plug, **2.5** if people pause Kettle when away (46% of check-ins are no-activity days). Each check-in is a call to the person first.
- **Median 76 minutes** after the usual time before Kettle asks (51 in cold mode).
- Honest limits: UK families, not Calgary seniors; no true incidents, so every check-in counts as false; microwave detection from the whole-home meter is unreliable (precision 0.09). Full method: `docs/refit-evaluation.md`.

## Challenges
- North American kettles draw 1500 W, half a UK kettle's 3 kW, so whole-home detection is harder here than in the UK data we evaluated on.
- Choosing the deadline is a trade-off between false check-ins and time-to-help. We chose robust statistics with a minimum margin, and the first step is a call to the person, so a false alarm costs one phone call.
- Our brief said Jan 13 2024 reserves "fell to ~10 MW". We couldn't source it, so we dropped it.

## What's next
A consented pilot in 3–5 homes (the protocol and consent form are in the repo), outreach to Calgary seniors organisations (e.g. Kerby Centre), a v2 adapter for utility interval data (no hardware), and a utility partnership.

## Built with
python, fastapi, websockets, timescaledb, postgresql, twilio, esp32, arduino, javascript, aeso, environment-canada, refit

## AI disclosure
Built with AI coding assistance (Claude Code). The product uses no AI model at runtime. See `docs/ai-disclosure.md`.

**Not a medical device or an emergency service.**
