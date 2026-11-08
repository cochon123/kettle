# Hardware

## v0: a plug on the kettle (~$25)

Any plug Kettle can read **locally**, with no vendor cloud in the loop:

| Plug | Kettle flag | Local API |
|---|---|---|
| Shelly Plus Plug US / Gen3 | `--plug shelly:<ip>` | `GET /rpc/Switch.GetStatus?id=0` → `apower` |
| Shelly Plug US (Gen1) | `--plug shelly1:<ip>` | `GET /meter/0` → `power` |
| Any Tasmota energy plug (e.g. Athom, Sonoff S31 flashed) | `--plug tasmota:<ip>` | `GET /cm?cmnd=Status 10` → `ENERGY.Power` |
| TP-Link Kasa KP115 / EP25 | `--plug kasa:<ip>` | python-kasa (`pip install python-kasa`) |

North American kettles draw about 1000–1500 W (120 V, 15 A circuit). The plug must be rated 15 A / 1800 W. All of the above are.

Set up the Shelly with the Shelly app (Wi-Fi only), then in its web UI at `http://<ip>` you can disable cloud. Kettle polls it once a second.

## v1: the whole home, with no electrician (ESP32, ~$15)

`firmware/kettle-sense/kettle-sense.ino`, any ESP32 dev board, Arduino core 3.x.

**Meter pulse LED (preferred).** Most smart meters have an LED marked "1000 imp/kWh" (one flash per Wh). Tape a phototransistor or photodiode module (e.g. a TCRT5000 board or an LM393 light-sensor module with digital out) over the LED. Wire: module VCC → 3V3, GND → GND, DO → GPIO 27. Power = 3600 / seconds between flashes (W). A kettle on top of a 300 W base load takes the flash interval from about 12 s to about 2 s.

**CT clamp (alternative).** SCT-013-030 (30 A : 1 V) around one cord or one leg. Bias it to mid-rail with two 10 kΩ resistors and a 10 µF capacitor into GPIO 34 (ADC1). This gives apparent power, assuming 120 V.

**Kitchen interface.** A big momentary button between GPIO 0 and GND (the board's BOOT button works for a demo) is the physical **"I'm fine"**. A warm LED (or a MOSFET driving an LED strip) on GPIO 2 **pulses** during a check-in and **glows** when someone sends "thinking of you".

**Two output modes** (`#define OUTPUT_MODE`):
- `OUTPUT_HUB`: pushes watts to the edge hub on the LAN (`python -m kettle edge --plug push --sensing meter`). The hub runs the full detector and the kitchen display.
- `OUTPUT_EVENTS`: standalone. A port of the step detector runs **on the ESP32** and posts only events to the cloud (`POST /api/events/<home>` with `x-kettle-key`). The raw readings never leave the chip.

Build: `arduino-cli compile --fqbn esp32:esp32:esp32 firmware/kettle-sense`, then `arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:esp32 firmware/kettle-sense`. Set `WIFI_SSID`, `WIFI_PASS` and `HUB_URL`/`CLOUD_URL` first.

## v2: no hardware at all

Utility interval data (ENMAX, EPCOR) through a utility partnership. The cloud already accepts events from any source. A v2 adapter would run the same detector over 1–15 minute interval data, which only supports coarse rhythm, not appliance-level detection.
