/*
  AgriSense Lab - Trainer Board <-> IoT Studio
  Posts the team's feeds every 5 s and switches outputs from the platform. Wi-Fi only (no LoRa).
  Board (Tools > Board): "XIAO_ESP32S3" for 2026 kits (standard Radio Board) or "Heltec WiFi LoRa 32(V3)".

  Pins (Trainer Board v2, FIELD I/O):         XIAO_ESP32S3 (2026)              Heltec V3 (first kits)
    RS485 probe  MAX3485  TX                  D3 / GPIO4                       GPIO4
                          RX (1k/2k divider)  D7 / GPIO44                      GPIO40
                          DE/RE               D2 / GPIO3                       GPIO41
    Module bus (Wire)     SDA / SCL           D4 / D5 (GPIO5 / GPIO6)          GPIO5 / GPIO6
    STUDENT port (Wire1)  SDA / SCL           D0 / D1 (GPIO1 / GPIO2)          GPIO38 / GPIO39
    Screen                0.96" OLED 0x3C on the module bus                    (built-in screen not used)
    Coding post 12 A1     D8 / GPIO7 (analog in)                           GPIO7
    Coding post 14 D1     D9 / GPIO8 (digital in, pulled down)             GPIO47
    Coding post 15 D2     D10 / GPIO9 (free for student code)              GPIO48
    The Trainer's XIAO runs WITHOUT the Wio-SX1262 radio (unclip it, or buy a plain XIAO ESP32S3): the
    radio would use D8-D10, which are the coding posts here. The Trainer needs Wi-Fi only.
    4800 baud, address 1, regs 0..6
    Pressure     ADS1115 A2 through 10k/20k divider (0.5-4.5 V sensor, 0-30 psi)
    Tank level   MCP23017 pin 13, INPUT_PULLUP (float closed = OK)
    Relay 1 pump MCP23017 pin 11      Relay 2 fan  MCP23017 pin 12      Buzzer MCP pin 10
    Servo vent   PCA9685 ch0          AIR pod AHT20 0x38 (Qwiic)
    Knobs        ADS1115 A0 (knob 1) and A1 (knob 2), 0-3.3 V -> 0-100 %
    Motor        TB6612: PWMA = PCA9685 ch1, AIN1/AIN2 = MCP23017 pins 14/15, motor on load jacks L3
    Grow light   PCA9685 ch2 -> logic-level MOSFET module gate -> 12 V LED strip on load jacks L4 (white)
                 (PCA runs at 50 Hz for the servo, so dimming below ~30 % can flicker to the eye; plants don't mind)

  I2C buses (wiring sheet W5):
    Wire  = module bus (MCP23017, PCA9685, ADS1115, Qwiic port, pods, coding posts 10/11, XIAO screen 0x3C)
    Wire1 = STUDENT port (I2C target at 0x42 for the student's UNO R4; 3.3 V pad not connected)

  Safety is enforced HERE as well as on the server:
    pump max 30 s, 60 s rest, only with tank OK,
    stop on NO FLOW (< 10 kPa 2 s after start) or BLOCKED (> 150 kPa).
  STUDENT port (v1.2): student code can only ASK for a run (max 20 s). The Trainer decides with
  as_decide_pump() in agrisense_protocol.h: needs the teacher's unlock (sent by the website), Wi-Fi,
  rest time, tank, a probe reading and soil below 40 %. Answers OK or a REFUSED code.
  Libraries: Adafruit ADS1X15, Adafruit MCP23017, Adafruit PWM Servo Driver, Adafruit AHTX0, ArduinoJson 7,
             Adafruit SSD1306 + Adafruit GFX.
*/
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <Adafruit_MCP23X17.h>
#include <Adafruit_PWMServoDriver.h>
#include <Adafruit_AHTX0.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "secrets.h"
#include "agrisense_protocol.h"

