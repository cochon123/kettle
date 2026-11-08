# Pilot kit: 3–5 homes, 7+ days

Goal: show judges real rhythms from real consenting households, and a measured false-check-in rate. **No pilot data has been collected yet.** Until it has, the stage only shows REFIT data, labelled as REFIT.

## Ground rules

1. **Written consent before anything is plugged in** (form below). The participant can withdraw at any time, and their data is deleted on request.
2. **The pilot is observation only.** Kettle runs with escalation **switched off** (no neighbour is ever messaged), so a false alarm has no consequence. We only count what *would* have happened.
3. **No real household data in the public repo.** Pilot event logs go in `pilot/` (git-ignored). Only aggregate numbers go on slides (e.g. "4 homes, 31 home-days, 1 check-in would have been sent"). Never names, addresses or per-day timelines, unless the participant explicitly agrees to their anonymised rhythm being shown on stage.
4. Kettle is not a medical device. Participants keep their usual safety arrangements.

## Install (15 minutes per home)

1. Shelly Plus Plug US (or a Tasmota/Kasa energy plug) between the kettle and the wall. Join it to the home Wi-Fi with the vendor app, then **turn off its cloud connection**; we read it locally.
2. A Raspberry Pi (or any always-on laptop) on the same Wi-Fi:
   ```bash
   KETTLE_DEMO=0 .venv/bin/python -m kettle edge --home pilot1 --plug shelly:<plug-ip> --cloud ws://<team-server>:8700 --key <device-key>
   ```
3. Cloud with `KETTLE_DEMO=0` (real clock, production timings) and `KETTLE_DB` set, so events go into TimescaleDB.
4. Check that the kitchen display at `http://<pi-ip>:8701/hub/` shows the plug as ✓. Boil once together and watch the event arrive.

## What we measure

- Days covered, kettle uses per day, first activity per day (the `daily_activity` continuous aggregate).
- From day 5 on: whether the deadline would have triggered a check-in, and for which reason.
- Participant feedback (2 questions on day 7): *"Would you want this on?"* and *"Who would you want in your circle?"*

---

## Consent form (template)

**Kettle pilot: participant information and consent**

Kettle is a student project at Hack the Change 2026 (University of Calgary). It explores whether a home's electricity use, starting with the kettle, can quietly show that someone's day has started normally.

**What we'll do:** put a smart plug on your kettle and a small computer in your home for about 7–14 days. The computer notices when the kettle goes on and off.

**What we collect:** only the time and type of appliance events (e.g. "kettle on, 7:48, 2 minutes"). Detailed power readings stay on the device in your home and are not stored by us. No cameras, no microphones.

**What we don't do:** during the pilot, Kettle will **not** contact you, your neighbours or your family. We only record what it *would* have done.

**Who sees it:** only the team members named below. In our presentation we may show summary numbers (e.g. number of homes and days). We will show your daily pattern only if you tick the box below, and then without your name or address.

**Your choices:** you can unplug Kettle, stop, or ask us to delete your data at any time, without giving a reason. All pilot data is deleted by ____________ (date).

**Contact:** ____________________ (team lead), ____________________ (phone/email)

☐ I agree to take part in the Kettle pilot as described above.
☐ I agree that my anonymised daily kettle pattern may be shown in the presentation.

Name: ______________________  Signature: ______________________  Date: __________

Team member: ________________  Signature: ______________________  Date: __________

*(Participant keeps a copy.)*
