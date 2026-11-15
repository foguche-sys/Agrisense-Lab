/*
  AgriSense Lab - Build deck sensor node (node E), lesson 1.6 "Build your own sensor node"
  Heltec WiFi LoRa 32 V3. Reads the 7-in-1 soil probe (RS485) and the plug-in pods, shows them on the
  screen, and sends the soil reading to the website.

  Two ways to send (set SEND_MODE below):
    SEND_WIFI (default, Starter kit): posts straight to /api/v1/ingest over the school Wi-Fi with the
               deck's own device key. No gateway needed.
    SEND_LORA (Field add-on): sends "R,<serial>,moisture,temp,EC,pH,N,P,K,supplyV" by LoRa to the
               field gateway, like nodes A-D.

  Pins (same as field nodes A-D, wiring sheet W2):
    RS485 MAX485  TX GPIO4  RX GPIO40 (through 1k/2k divider)  DE/RE GPIO41   4800 baud, address 1
    Pod rail      SDA GPIO5  SCL GPIO6 (3.3 V): AIR pod AHT20 0x38, LIGHT pod BH1750 0x23
    12 V monitor  GPIO7 through 47k/10k divider (optional)      Button GPIO0 (PRG)
    Screen        built-in OLED: SDA GPIO17, SCL GPIO18, RST GPIO21; Vext GPIO36 LOW = screen power on
  Libraries: Adafruit AHTX0, Adafruit SSD1306 + GFX, ArduinoJson 7, RadioLib (LoRa mode only).
*/
#define SEND_WIFI 1
#define SEND_LORA 2
#define SEND_MODE SEND_WIFI

#include <Wire.h>
#include <Adafruit_AHTX0.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include "secrets.h"
#if SEND_MODE == SEND_WIFI
#include <WiFi.h>
#include <HTTPClient.h>
#else
#include <RadioLib.h>
SX1262 radio = new Module(8, 14, 12, 13);              // Heltec V3: NSS, DIO1, RST, BUSY
#endif

#define FW_VERSION "deck-1.0.0"
#define RS485_TX 4
#define RS485_RX 40
#define RS485_DE 41
#define POD_SDA 5
#define POD_SCL 6
#define MON_12V 7
#define VEXT 36
#define OLED_RST 21
const uint32_t SEND_EVERY_MS = 60000;                // one reading a minute to the website
const uint8_t BH1750_ADDR = 0x23;

TwoWire podBus = TwoWire(1);                          // pods on their own bus; the screen uses Wire
Adafruit_SSD1306 screen(128, 64, &Wire, OLED_RST);
Adafruit_AHTX0 aht;
bool haveAht = false, haveLux = false, probeOk = false;
float moist = 0, stemp = 0, ec = 0, ph = 0, n = 0, p = 0, k = 0, airT = 0, hum = 0, lux = 0, supplyV = 0;
String sendStatus = "starting";

// ---------- RS485 soil probe (Modbus RTU function 03, registers 0..6) ----------
uint16_t crc16(const uint8_t *b, size_t len) {
  uint16_t c = 0xFFFF;
  for (size_t i = 0; i < len; i++) { c ^= b[i]; for (int j = 0; j < 8; j++) c = (c & 1) ? (c >> 1) ^ 0xA001 : c >> 1; }
  return c;
}
bool readProbe() {
  uint8_t q[8] = {0x01, 0x03, 0x00, 0x00, 0x00, 0x07, 0, 0};
  uint16_t c = crc16(q, 6); q[6] = c & 0xFF; q[7] = c >> 8;
  while (Serial1.available()) Serial1.read();
  digitalWrite(RS485_DE, HIGH); Serial1.write(q, 8); Serial1.flush(); digitalWrite(RS485_DE, LOW);
  uint8_t r[19]; size_t got = 0; uint32_t t0 = millis();
  while (got < 19 && millis() - t0 < 400) if (Serial1.available()) r[got++] = Serial1.read();
  if (got < 19 || r[0] != 0x01 || r[1] != 0x03 || crc16(r, 17) != (uint16_t)(r[17] | (r[18] << 8))) return false;
  moist = ((r[3] << 8) | r[4]) / 10.0;                // check your probe's datasheet: register map and scaling
  stemp = (int16_t)((r[5] << 8) | r[6]) / 10.0;
  ec    = (r[7] << 8) | r[8];
  ph    = ((r[9] << 8) | r[10]) / 10.0;
  n     = (r[11] << 8) | r[12];
  p     = (r[13] << 8) | r[14];
  k     = (r[15] << 8) | r[16];
  return true;
}

