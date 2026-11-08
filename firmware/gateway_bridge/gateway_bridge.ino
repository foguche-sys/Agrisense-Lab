/*
  AgriSense Lab - bench gateway -> platform bridge
  Heltec WiFi LoRa 32 V3 (RadioLib SX1262). Receives node readings over LoRa and posts them to
  /api/v1/ingest; collects the pump node's commands and relays them over LoRa.

  LoRa packets this sketch expects (adapt parseNode() if your node firmware sends another format):
    node -> gateway:  "R,ND-1B33,24.1,19.2,410,6.5,37,12,94,3.31"   (serial, moisture, temp, EC, pH, N, P, K, battery V)
                      "F,ND-1B33"                                    (probe did not answer)
    pump -> gateway:  "P,DONE" | "P,NO_FLOW" | "P,BLOCKED" | "P,TANK_LOW" | "P,TANK_OK"
    gateway -> pump:  the platform command as-is: "RUN,60,B" or "STOP"
  The pump node keeps its own limits (300 s max, one tray at a time, stops on NO FLOW / BLOCKED).
*/
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <RadioLib.h>
#include "secrets.h"

#define FW_VERSION "gateway-1.0.0"
SX1262 radio = new Module(8, 14, 12, 13);           // Heltec V3: NSS, DIO1, RST, BUSY
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

void setup() {
  Serial.begin(115200);
  radio.begin(915.0, 125.0, 9, 7, 0x12, 14);       // US915; match your node settings
  radio.setDio1Action(onRx);
  radio.startReceive();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  resetBatch();
}

void loop() {
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
