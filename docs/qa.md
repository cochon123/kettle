# Q&A prep

Say this **before** they ask: *"Kettle is not a medical device or an emergency service. It's a neighbourly nudge."*

**"Isn't this surveillance?"**
Raw power readings never leave the house, and that's enforced in code: the cloud has no place to store them and drops them if sent. The circle sees moments like "kettle on at 7:48". The person owns their circle, can pause it from the kitchen display, and is always asked first. No cameras, no microphones, no wearables.

**"What about false alarms?"**
We measured it. Replaying 20 real REFIT homes through the code we ship gives **4.7 check-in calls per home per month** with a kettle plug, and **2.5** if people pause Kettle when they go away. Every check-in is a call to the person first. A false alarm costs one phone call, not a neighbour at the door. Robust statistics (median and MAD, separate weekend rhythm, a minimum 45-minute margin) keep one late morning from moving the baseline. Almost half of check-ins (46%) are days with no activity at all, which is why the away-pause matters. *Honest caveat:* REFIT homes are UK families, not Calgary seniors, and there were no real incidents, so every check-in counts as false.

**"How fast does it notice?"**
The median is **76 minutes** after the person's usual time (**51 min** in cold mode). Compare a pendant: only if it's worn and pressed. In the BMJ study, 80% didn't press it.

**"How accurate is the detection?"**
With a plug on the kettle, detection is essentially certain: F1 **0.96** against REFIT's labelled kettle channel. With a whole-home meter (v1), F1 is **0.66** on UK 3 kW kettles (0.69 on held-out houses); three calibration boils at setup lift it to **0.72**. Microwave detection from the whole-home meter is *not* reliable (precision 0.09), so the apps call those events plain "activity". Morning activity doesn't need the kettle specifically: any human appliance event counts.

**"What if they don't have a kettle?"**
The model learns any daily routine: microwave, toaster, TV. With the v1 meter sensor, it sees the whole home.

**"Why not just a camera or a smart speaker?"**
People refuse cameras in their kitchen. Speakers need you to talk to them. Kettle needs nothing new from the person.

**"Does it work in Alberta's cold?"**
Cold mode uses live Environment Canada alerts and temperatures to ask sooner. It also watches the furnace blower on whole-home sensing, and a Kettle that goes dark in a cold snap asks the circle to check. We replayed January 13 2024 from real AESO and ECCC data: −30.9 °C at 6 PM, the price at the $999.99 cap for 4 hours, and the 6:44 PM alert.

**"Who pays? How does it scale?"**
v0 is a $25 plug and any spare Raspberry Pi or tablet. v1 is a $15 ESP32 on the meter LED, with no electrician. v2 needs no hardware: utility interval data through ENMAX or EPCOR. Cloud cost per home is tiny (a few events per day; TimescaleDB continuous aggregates keep baselines current). Natural partners: seniors' organisations like Kerby Centre (circles), utilities (data and outreach), and municipal community-safety programs.

**"What about people with no neighbours or family nearby?"**
The circle can include a volunteer from a seniors' organisation. The last step is a welfare check (Calgary Police non-emergency line, 403-266-1234).

**"Did you run a pilot?"**
Not yet. We have the consent form and protocol ready (`docs/pilot-kit.md`), and the pilot runs in observation-only mode. We didn't want to claim one we hadn't done.

**"What's real in the demo?"**
The detection, rhythm, escalation, apps and data are real. Margaret is a persona, but her mornings are a real single-occupant home's measured mornings (REFIT House 11). The demo clock is openly accelerated. Calls and SMS are simulated unless Twilio has a number.

**"Did you use AI?"**
As a coding assistant during the event, disclosed in `docs/ai-disclosure.md`. The product itself uses no AI at runtime. Every decision is an explainable rule, and we can walk you through any line.

**"Is it a medical device?"**
No. It doesn't diagnose or monitor health. It notices when an ordinary day looks unusual and asks people who care to check.