#define FW_VERSION "trainer-1.5.0"
#define PCA_GROW 2
#define PCA_MOTOR 1
#define MCP_AIN1 14
#define MCP_AIN2 15
#define RS485_TX 4
#if defined(ARDUINO_XIAO_ESP32S3)
#define RS485_RX 44
#define RS485_DE 3
#define STUDENT_SDA 1
#define STUDENT_SCL 2
#define POST_A1 7      // D8, coding post 12
#define POST_D1 8      // D9, coding post 14
#define POST_D2 9      // D10, coding post 15 (not driven by this program)
#else
#define POST_A1 7
#define POST_D1 47
#define POST_D2 48
#define RS485_RX 40
#define RS485_DE 41
#define STUDENT_SDA 38
#define STUDENT_SCL 39
#endif
#define MCP_BUZZER 10
#define MCP_PUMP 11
#define MCP_FAN 12
#define MCP_LEVEL 13
#define I2C_SDA 5
#define I2C_SCL 6

const uint32_t PUMP_MAX_MS = 30000, PUMP_REST_MS = 60000, FLOW_CHECK_MS = 2000;
const float NO_FLOW_KPA = 10.0, BLOCKED_KPA = 150.0;

Adafruit_SSD1306 screen(128, 64, &Wire, -1);   // optional status screen on the module bus (XIAO Radio Board)
bool screenOk = false;
Adafruit_ADS1115 ads;
Adafruit_MCP23X17 mcp;
Adafruit_PWMServoDriver pca;
Adafruit_AHTX0 aht;
bool haveAht = false, haveLux = false;
const uint8_t BH1750_ADDR = 0x23;            // LIGHT pod (Qwiic)

bool pumpOn = false, fanOn = false;
uint32_t pumpStart = 0, pumpStopAt = 0, pumpOffAt = 0, fanStopAt = 0, buzzerStopAt = 0;
String pendingEvent = "";
int ventDeg = 90;
int growPct = 0;
int motorVal = 0;                                 // -100..100
float knob1 = 0, knob2 = 0;

// ---------- cached sensor readings (probe read every 2 s; shared by the website post and the STUDENT port) ----------
bool probeOk = false; float sMoist = 0, sTemp = 0, sEc = 0, sPh = 0, sAirT = 0, sHum = 0, sLux = 0;
bool airOk = false, luxOk = false;
uint32_t lastSensorRead = 0, lastServerOk = 0, studentUnlockUntil = 0;

// ---------- STUDENT port state (I2C target on Wire1) ----------
portMUX_TYPE stuMux = portMUX_INITIALIZER_UNLOCKED;
volatile uint8_t stuCmd = 0, stuArg = 0;
volatile bool stuNew = false;
uint8_t stuSnap[AS_SNAPSHOT_LEN];                // last snapshot, ready to send
uint8_t stuReply[2] = {AS_PENDING, 0};           // reply to the last command
volatile bool stuWantSnap = true;                // the next read returns the snapshot (else the 2-byte reply)
String studentEvent = "";                        // reported to the website with the next post

// ---------- RS485 soil probe (Modbus RTU function 03) ----------
uint16_t crc16(const uint8_t *b, size_t n) {
  uint16_t c = 0xFFFF;
  for (size_t i = 0; i < n; i++) { c ^= b[i]; for (int k = 0; k < 8; k++) c = (c & 1) ? (c >> 1) ^ 0xA001 : c >> 1; }
  return c;
}
bool readProbe(float &moist, float &temp, float &ec, float &ph) {
  uint8_t q[8] = {0x01, 0x03, 0x00, 0x00, 0x00, 0x04, 0, 0};
  uint16_t c = crc16(q, 6); q[6] = c & 0xFF; q[7] = c >> 8;
  while (Serial1.available()) Serial1.read();
  digitalWrite(RS485_DE, HIGH); Serial1.write(q, 8); Serial1.flush(); digitalWrite(RS485_DE, LOW);
  uint8_t r[13]; size_t n = 0; uint32_t t0 = millis();
  while (n < 13 && millis() - t0 < 300) if (Serial1.available()) r[n++] = Serial1.read();
  if (n < 13 || r[0] != 0x01 || r[1] != 0x03 || crc16(r, 11) != (uint16_t)(r[11] | (r[12] << 8))) return false;
  moist = ((r[3] << 8) | r[4]) / 10.0;               // check your probe's datasheet: register map and scaling
  temp  = (int16_t)((r[5] << 8) | r[6]) / 10.0;
  ec    = (r[7] << 8) | r[8];
  ph    = ((r[9] << 8) | r[10]) / 10.0;
  return true;
}

