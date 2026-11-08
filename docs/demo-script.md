# Demo script (about 3 minutes)

## Before you go on (10 min before)

- [ ] Laptop on power. `.venv/bin/python -m kettle demo --plug shelly:<ip>` (or `--plug sim` with no plug).
- [ ] Projector: `http://localhost:8700/stage/` fullscreen (F11). Press **R** to reset to 6:30. Check the plug chip says **plug** (real) or **simulated plug**.
- [ ] "Priya's" phone (a team phone): open `http://<laptop-ip>:8700/circle/?m=priya`. Tap once anywhere to unlock sound. Turn the volume up, switch vibration on and stop the screen sleeping. This is the phone you hand to a judge.
- [ ] Kettle on the judges' table, plugged into the plug, with **one cup of water** (≈ 70 s to boil at 1500 W).
- [ ] Optional, with Twilio: `TWILIO_FROM` + `KETTLE_MARGARET_PHONE` set to a second team phone placed face-up on the table as "Margaret's landline". **Don't answer it.**
- [ ] Kitchen display (optional, second screen or tablet): `http://<laptop-ip>:8701/hub/`.
- [ ] Phones and laptop on the same Wi-Fi (or Tailscale). Test the circle phone **after** the venue Wi-Fi is up.

Presenter keys on the stage: **D** drawer · **R** reset to 6:30 · **J** jump just past Margaret's learned deadline · **K** simulate kettle · **C** cold mode · **P** Jan 13 2024 replay · **M** sound.

## Run of show

| Time | Say | Do |
|---|---|---|
| 0:00 | *(silence, then)* "Every morning, around ten, Margaret makes tea." | Stage idle: the live line breathes. Click the kettle switch once for the sound, without boiling. |
| 0:20 | "42% of Canadians aged 85+ live alone. In a BMJ study of people over 90, 80% of those who fell alone and couldn't get up didn't use their alarm pendant. A pendant needs you to wear it and press it. Kettle needs nothing." | – |
| 0:45 | "Kettle learned Margaret's mornings from her electricity. These are real mornings, from a real single-person home in the REFIT study: usually around 10:20. Time on screen is accelerated. It's past noon and there's been no kettle." | Press **J** (jumps a few minutes past her learned deadline, about 12:07 on a weekend). The band glows amber; the explanation appears: *"No kettle by 12:07. Usually 10:21."* |
| 0:55 | "Kettle asks Margaret first: a phone call and a pulsing light in her kitchen. Nobody answers." | Margaret's phone rings on stage (and on the table, with Twilio). Wait about 20 s. |
| 1:15 | "So it asks the nearest person in her circle." | **The judge's phone buzzes**: *"You're 2 min away. Can you knock?"* Invite the judge to tap **I'm going**. A thread of light crosses the map. |
| 1:30 | "And then Margaret puts the kettle on." | **Switch the real kettle on** (or press **K**). The trace spikes to ~1500 W. The judge's phone: *"Margaret's kettle just came on ☕"*. About 70 s later: *"…just boiled"*. |
| 1:45 | "Now the Alberta part. January 13, 2024. Real AESO and Environment Canada data." | Press **P**. Frost creeps in at −29.7 °C. The price sits at the $999.99 cap. |
| 2:05 | "At 6:44 PM every phone in Alberta buzzed. Albertans cut about 200 MW within minutes. Kettle makes that alert also say: check on Margaret." | The alert fires at 18:44 (about 18 s after P). The judge's phone gets the grid check. |
| 2:15 | "Raw power never leaves the house; only events like 'kettle on' do. We replayed 20 real homes, over 9,000 home-days, through the code you just saw: a plug on the kettle detects it 96% of the time, and Kettle would ring the person about 4.7 times a month, 2.5 if they pause it when away. Each of those is a phone call to her, not a neighbour at the door. Next is a consented pilot in Calgary homes." | Point at the evidence strip (or deck slide 7). |
| 2:40 | "Japan has done this with a kettle since 2001. Every Calgary home already has a meter. No cameras. No wearables. Just someone who notices." | Logo. |

## Presenter mode (no smart plug): the story one keypress at a time

`python3 -m kettle show` starts everything (simulated kettle plug, the big button when the Arduino is plugged in),
puts Margaret's learned morning at 8:30 and switches the timers off. Nothing happens until you press **SPACE** in that terminal:

| Key | Clock | What happens | Show |
|---|---|---|---|
| SPACE | 8:31 | Kettle texts Margaret; the big button pulses | Margaret's phone, the button |
| SPACE | 8:34 | No answer: Priya, next door, gets "Can you knock on Margaret's door?" | Priya's phone |
| SPACE | 8:54 | Still nothing: Daniel, her son, gets "Can you call Margaret?" | Daniel's phone |
| SPACE | 9:01 | She makes her tea: everyone gets "Margaret's kettle just came on" | All phones |

**R** starts over, **Q** quits. Pressing the big button at any point is Margaret saying "I'm fine" and ends it the same way.
`--usual 7:45` moves her morning.

### The phones: https://kettle-demo.vercel.app

Each phone plays one character. Open the site (or scan the QR code on the host page), pick Margaret, Priya or Daniel,
and optionally add a phone number. Registered numbers get real texts with a link back to the site, where the buttons
are ("I'm going", "All good, I know she's fine", "I'm fine"…); SMS can't carry buttons. Numbers are kept 24 hours at most.

The laptop is the hub: `kettle show` pushes every phone's card to the site about once a second and picks up taps and
registrations on the way back, so the laptop needs internet but no open port. The host page
(`/host/?pin=…`, link printed in the presenter terminal) lists who is playing, removes a phone to free its character,
and has the same Next / Restart as SPACE / R.

No internet? `kettle show --offline`, and phones on the same Wi-Fi open the laptop links printed at the bottom of the
presenter screen (`…:8700/phone/?c=priya`, `?c=daniel`, `?c=margaret`). Real texts then need `--phone who=+1…`.

The site's secrets live in `~/.config/kettle/site.json` (hub secret, host PIN, URL), never in the repo.

## If something goes wrong

| Problem | Fix |
|---|---|
| Real plug not responding (chip goes red) | Restart with `--plug sim` and press **K** instead of the switch. Say "simulated plug" out loud; the chip says it too. |
| Circle phone not buzzing | Open `/circle/?m=tom` on a second phone. Or show the stage outbox; the same message is there. |
| Wi-Fi down | Everything runs on the laptop. Use a phone hotspot for the circle phone, or present the circle app in a laptop browser window. |
| Replay too fast or slow | Drawer → speed buttons. The 18:44 moment can also be forced with "Grid alert now". |
| Need to start over | **R** (reset to 6:30), then **J**. |

## Recording the video

Same script, same screens: animate the real product, not a mock-up. Record the stage at 1920×1080, plus a phone screen recording of the circle app, and cut between them. Keep it to 2–3 minutes. Show the AI disclosure and "time accelerated" captions on screen.
