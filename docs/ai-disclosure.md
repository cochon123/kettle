# AI usage disclosure

The Hack the Change rules require disclosing all AI usage. Here is ours.

## In the product: none at runtime

Kettle uses **no machine-learning model and no AI API** when it runs. Appliance detection is deterministic signal processing (edge detection and signature bands). The rhythm model is robust statistics (median and MAD). Escalation is a hand-written state machine. Every decision can be explained in one sentence, and the app shows that sentence ("No kettle by 10:40. Usually 7:52.").

## In building it: AI coding assistance

We used **Claude Code (Anthropic, Claude Opus)** as a coding assistant during the event, for:

- scaffolding and writing code: the Python package (detector, rhythm model, escalation, cloud service, edge hub), the web front-ends, the ESP32 firmware and the TimescaleDB schema;
- the REFIT evaluation pipeline, which was run on the real dataset;
- fetching and parsing the public AESO and Environment Canada data;
- drafting documentation (this folder, the README, the demo script).

How we checked it:
- The core logic has unit and integration tests (`pytest`).
- The UIs were checked with headless-browser screenshots at projector and phone sizes.
- Every number shown on screen comes from a real data file in `data/` with its source URL. The evaluation numbers come from running the code, not from the assistant.
- One claim from our own early brief ("reserves fell to about 10 MW" on Jan 13 2024) **could not be sourced, so it was removed**.

The team is responsible for all of it. Ask us anything about how any part works.