float pressureKpa() {
  float vAdc = ads.computeVolts(ads.readADC_SingleEnded(2));
  float vSensor = vAdc * 1.5;                        // 10k/20k divider
  float psi = (vSensor - 0.5) / 4.0 * 30.0;
  return max(0.0f, psi * 6.895f);
}
bool tankOk() { return mcp.digitalRead(MCP_LEVEL) == LOW; }

// ---------- outputs ----------
void pumpOff(const char *why) {
  if (pumpOn) { pumpOffAt = millis(); Serial.printf("pump OFF (%s)\n", why); }
  pumpOn = false; mcp.digitalWrite(MCP_PUMP, LOW);
}
bool pumpStartFor(uint32_t ms) {
  if (!tankOk()) { pendingEvent = "tank_low"; return false; }
  if (pumpOffAt && millis() - pumpOffAt < PUMP_REST_MS) return false;
  pumpOn = true; pumpStart = millis(); pumpStopAt = pumpStart + min(ms, PUMP_MAX_MS);
  mcp.digitalWrite(MCP_PUMP, HIGH); return true;
}
void setVent(int deg) {
  ventDeg = constrain(deg, 0, 180);
  pca.setPWM(0, 0, map(ventDeg, 0, 180, 110, 510)); // 0.5-2.5 ms at 50 Hz
}

// ---------- LIGHT pod: BH1750, read directly (no library) ----------
bool luxBegin() {
  Wire.beginTransmission(BH1750_ADDR); Wire.write(0x10);   // continuous high-resolution mode
  return Wire.endTransmission() == 0;
}
bool readLux(float &lux) {
  if (Wire.requestFrom(BH1750_ADDR, (uint8_t)2) != 2) return false;
  uint16_t raw = (Wire.read() << 8) | Wire.read();
  lux = raw / 1.2f; return true;
}

void setGrow(int pct) {                            // 0-100 % -> PCA9685 duty on ch 2 (MOSFET gate)
  growPct = constrain(pct, 0, 100);
  if (growPct == 0) pca.setPWM(PCA_GROW, 0, 4096);        // fully off
  else if (growPct == 100) pca.setPWM(PCA_GROW, 4096, 0); // fully on
  else pca.setPWM(PCA_GROW, 0, map(growPct, 0, 100, 0, 4095));
}

void setMotor(int v) {                             // -100..100: sign = direction, size = speed (lesson 3.5)
  motorVal = constrain(v, -100, 100);
  mcp.digitalWrite(MCP_AIN1, motorVal > 0);
  mcp.digitalWrite(MCP_AIN2, motorVal < 0);
  if (motorVal == 0) pca.setPWM(PCA_MOTOR, 0, 4096);  // fully off
  else pca.setPWM(PCA_MOTOR, 0, map(abs(motorVal), 0, 100, 0, 4095));
}

void applyCommand(const String &cmd) {            // "SET,pump,ON,30" | "SET,vent,120" | "STOP" | "RESTART"
  Serial.println("cmd " + cmd);
  if (cmd == "STOP") { pumpOff("STOP"); fanOn = false; mcp.digitalWrite(MCP_FAN, LOW); setGrow(0); setMotor(0); return; }
  if (cmd == "RESTART") { ESP.restart(); }
  if (!cmd.startsWith("SET,")) return;
  int a = cmd.indexOf(',', 4), b = cmd.indexOf(',', a + 1);
  String comp = cmd.substring(4, a), val = b > 0 ? cmd.substring(a + 1, b) : cmd.substring(a + 1);
  uint32_t secs = b > 0 ? cmd.substring(b + 1).toInt() : 0;
  if (comp == "pump") { if (val == "ON") pumpStartFor((secs ? secs : 30) * 1000UL); else pumpOff("dashboard"); }
  else if (comp == "fan") { fanOn = val == "ON"; mcp.digitalWrite(MCP_FAN, fanOn); fanStopAt = (fanOn && secs) ? millis() + secs * 1000UL : 0; }
  else if (comp == "buzzer") { bool on = val == "ON"; mcp.digitalWrite(MCP_BUZZER, on); buzzerStopAt = on ? millis() + (secs ? secs : 2) * 1000UL : 0; }
  else if (comp == "vent") setVent(val.toInt());
  else if (comp == "growlight") setGrow(val == "ON" ? 100 : val == "OFF" ? 0 : val.toInt());
  else if (comp == "motor") setMotor(val == "OFF" ? 0 : val.toInt());
  else if (comp == "ledbar") { int n = constrain(val.toInt(), 0, 10); for (int i = 0; i < 10; i++) mcp.digitalWrite(i, i < n); }
}

