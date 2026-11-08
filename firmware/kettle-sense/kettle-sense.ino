/*
  Kettle sense: ESP32 firmware for the v1 sensor.

  Sensors (pick one with SENSOR_MODE):
    SENSOR_PULSE  photodiode / phototransistor taped over the electricity meter's
                  pulse LED (usually 1 pulse = 1 Wh, printed on the meter as
                  "1000 imp/kWh"). Whole-home power, no electrician needed.
    SENSOR_CT     SCT-013-030 split-core current clamp (30 A : 1 V) on one cord or
                  one leg, biased at mid-rail into ADC1. Apparent power only.

  Outputs (pick one with OUTPUT_MODE):
    OUTPUT_HUB    push the latest watts to the Kettle edge hub on the LAN once a
                  second (POST /api/push). The hub runs the full detector.
    OUTPUT_EVENTS standalone: run a small step detector *on this chip* and post
                  only appliance events to the Kettle cloud. Raw readings never
                  leave the device.

  Kitchen interface (optional, works in OUTPUT_HUB mode):
    BUTTON_PIN    a big physical "I'm fine" button (to GND; BOOT button works)
    LED_PIN       a warm LED / LED strip MOSFET: pulses during a check-in,
                  glows when someone in the circle sends "thinking of you"

  Board: any ESP32 (tested target: esp32:esp32:esp32, Arduino core 3.x).
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

// ------------------------------------------------------------------ settings
#define SENSOR_PULSE 1
#define SENSOR_CT 2
#define OUTPUT_HUB 1
#define OUTPUT_EVENTS 2

#ifndef SENSOR_MODE
#define SENSOR_MODE SENSOR_PULSE
#endif
#ifndef OUTPUT_MODE
#define OUTPUT_MODE OUTPUT_HUB
#endif

const char* WIFI_SSID = "your-wifi";
const char* WIFI_PASS = "your-password";

// OUTPUT_HUB: the edge hub on the LAN (python -m kettle edge --plug push --sensing meter)
const char* HUB_URL = "http://192.168.1.50:8701";
// OUTPUT_EVENTS: the Kettle cloud
const char* CLOUD_URL = "http://192.168.1.50:8700";
const char* HOME_ID = "margaret";
const char* DEVICE_KEY = "demo-key";

const int PULSE_PIN = 27;           // phototransistor module digital out
const float WH_PER_PULSE = 1.0;     // 1000 imp/kWh meters
const unsigned long PULSE_DEBOUNCE_MS = 40;

const int CT_PIN = 34;              // ADC1 only (ADC2 is unusable with Wi-Fi)
const float CT_AMPS_PER_VOLT = 30.0;
const float MAINS_V = 120.0;        // North America
const float CT_NOISE_A = 0.08;      // below this, report 0

const int BUTTON_PIN = 0;           // BOOT button on most dev boards
const int LED_PIN = 2;              // on-board LED; swap for a MOSFET-driven warm strip
const int LED_CH_FREQ = 5000;

// ------------------------------------------------------------------ meter pulse sensing
volatile unsigned long lastPulseMs = 0, prevPulseMs = 0;
volatile unsigned long pulseCount = 0;

void IRAM_ATTR onPulse() {
  unsigned long now = millis();
  if (now - lastPulseMs < PULSE_DEBOUNCE_MS) return;
  prevPulseMs = lastPulseMs;
  lastPulseMs = now;
  pulseCount++;
}

float pulseWatts() {
  noInterrupts();
  unsigned long last = lastPulseMs, prev = prevPulseMs;
  interrupts();
  if (prev == 0) return 0;
  float interval = (last - prev) / 1000.0f;
  float p = 3600.0f * WH_PER_PULSE / max(interval, 0.05f);
  // No pulse for a while means power is at most this: lets drops show up quickly.
  float since = (millis() - last) / 1000.0f;
  if (since > interval) p = min(p, 3600.0f * WH_PER_PULSE / since);
  return p;
}

// ------------------------------------------------------------------ CT clamp sensing
float ctWatts() {
  const int N = 1600;                 // ~13 mains cycles at 60 Hz
  double sum = 0, sum2 = 0;
  unsigned long t0 = micros();
  for (int i = 0; i < N; i++) {
    double mv = analogReadMilliVolts(CT_PIN);
    sum += mv; sum2 += mv * mv;
  }
  (void)t0;
  double mean = sum / N;
  double vrms = sqrt(max(0.0, sum2 / N - mean * mean)) / 1000.0;  // volts
  double irms = vrms * CT_AMPS_PER_VOLT;
  if (irms < CT_NOISE_A) irms = 0;
  return (float)(irms * MAINS_V);
}

float readWatts() {
#if SENSOR_MODE == SENSOR_PULSE
  return pulseWatts();
#else
  return ctWatts();
#endif
}

// ------------------------------------------------------------------ on-chip step detector
// A compact port of kettle/detect.py: steady level, candidate level that must persist,
// edges of at least MIN_STEP_W, ON edges paired with matching OFF edges.
struct Cycle { bool open; unsigned long tOn; float dp; };
const float MIN_STEP_W = 150, REL_TOL = 0.06, ABS_TOL = 50;
const int CONFIRM = 2;
float level = -1, candSum = 0; int candN = 0; unsigned long candT = 0;
Cycle cycles[6];

const char* labelFor(float dp, float durS) {
  if (dp >= 950 && dp <= 1700 && (durS < 0 || (durS >= 40 && durS <= 480))) return "kettle";
  if (dp >= 900 && dp <= 1800) return "microwave";
  if (dp >= 250 && dp <= 900 && durS >= 240) return "furnace_blower";
  if (dp >= 500) return "human_unknown";
  return "unknown";
}
bool isHuman(const char* l) { return strcmp(l, "furnace_blower") && strcmp(l, "unknown"); }

void postEvent(const char* kind, const char* label, float dp, float durS);

void detect(float w) {
  unsigned long now = millis();
  if (level < 0) { level = w; return; }
  float tol = max(ABS_TOL, REL_TOL * level);
  if (candN == 0) {
    if (fabs(w - level) <= tol) { level += 0.1f * (w - level); return; }
    candSum = w; candN = 1; candT = now; return;
  }
  float cmean = candSum / candN;
  if (fabs(w - cmean) <= max(ABS_TOL, REL_TOL * cmean)) { candSum += w; candN++; }
  else if (fabs(w - level) <= tol) { candN = 0; return; }
  else { candSum = w; candN = 1; candT = now; return; }
  if (candN < CONFIRM) return;
  float newLevel = candSum / candN, dp = newLevel - level;
  candN = 0; level = newLevel;
  if (fabs(dp) < MIN_STEP_W) return;
  if (dp > 0) {
    for (auto& c : cycles) if (!c.open) { c = {true, candT, dp}; break; }
    postEvent("on", labelFor(dp, -1), dp, -1);
  } else {
    int best = -1; float err = 1e9;
    for (int i = 0; i < 6; i++) if (cycles[i].open) {
      float e = fabs(cycles[i].dp + dp);
      if (e < max(150.0f, 0.25f * cycles[i].dp) && e < err) { best = i; err = e; }
    }
    if (best >= 0) {
      cycles[best].open = false;
      float dur = (candT - cycles[best].tOn) / 1000.0f;
      postEvent("cycle", labelFor(cycles[best].dp, dur), cycles[best].dp, dur);
    }
  }
}

// ------------------------------------------------------------------ network
void wifiUp() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
}

int httpPost(const String& url, const String& body, const char* key = nullptr) {
  HTTPClient http;
  WiFiClientSecure tls;
  if (url.startsWith("https")) { tls.setInsecure(); http.begin(tls, url); }  // TODO: pin the CA in production
  else http.begin(url);
  http.addHeader("Content-Type", "application/json");
  if (key) http.addHeader("x-kettle-key", key);
  int code = http.POST(body);
  http.end();
  return code;
}

void postEvent(const char* kind, const char* label, float dp, float durS) {
#if OUTPUT_MODE == OUTPUT_EVENTS
  String body = String("{\"kind\":\"") + kind + "\",\"label\":\"" + label + "\",\"human\":" +
                (isHuman(label) ? "true" : "false") + ",\"channel\":\"esp32\",\"dp_w\":" + String(dp, 0);
  if (durS >= 0) body += ",\"duration_s\":" + String(durS, 0);
  body += "}";
  int code = httpPost(String(CLOUD_URL) + "/api/events/" + HOME_ID, body, DEVICE_KEY);
  Serial.printf("event %s %s %.0f W -> %d\n", kind, label, dp, code);
#endif
}

// ------------------------------------------------------------------ kitchen interface (hub mode)
bool checkinActive = false, glowActive = false;
unsigned long lastStatusMs = 0;

void pollHubStatus() {
#if OUTPUT_MODE == OUTPUT_HUB
  if (millis() - lastStatusMs < 2000) return;
  lastStatusMs = millis();
  HTTPClient http;
  http.begin(String(HUB_URL) + "/api/status");
  if (http.GET() == 200) {
    String s = http.getString();
    checkinActive = s.indexOf("\"checkin\":null") < 0 && s.indexOf("\"checkin\":") >= 0;
    glowActive = s.indexOf("\"glow\":null") < 0 && s.indexOf("\"glow\":") >= 0;
  }
  http.end();
#endif
}

void driveLed() {
  int duty = 0;
  if (checkinActive) duty = (int)(127 + 127 * sin(millis() / 350.0));   // slow pulse: "please press"
  else if (glowActive) duty = 180;                                      // warm, steady
  ledcWrite(LED_PIN, duty);
}

void checkButton() {
  static bool was = HIGH; static unsigned long t = 0;
  bool now = digitalRead(BUTTON_PIN);
  if (was == HIGH && now == LOW && millis() - t > 400) {
    t = millis();
#if OUTPUT_MODE == OUTPUT_HUB
    httpPost(String(HUB_URL) + "/api/im_fine", "{}");
#endif
    checkinActive = false;
    Serial.println("I'm fine pressed");
  }
  was = now;
}

// ------------------------------------------------------------------ main
void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  ledcAttach(LED_PIN, LED_CH_FREQ, 8);
#if SENSOR_MODE == SENSOR_PULSE
  pinMode(PULSE_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PULSE_PIN), onPulse, FALLING);
#else
  analogReadResolution(12);
  analogSetPinAttenuation(CT_PIN, ADC_11db);
#endif
  wifiUp();
  Serial.printf("Kettle sense up. IP %s\n", WiFi.localIP().toString().c_str());
}

unsigned long lastSampleMs = 0;

void loop() {
  wifiUp();
  checkButton();
  pollHubStatus();
  driveLed();
  if (millis() - lastSampleMs >= 1000) {
    lastSampleMs = millis();
    float w = readWatts();
#if OUTPUT_MODE == OUTPUT_HUB
    httpPost(String(HUB_URL) + "/api/push", String("{\"w\":") + String(w, 1) + ",\"source\":\"esp32\"}");
#else
    detect(w);
#endif
  }
  delay(10);
}
