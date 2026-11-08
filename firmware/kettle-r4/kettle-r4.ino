/*
  Kettle kitchen interface for the Arduino UNO R4 Minima (USB serial, no Wi-Fi).

  Wiring (docs/wiring.html):
    big button  COM -> GND, NO -> D2      (internal pull-up, pressed = LOW)
    warm LED    D9 -> 330-1k resistor -> LED(+), LED(-) -> GND

  Serial protocol, 115200 baud, one command per line:
    laptop -> board   off | on | pulse | glow | b<0-255> | ping
    board -> laptop   ready            after boot
                      fine             the big button was pressed ("I'm fine")
                      mode <name>      acknowledges a command
                      pong             reply to ping

  Light modes: off; on = full; pulse = slow breathing ("please press");
  glow = warm and steady ("thinking of you"). Pressing the button during a
  pulse stops it, so the light answers even before the laptop does.
*/

const int BUTTON_PIN = 2;
const int LED_PIN = 9;             // PWM
const int GLOW_LEVEL = 140;
const int MAX_LEVEL = 255;

enum Mode { OFF, ON, PULSE, GLOW, RAW };
Mode mode = OFF;
int rawLevel = 0;
unsigned long flashUntil = 0;
String line;

const char* modeName(Mode m) {
  switch (m) { case ON: return "on"; case PULSE: return "pulse"; case GLOW: return "glow"; case RAW: return "raw"; default: return "off"; }
}

void setMode(Mode m) { mode = m; Serial.print("mode "); Serial.println(modeName(m)); }

void handle(String cmd) {
  cmd.trim(); cmd.toLowerCase();
  if (cmd == "off") setMode(OFF);
  else if (cmd == "on") setMode(ON);
  else if (cmd == "pulse") setMode(PULSE);
  else if (cmd == "glow") setMode(GLOW);
  else if (cmd == "ping") Serial.println("pong");
  else if (cmd.length() > 1 && cmd[0] == 'b') { rawLevel = constrain(cmd.substring(1).toInt(), 0, 255); setMode(RAW); }
  else if (cmd.length()) { Serial.print("error unknown "); Serial.println(cmd); }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') { if (line.length()) handle(line); line = ""; }
    else if (line.length() < 32) line += c;
  }
}

void checkButton() {
  static bool was = HIGH;
  static unsigned long changedAt = 0;
  bool now = digitalRead(BUTTON_PIN);
  if (now != was && millis() - changedAt > 40) {
    changedAt = millis();
    was = now;
    if (now == LOW) {
      Serial.println("fine");
      flashUntil = millis() + 600;          // acknowledge the press with a bright flash
      if (mode == PULSE) mode = OFF;        // the check-in is answered
    }
  }
}

void driveLed() {
  int level;
  if (millis() < flashUntil) level = MAX_LEVEL;
  else switch (mode) {
    case ON: level = MAX_LEVEL; break;
    case GLOW: level = GLOW_LEVEL; break;
    case RAW: level = rawLevel; break;
    case PULSE: level = (int)(8 + (MAX_LEVEL - 8) * (0.5 - 0.5 * cos(millis() / 1600.0 * 2 * PI))); break;
    default: level = 0;
  }
  analogWrite(LED_PIN, level);
}

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  analogWrite(LED_PIN, 0);
  Serial.println("ready");
}

void loop() {
  readSerial();
  checkButton();
  driveLed();
  delay(5);
}