bool luxBegin() { podBus.beginTransmission(BH1750_ADDR); podBus.write(0x10); return podBus.endTransmission() == 0; }
bool readLux() {
  if (podBus.requestFrom(BH1750_ADDR, (uint8_t)2) != 2) return false;
  lux = ((podBus.read() << 8) | podBus.read()) / 1.2f; return true;
}

void readAll() {
  probeOk = readProbe();
  if (haveAht) { sensors_event_t h, t; if (aht.getEvent(&h, &t)) { airT = t.temperature; hum = h.relative_humidity; } }
  if (haveLux) readLux();
  supplyV = analogReadMilliVolts(MON_12V) / 1000.0 * (47.0 + 10.0) / 10.0;
}

void draw() {
  screen.clearDisplay(); screen.setTextColor(SSD1306_WHITE); screen.setTextSize(1); screen.setCursor(0, 0);
  screen.println("AgriSense node E");
  if (probeOk) { screen.printf("Moist %.1f%%  T %.1fC\n", moist, stemp); screen.printf("EC %.0f   pH %.1f\n", ec, ph); }
  else screen.println("Probe: no answer\n(check GX16 plug)");
  if (haveAht) screen.printf("Air %.1fC  RH %.0f%%\n", airT, hum); else screen.println("AIR pod: not found");
  if (haveLux) screen.printf("Light %.0f lux\n", lux); else screen.println("LIGHT pod: not found");
  screen.printf("12V %.1f  %s\n", supplyV, sendStatus.c_str());
  screen.display();
}

#if SEND_MODE == SEND_WIFI
void sendReading() {
  if (WiFi.status() != WL_CONNECTED) { sendStatus = "no Wi-Fi"; return; }
  JsonDocument doc;
  doc["firmware"] = FW_VERSION; doc["rssi"] = WiFi.RSSI();
  if (supplyV > 1) doc["supply_v"] = supplyV;
  if (probeOk) { doc["moisture"] = moist; doc["temp"] = stemp; doc["ec"] = ec; doc["ph"] = ph; doc["n"] = n; doc["p"] = p; doc["k"] = k; }
  else doc["fault"] = true;
  String body; serializeJson(doc, body);
  HTTPClient http;
  http.begin(String(API_BASE) + "/api/v1/ingest");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_KEY);
  http.setTimeout(5000);
  int code = http.POST(body);
  sendStatus = code == 200 ? "sent" : "HTTP " + String(code);
  http.end();
}
#else
void sendReading() {
  String pkt = probeOk ? "R," + String(NODE_SERIAL) + "," + String(moist, 1) + "," + String(stemp, 1) + "," + String(ec, 0) + "," +
                         String(ph, 1) + "," + String(n, 0) + "," + String(p, 0) + "," + String(k, 0) + "," + String(supplyV, 2)
                       : "F," + String(NODE_SERIAL);
  sendStatus = radio.transmit(pkt) == RADIOLIB_ERR_NONE ? "LoRa sent" : "LoRa error";
}
#endif

void setup() {
  Serial.begin(115200);
  pinMode(VEXT, OUTPUT); digitalWrite(VEXT, LOW); delay(50);       // power the screen
  Wire.begin(17, 18);
  screen.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  podBus.begin(POD_SDA, POD_SCL, 100000);
  haveAht = aht.begin(&podBus);
  haveLux = luxBegin();
  pinMode(RS485_DE, OUTPUT); digitalWrite(RS485_DE, LOW);
  Serial1.begin(4800, SERIAL_8N1, RS485_RX, RS485_TX);
  analogReadResolution(12);
#if SEND_MODE == SEND_WIFI
  WiFi.begin(WIFI_SSID, WIFI_PASS);
#else
  radio.begin(915.0, 125.0, 9, 7, 0x12, 14);         // US915; same settings as the gateway
#endif
}

uint32_t lastRead = 0, lastSend = 0;
void loop() {
  uint32_t now = millis();
  bool button = digitalRead(0) == LOW;                 // press PRG to send now (handy in lesson 1.6, step "Go live")
  if (now - lastRead > 2000) { lastRead = now; readAll(); draw(); }
  if (now - lastSend > SEND_EVERY_MS || (button && now - lastSend > 3000) || (lastSend == 0 && now > 8000)) {
    lastSend = now; sendReading(); draw();
  }
  delay(20);
}
