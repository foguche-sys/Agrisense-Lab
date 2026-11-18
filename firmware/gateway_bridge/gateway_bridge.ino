/*
  AgriSense Lab - bench gateway -> platform bridge
  Heltec WiFi LoRa 32 V3 (RadioLib SX1262). Receives node readings over LoRa and posts them to
  /api/v1/ingest; collects the pump node's commands and relays them over LoRa.

  LoRa packets this sketch expects (adapt parseNode() if your node firmware sends another format):
    node -> gateway:  "R,ND-1B33,24.1,19.2,410,6.5,37,12,94,3.31"   (serial, moisture, temp, EC, pH, N, P, K, battery V)
                      "F,ND-1B33"                                    (probe did not answer)
    pump -> gateway:  "P,DONE" | "P,NO_FLOW" | "P,BLOCKED" | "P,PRESSURE_FAULT"  (firmware/pump_node)
                      "P,TANK_LOW" | "P,TANK_OK"  (only if a pump node has a float switch; the kit's does not)
    gateway -> pump:  the platform command as-is: "RUN,60,B" or "STOP"
  The pump node keeps its own limits (300 s max, one tray at a time, stops on NO FLOW / BLOCKED).

  Board (Tools > Board): "XIAO_ESP32S3" for 2026 kits (standard Radio Board: 0.96" OLED on D4/D5 = GPIO5/6) or
  "Heltec WiFi LoRa 32(V3)" for first kits (built-in OLED). Radio pins and settings: agrisense_radio.h.
  Libraries: RadioLib, ArduinoJson 7, Adafruit SSD1306 + Adafruit GFX.
*/
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "agrisense_radio.h"
#include "secrets.h"

#define FW_VERSION "gateway-1.1.0"
#if defined(ARDUINO_XIAO_ESP32S3)
Adafruit_SSD1306 screen(128, 64, &Wire, -1);
#else
Adafruit_SSD1306 screen(128, 64, &Wire, 21);
#endif
bool screenOk = false, radioOk = false;
uint32_t forwarded = 0; String lastNode = "-"; int lastRssi = 0; String lastHttp = "-";
volatile bool rxFlag = false;
void IRAM_ATTR onRx() { rxFlag = true; }

JsonDocument batch;
JsonArray readings;
String pumpEvent = "", tankState = "";
uint32_t lastSend = 0, lastPumpPoll = 0;

void resetBatch() { batch.clear(); readings = batch["readings"].to<JsonArray>(); }

void parseNode(const String &p, int rssi) {
  if (p.startsWith("P,")) {                        // pump node status
    String ev = p.substring(2); ev.toLowerCase();
    if (ev == "tank_ok") tankState = "OK"; else pumpEvent = ev;
    return;
  }
  JsonObject r = readings.add<JsonObject>();
  float v[8]; int idx = 0, start = 2, comma = p.indexOf(',', start);
  r["node"] = comma > 0 ? p.substring(start, comma) : p.substring(start);
  r["rssi"] = rssi;
  lastNode = r["node"].as<String>(); lastRssi = rssi;
  if (p.startsWith("F,")) { r["fault"] = true; return; }
  while (comma > 0 && idx < 8) {
    int next = p.indexOf(',', comma + 1);
    v[idx++] = (next > 0 ? p.substring(comma + 1, next) : p.substring(comma + 1)).toFloat();
    comma = next;
  }
  const char *keys[] = {"moisture", "temp", "ec", "ph", "n", "p", "k", "supply_v"};
  for (int i = 0; i < idx; i++) r[keys[i]] = v[i];
}

String post(const char *key, const String &body) {
  HTTPClient http;
  http.begin(String(API_BASE) + "/api/v1/ingest");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", key);
  http.setTimeout(5000);
  int code = http.POST(body);
  String out = code == 200 ? http.getString() : "";
  if (code != 200) Serial.printf("ingest HTTP %d\n", code);
  lastHttp = String(code);
  http.end();
  return out;
}

void relay(const String &res) {
  if (!res.length()) return;
  JsonDocument doc; deserializeJson(doc, res);
  for (JsonVariant c : doc["commands"].as<JsonArray>()) {
    String cmd = c.as<String>();
    Serial.println("-> pump " + cmd);
    radio.transmit(cmd); radio.startReceive();
  }
}

void draw() {
  if (!screenOk) return;
  screen.clearDisplay(); screen.setTextColor(SSD1306_WHITE); screen.setTextSize(1); screen.setCursor(0, 0);
  screen.println("AgriSense GATEWAY");
  screen.println(WiFi.status() == WL_CONNECTED ? "Wi-Fi OK " + WiFi.localIP().toString() : String("Wi-Fi: connecting"));
  screen.println(radioOk ? "LoRa 909.4 MHz ready" : "LoRa: RADIO NOT FOUND");
  screen.printf("Readings sent %lu\n", (unsigned long)forwarded);
  screen.printf("Last %s %ddBm\n", lastNode.c_str(), lastRssi);
  screen.printf("Website HTTP %s\n", lastHttp.c_str());
  screen.display();
}

void setup() {
  Serial.begin(115200);
#if defined(ARDUINO_XIAO_ESP32S3)
  Wire.begin(5, 6);
#else
  pinMode(36, OUTPUT); digitalWrite(36, LOW); delay(50);      // Heltec: power the built-in screen
  Wire.begin(17, 18);
#endif
  screenOk = screen.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  int st = radioBegin();                           // agrisense_radio.h: same settings as every node
  radioOk = st == RADIOLIB_ERR_NONE;
  if (!radioOk) Serial.printf("radio.begin failed: %d\n", st);
  radio.setDio1Action(onRx);
  radio.startReceive();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  resetBatch();
}

void loop() {
  static uint32_t lastDraw = 0;
  if (millis() - lastDraw > 1000) { lastDraw = millis(); draw(); }
  if (rxFlag) {
    rxFlag = false;
    String p; if (radio.readData(p) == RADIOLIB_ERR_NONE) parseNode(p, (int)radio.getRSSI());
    radio.startReceive();
  }
  if (WiFi.status() != WL_CONNECTED) { delay(20); return; }
  uint32_t now = millis();
  if (readings.size() && (now - lastSend > 10000 || readings.size() >= 10)) {
    batch["firmware"] = FW_VERSION; batch["rssi"] = WiFi.RSSI();
    String body; serializeJson(batch, body);
    forwarded += readings.size();
    post(DEVICE_KEY, body); resetBatch(); lastSend = now;
  }
  if (now - lastPumpPoll > 1500 || pumpEvent.length()) {      // pump node: report events, collect RUN/STOP
    JsonDocument p; p["firmware"] = FW_VERSION;
    if (pumpEvent.length()) p["event"] = pumpEvent;
    if (tankState.length()) p["tank"] = tankState;
    String body; serializeJson(p, body);
    relay(post(PUMP_KEY, body));
    pumpEvent = ""; tankState = ""; lastPumpPoll = now;
  }
  delay(10);
}