void safetyLoop() {
  uint32_t now = millis();
  if (pumpOn) {
    float kpa = pressureKpa();
    if (now >= pumpStopAt) pumpOff("30 s limit");
    else if (!tankOk()) { pumpOff("tank low"); pendingEvent = "tank_low"; }
    else if (now - pumpStart > FLOW_CHECK_MS && kpa < NO_FLOW_KPA) { pumpOff("NO FLOW"); pendingEvent = "no_flow"; }
    else if (kpa > BLOCKED_KPA) { pumpOff("BLOCKED"); pendingEvent = "blocked"; }
  }
  if (fanStopAt && now >= fanStopAt) { fanOn = false; fanStopAt = 0; mcp.digitalWrite(MCP_FAN, LOW); }
  if (buzzerStopAt && now >= buzzerStopAt) { buzzerStopAt = 0; mcp.digitalWrite(MCP_BUZZER, LOW); }
}

// ---------- platform ----------
void readSensors() {
  float m, t, ec, ph;
  probeOk = readProbe(m, t, ec, ph);
  if (probeOk) { sMoist = m; sTemp = t; sEc = ec; sPh = ph; }
  airOk = false;
  if (haveAht) { sensors_event_t h, tp; if (aht.getEvent(&h, &tp)) { sAirT = tp.temperature; sHum = h.relative_humidity; airOk = true; } }
  float lux; luxOk = haveLux && readLux(lux); if (luxOk) sLux = lux;
  knob1 = constrain(ads.computeVolts(ads.readADC_SingleEnded(0)) / 3.3f * 100.0f, 0.0f, 100.0f);
  knob2 = constrain(ads.computeVolts(ads.readADC_SingleEnded(1)) / 3.3f * 100.0f, 0.0f, 100.0f);
  lastSensorRead = millis();
}

// ---------- STUDENT port ----------
bool online() { return WiFi.status() == WL_CONNECTED && lastServerOk && millis() - lastServerOk < 30000; }
bool studentUnlocked() { return online() && studentUnlockUntil && (int32_t)(studentUnlockUntil - millis()) > 0; }

void studentSnapshot() {                          // rebuild the 20-byte snapshot from the cached readings
  AsSnapshot s;
  s.flags = (probeOk ? AS_F_PROBE : 0) | (tankOk() ? AS_F_TANK : 0) | (pumpOn ? AS_F_PUMP : 0) |
            (studentUnlocked() ? AS_F_UNLOCKED : 0) | (airOk ? AS_F_AIR : 0) | (luxOk ? AS_F_LIGHT : 0) | (online() ? AS_F_ONLINE : 0);
  s.moisture = sMoist; s.soilTemp = sTemp; s.ec = sEc; s.ph = sPh; s.pressure = pressureKpa();
  s.airTemp = sAirT; s.humidity = sHum; s.lux = sLux;
  s.pumpLeft = pumpOn && pumpStopAt > millis() ? (uint8_t)min<uint32_t>(255, (pumpStopAt - millis()) / 1000 + 1) : 0;
  uint8_t buf[AS_SNAPSHOT_LEN]; as_pack_snapshot(s, buf);
  portENTER_CRITICAL(&stuMux); memcpy(stuSnap, buf, AS_SNAPSHOT_LEN); portEXIT_CRITICAL(&stuMux);
}

