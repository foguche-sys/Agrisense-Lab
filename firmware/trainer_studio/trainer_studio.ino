/*
  AgriSense Lab - Trainer Board <-> IoT Studio
  Heltec WiFi LoRa 32 V3. Posts the team's feeds every 5 s and switches outputs from the platform.

  Pins (Trainer Board v2, FIELD I/O; unchanged from the wiring atlas):
    RS485 probe  MAX3485  TX GPIO4  RX GPIO40  DE/RE GPIO41   4800 baud, address 1, regs 0..6
    Pressure     ADS1115 A2 through 10k/20k divider (0.5-4.5 V sensor, 0-30 psi)
    Tank level   MCP23017 pin 13, INPUT_PULLUP (float closed = OK)
    Relay 1 pump MCP23017 pin 11      Relay 2 fan  MCP23017 pin 12      Buzzer MCP pin 10
    Servo vent   PCA9685 ch0          AIR pod AHT20 0x38 (Qwiic)

  Safety is enforced HERE as well as on the server:
    pump max 30 s, 60 s rest, only with tank OK,
    stop on NO FLOW (< 10 kPa 2 s after start) or BLOCKED (> 150 kPa).
  Libraries: Adafruit ADS1X15, Adafruit MCP23017, Adafruit PWM Servo Driver, Adafruit AHTX0, ArduinoJson 7.
*/
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <Adafruit_MCP23X17.h>
#include <Adafruit_PWMServoDriver.h>
#include <Adafruit_AHTX0.h>
#include "secrets.h"

#define FW_VERSION "trainer-1.0.0"
#define RS485_TX 4
#define RS485_RX 40
#define RS485_DE 41
#define MCP_BUZZER 10
#define MCP_PUMP 11
#define MCP_FAN 12
#define MCP_LEVEL 13

const uint32_t PUMP_MAX_MS = 30000, PUMP_REST_MS = 60000, FLOW_CHECK_MS = 2000;
const float NO_FLOW_KPA = 10.0, BLOCKED_KPA = 150.0;

Adafruit_ADS1115 ads;
Adafruit_MCP23X17 mcp;
Adafruit_PWMServoDriver pca;
Adafruit_AHTX0 aht;
bool haveAht = false;

bool pumpOn = false, fanOn = false;
uint32_t pumpStart = 0, pumpStopAt = 0, pumpOffAt = 0, fanStopAt = 0, buzzerStopAt = 0;
String pendingEvent = "";
int ventDeg = 90;

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

void applyCommand(const String &cmd) {            // "SET,pump,ON,30" | "SET,vent,120" | "STOP" | "RESTART"
  Serial.println("cmd " + cmd);
  if (cmd == "STOP") { pumpOff("STOP"); fanOn = false; mcp.digitalWrite(MCP_FAN, LOW); return; }
  if (cmd == "RESTART") { ESP.restart(); }
  if (!cmd.startsWith("SET,")) return;
  int a = cmd.indexOf(',', 4), b = cmd.indexOf(',', a + 1);
  String comp = cmd.substring(4, a), val = b > 0 ? cmd.substring(a + 1, b) : cmd.substring(a + 1);
  uint32_t secs = b > 0 ? cmd.substring(b + 1).toInt() : 0;
  if (comp == "pump") { if (val == "ON") pumpStartFor((secs ? secs : 30) * 1000UL); else pumpOff("dashboard"); }
  else if (comp == "fan") { fanOn = val == "ON"; mcp.digitalWrite(MCP_FAN, fanOn); fanStopAt = (fanOn && secs) ? millis() + secs * 1000UL : 0; }
  else if (comp == "buzzer") { bool on = val == "ON"; mcp.digitalWrite(MCP_BUZZER, on); buzzerStopAt = on ? millis() + (secs ? secs : 2) * 1000UL : 0; }
  else if (comp == "vent") setVent(val.toInt());
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
void postFeeds() {
  JsonDocument doc;
  doc["firmware"] = FW_VERSION;
  doc["rssi"] = WiFi.RSSI();
  JsonObject f = doc["feeds"].to<JsonObject>();
  float m, t, ec, ph;
  if (readProbe(m, t, ec, ph)) f["moisture"] = m;
  if (haveAht) { sensors_event_t h, tp; aht.getEvent(&h, &tp); f["air-temp"] = tp.temperature; f["humidity"] = h.relative_humidity; }
  f["pressure"] = round(pressureKpa() * 10) / 10.0;
  f["tank"] = tankOk() ? "OK" : "LOW";
  f["pump"] = pumpOn ? "ON" : "OFF";
  f["fan"] = fanOn ? "ON" : "OFF";
  f["vent"] = ventDeg;
  if (pendingEvent.length()) doc["event"] = pendingEvent;
  String body; serializeJson(doc, body);

  HTTPClient http;
  http.begin(String(API_BASE) + "/api/v1/ingest");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  http.setTimeout(4000);
  int code = http.POST(body);
  if (code == 200) {
    pendingEvent = "";
    JsonDocument res; deserializeJson(res, http.getString());
    for (JsonVariant c : res["commands"].as<JsonArray>()) applyCommand(c.as<String>());
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
    for (JsonVariant c : res["commands"].as<JsonArray>()) applyCommand(c.as<String>());
  }
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(RS485_DE, OUTPUT); digitalWrite(RS485_DE, LOW);
  Serial1.begin(4800, SERIAL_8N1, RS485_RX, RS485_TX);
  Wire.begin();
  ads.begin(); ads.setGain(GAIN_ONE);
  mcp.begin_I2C();
  for (int i = 0; i <= 12; i++) { mcp.pinMode(i, OUTPUT); mcp.digitalWrite(i, LOW); }
  mcp.pinMode(14, OUTPUT); mcp.pinMode(15, OUTPUT);
  mcp.pinMode(MCP_LEVEL, INPUT_PULLUP);
  pca.begin(); pca.setPWMFreq(50); setVent(ventDeg);
  haveAht = aht.begin();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

uint32_t lastPost = 0, lastPoll = 0;
void loop() {
  safetyLoop();                                     // always runs, even offline
  if (WiFi.status() != WL_CONNECTED) { pumpOff("no Wi-Fi"); delay(50); return; }
  uint32_t now = millis();
  if (now - lastPost > 5000 || pendingEvent.length()) { lastPost = now; postFeeds(); }
  else if (now - lastPoll > 1000) { lastPoll = now; pollCommands(); }
  delay(20);
}
