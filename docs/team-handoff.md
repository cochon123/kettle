# Team handoff: what's done, what's left

The deadline is **Sun Nov 8, before 11:30 AM Alberta Time** (the portal's "ABT" and Devpost's "CST" are the same: Alberta has been on UTC−6 since Nov 1 2026). Aim to submit by 10:30.

## Done and working

- End-to-end product: plug or simulator → edge detector → events → cloud rhythm + escalation → circle phone → "kettle just came on ☕". 17 tests pass.
- Stage, circle PWA, kitchen display and pitch deck. axe-core: 0 WCAG A/AA violations on the circle and kitchen screens.
- Real data: AESO live + Jan 2024 archive, ECCC live + archive, REFIT evaluation over 9,242 home-days. Margaret's baseline is REFIT House 11's real mornings.
- TimescaleDB schema (hypertables, continuous aggregates, retention) checked against a real container. Twilio adapter. ESP32 firmware (compiles, 4 modes).
- Docs: demo script, Q&A, architecture, accessibility, hardware, pilot kit + consent, data sources, AI disclosure, Devpost draft.
- Tools: `scripts/preflight.py` (pre-show check), `scripts/record.py` (records the real demo to MP4), `scripts/snap.py` (screenshots).

## Needs a human

| Item | Who (suggested split) | Notes |
|---|---|---|
| Buy and set up a Shelly Plus Plug US (or Kasa KP115), test `--plug shelly:<ip>` with a real kettle | 1 Hardware | Boil one cup (≈70 s). Run preflight. If anything's flaky, `--plug sim` still works and is labelled. |
| Flash an ESP32 with `firmware/kettle-sense` (OUTPUT_HUB) and wire a big button + warm LED | 1 Hardware | Optional, but the physical "I'm fine" button is a great prop |
| Real phone ring (Twilio) | 3 Backend | **Done:** the team's Twilio number is +1 825 782 9153 and a test SMS was delivered. Run the demo with `KETTLE_TWILIO_PROFILE=cochon-victus TWILIO_FROM=+18257829153 KETTLE_MARGARET_PHONE=<team phone> KETTLE_TWILIO_ONLY=<team phone>`. "Press 1" needs a public HTTPS `KETTLE_PUBLIC_URL`; without it the call just speaks the message |
| Pilot | 5 Pilot lead | Only with signed consent (`docs/pilot-kit.md`). Even 1–2 homes for 1 night is honest if labelled as such. **Don't overclaim.** |
| Practise the 3-minute run 5+ times with the real kettle and a judge-phone | everyone | `docs/demo-script.md` |
| Record the 2–3 min video | 4 Design | A raw 86 s capture of the real demo already exists: `/home/cochon/kettle-data/video/kettle-demo-raw{,-stage,-phone}.mp4`. Re-record with `scripts/record.py`, then cut and caption. Say "time accelerated" and show the AI disclosure |
| Devpost: title `TeamID-TeamName - Kettle`, GitHub link, video | 5 | Draft in `docs/devpost.md` |
| Make the repo public, check no secrets or pilot data | 3 | `.env` and `pilot/` are git-ignored |
| Auth0 for circle logins (MLH prize) | 4 | Not done: circle links are bearer links (`?m=priya`). Fine for a demo; say so if asked |

## Known limits (say them before judges find them)

- REFIT is UK homes (3 kW kettles); North American kettles are 1.5 kW. With the plug (v0) that doesn't matter (F1 0.96 on REFIT); whole-home (v1) is harder.
- 4.7 check-ins per home per month is the no-pause number. A real product needs "I'm away" (built), and possibly learned weekly patterns.
- Microwave and TV detection from the whole-home meter isn't reliable, so we only claim kettle versus "activity".
- No real pilot yet. Margaret is a persona with a real REFIT routine.