void onStudentReceive(int n) {                   // runs in the I2C task: only store, decide in loop()
  if (n < 1) return;
  uint8_t c = Wire1.read(), a = n > 1 ? Wire1.read() : 0;
  while (Wire1.available()) Wire1.read();
  portENTER_CRITICAL(&stuMux);
  if (c == AS_CMD_SNAPSHOT) stuWantSnap = true;
  else { stuWantSnap = false; stuCmd = c; stuArg = a; stuNew = true; stuReply[0] = AS_PENDING; stuReply[1] = 0; }
  portEXIT_CRITICAL(&stuMux);
}

void onStudentRequest() {
  uint8_t buf[AS_SNAPSHOT_LEN]; size_t n;
  portENTER_CRITICAL(&stuMux);
  if (stuWantSnap) { memcpy(buf, stuSnap, AS_SNAPSHOT_LEN); n = AS_SNAPSHOT_LEN; }
  else { buf[0] = stuReply[0]; buf[1] = stuReply[1]; n = 2; }
  portEXIT_CRITICAL(&stuMux);
  Wire1.write(buf, n);
}

void studentBegin() {
  studentSnapshot();
  Wire1.onReceive(onStudentReceive);
  Wire1.onRequest(onStudentRequest);
  Wire1.begin((uint8_t)AS_I2C_ADDR, STUDENT_SDA, STUDENT_SCL, 100000);
}

void studentLoop() {                              // decide queued STUDENT commands with the Trainer's own rules
  if (!stuNew) return;
  portENTER_CRITICAL(&stuMux); uint8_t c = stuCmd, a = stuArg; stuNew = false; portEXIT_CRITICAL(&stuMux);
  uint8_t res = AS_BAD_CMD, wait = 0;
  if (c == AS_CMD_PUMP) {
    AsPumpState st{online(), studentUnlocked(), tankOk(), probeOk, pumpOn, sMoist,
                   pumpOffAt ? (millis() - pumpOffAt) / 1000 : 100000UL};
    res = as_decide_pump(st, a, wait);
    if (res == AS_OK && !pumpStartFor(a * 1000UL)) res = tankOk() ? AS_TOO_SOON : AS_TANK_LOW;
    studentEvent = res == AS_OK ? "pump_ok:" + String(a) : "refused:" + String(res);
    Serial.printf("STUDENT pump %u s -> %s\n", a, as_reason(res));
  } else if (c == AS_CMD_STOP) { pumpOff("STUDENT stop"); res = AS_OK; }
  else if (c == AS_CMD_BEEP) { uint8_t t = a < 1 ? 1 : a > 10 ? 10 : a; mcp.digitalWrite(MCP_BUZZER, HIGH); buzzerStopAt = millis() + t * 100UL; res = AS_OK; }
  else if (c == AS_CMD_LEDBAR) { int k = a > 10 ? 10 : a; for (int i = 0; i < 10; i++) mcp.digitalWrite(i, i < k); res = AS_OK; }
  portENTER_CRITICAL(&stuMux); stuReply[0] = res; stuReply[1] = wait; portEXIT_CRITICAL(&stuMux);
}

void readServerReply(JsonDocument &res) {
  lastServerOk = millis();
  JsonVariant su = res["student"]["unlocked_s"];
  if (!su.isNull()) { long u = su.as<long>(); studentUnlockUntil = u > 0 ? millis() + (uint32_t)u * 1000UL : 0; }
  for (JsonVariant c : res["commands"].as<JsonArray>()) applyCommand(c.as<String>());
}

// ---------- platform ----------
void postFeeds() {
  JsonDocument doc;
  doc["firmware"] = FW_VERSION;
  doc["rssi"] = WiFi.RSSI();
  JsonObject f = doc["feeds"].to<JsonObject>();
  if (probeOk) f["moisture"] = sMoist;
  if (airOk) { f["air-temp"] = sAirT; f["humidity"] = sHum; }
  if (luxOk) f["light"] = round(sLux);
  f["pressure"] = round(pressureKpa() * 10) / 10.0;
  f["tank"] = tankOk() ? "OK" : "LOW";
  f["pump"] = pumpOn ? "ON" : "OFF";
  f["fan"] = fanOn ? "ON" : "OFF";
  f["vent"] = ventDeg;
  f["growlight"] = growPct;
  f["motor"] = motorVal;
  f["knob-1"] = round(knob1);
  f["knob-2"] = round(knob2);
  f["post-a1"] = round(analogReadMilliVolts(POST_A1) / 10.0) / 100.0;     // volts, 0-3.1 V
  f["post-d1"] = digitalRead(POST_D1) == HIGH ? "HIGH" : "LOW";
  if (pendingEvent.length()) doc["event"] = pendingEvent;
  if (studentEvent.length()) doc["student_event"] = studentEvent;
  String body; serializeJson(doc, body);

  HTTPClient http;
  http.begin(String(API_BASE) + "/api/v1/ingest");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  http.setTimeout(4000);
  int code = http.POST(body);
  if (code == 200) {
    pendingEvent = ""; studentEvent = "";
    JsonDocument res; deserializeJson(res, http.getString());
    readServerReply(res);
  } else Serial.printf("ingest HTTP %d\n", code);
  http.end();
}
void pollCommands() {
  HTTPClient http;
  http.begin(String(API_BASE) + "/api/v1/commands");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  http.setTimeout(3000);
  if (http.GET() == 200) {
    JsonDocument res; deserializeJson(res, http.getString());
    readServerReply(res);
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(RS485_DE, OUTPUT); digitalWrite(RS485_DE, LOW);
  Serial1.begin(4800, SERIAL_8N1, RS485_RX, RS485_TX);
  Wire.begin(I2C_SDA, I2C_SCL);                     // module bus (was Wire.begin(): wrong default pins on the Heltec V3)
  ads.begin(); ads.setGain(GAIN_ONE);
  mcp.begin_I2C();
  for (int i = 0; i <= 12; i++) { mcp.pinMode(i, OUTPUT); mcp.digitalWrite(i, LOW); }
  mcp.pinMode(14, OUTPUT); mcp.pinMode(15, OUTPUT);
  mcp.pinMode(MCP_LEVEL, INPUT_PULLUP);
  pca.begin(); pca.setPWMFreq(50); setVent(ventDeg); setGrow(0); setMotor(0);
  haveLux = luxBegin();
  haveAht = aht.begin();
  studentBegin();
  pinMode(POST_A1, INPUT); analogSetPinAttenuation(POST_A1, ADC_11db);   // coding posts: inputs only, never driven
  pinMode(POST_D1, INPUT_PULLDOWN);                                       // reads LOW until a student wires it to 3V3
  pinMode(POST_D2, INPUT);
#if defined(ARDUINO_XIAO_ESP32S3)
  screenOk = screen.begin(SSD1306_SWITCHCAPVCC, 0x3C);
#endif
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

void drawStatus() {
  if (!screenOk) return;
  screen.clearDisplay(); screen.setTextColor(SSD1306_WHITE); screen.setTextSize(1); screen.setCursor(0, 0);
  screen.println("AgriSense TRAINER");
  screen.println(WiFi.status() == WL_CONNECTED ? "Wi-Fi OK " + WiFi.localIP().toString() : String("Wi-Fi: connecting"));
  screen.println(FW_VERSION);
  screen.display();
}

uint32_t lastPost = 0, lastPoll = 0, lastSnap = 0;
void loop() {
  safetyLoop();                                     // always runs, even offline
  uint32_t now = millis();
  if (now - lastSensorRead > 2000) readSensors();
  if (now - lastSnap > 250) { lastSnap = now; studentSnapshot(); }
  static uint32_t lastDraw = 0;
  if (now - lastDraw > 2000) { lastDraw = now; drawStatus(); }
  studentLoop();                                    // answers the STUDENT port even offline (with REFUSED: offline)
  if (WiFi.status() != WL_CONNECTED) { pumpOff("no Wi-Fi"); delay(20); return; }
  if (now - lastPost > 5000 || pendingEvent.length() || studentEvent.length()) { lastPost = now; postFeeds(); }
  else if (now - lastPoll > 1000) { lastPoll = now; pollCommands(); }
  delay(20);
}
