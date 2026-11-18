/*
  AgriSense Lab - pump node (Field add-on), Heltec WiFi LoRa 32 V3
  Waters one tray at a time when the website approves a run. The gateway collects the command from the
  website and sends it here by LoRa; this node reports back what happened.

  LoRa (same radio settings as gateway_bridge.ino and the field nodes):
    gateway -> pump:  "RUN,<seconds>,<tray letter>"  e.g. "RUN,60,B"     or  "STOP"
    pump -> gateway:  "P,DONE" | "P,NO_FLOW" | "P,BLOCKED" | "P,PRESSURE_FAULT"   (each sent twice, 2 s apart)
  Any other packet (the field nodes' readings) is ignored.

  Safety, enforced here even if the website or the radio misbehaves (logic in pump_logic.h):
    - never longer than 300 s, one run at a time, at least 10 s rest between runs (a RUN during the rest waits)
    - stops on NO FLOW (under 10 kPa, 3 s after start) or BLOCKED (over 150 kPa for 0.5 s)
    - will not start, and stops, if the pressure sensor is unplugged
    - relays are OFF at power-up and if the program hangs (watchdog restarts the board within 5 s)
    - lid button: press = STOP; hold 3 s when idle = 5 s test run (to prime the line; not reported as a run)

  Pins (pump node wiring, inside the jack-panel case). Picked from Tools > Board:
                   "XIAO_ESP32S3" (2026 kits, Radio Board)    "Heltec WiFi LoRa 32(V3)" (first kits)
    Relay 1 PUMP   D3 / GPIO4                                 GPIO5
    Relay 2 VALVE  D2 / GPIO3                                 GPIO4
    Pressure SIG   D0 / GPIO1                                 GPIO6
    12 V monitor   D1 / GPIO2                                 GPIO7
    Lid button     D7 / GPIO44 to GND                         GPIO0 (PRG) to GND
    Screen         0.96" OLED on D4/D5 (GPIO5/6)              built-in OLED (GPIO17/18, RST 21, Vext 36)
    Relays: 1-channel 5 V, high-level trigger (HIGH = on), 10k pull-down IN to GND (keeps them off while the
    board starts). Valve opens 0.3 s before the pump and closes 0.3 s after. Pressure through the 10k/20k
    divider (sensor 0.5-4.5 V). 12 V monitor through 47k/10k (optional; shows "12V --" if not fitted).
    XIAO: never use D6 (GPIO43) for a relay - it carries boot messages at power-up. D8-D10 belong to the radio.
  Libraries (Arduino Library Manager): RadioLib, Adafruit SSD1306 + Adafruit GFX.
  No Wi-Fi and no keys: this node only talks LoRa, so there is no secrets.h.
*/
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <esp_task_wdt.h>
#include "agrisense_radio.h"
#include "pump_logic.h"

#define FW_VERSION "pump-1.1.0"
#if defined(ARDUINO_XIAO_ESP32S3)
#define PIN_PUMP 4
#define PIN_VALVE 3
#define PIN_PRESSURE 1
#define PIN_12V 2
#define PIN_BUTTON 44
#define OLED_SDA 5
#define OLED_SCL 6
#define OLED_RST -1
#else
#define PIN_PUMP 5
#define PIN_VALVE 4
#define PIN_PRESSURE 6
#define PIN_12V 7
#define PIN_BUTTON 0
#define OLED_SDA 17
#define OLED_SCL 18
#define OLED_RST 21
#define VEXT 36
#endif

// Pressure sensor: the kit's pump-node transducer is 0-1.2 MPa (1200 kPa). If you fit the 0-30 psi
// Trainer sensor instead, change this to 206.8.
const float SENSOR_FULL_KPA = 1200.0f;
const float DIVIDER = 1.5f;                 // 10k/20k: sensor volts = pin volts x 1.5
const float SENSOR_MIN_V = 0.25f;           // a working sensor never reads below ~0.5 V; lower = unplugged

Adafruit_SSD1306 screen(128, 64, &Wire, OLED_RST);
pump::Logic logic;

volatile bool rxFlag = false;
void IRAM_ATTR onRx() { rxFlag = true; }

float kpa = 0, sensorV = 0, supplyV = 0;
bool sensorOk = false, radioOk = false;
String lastCmd = "none yet", lastEvent = "-";
int lastRssi = 0;

// event sending: each event goes out twice, 2 s apart, in case the gateway was busy transmitting
const char *outPacket = nullptr; uint8_t outLeft = 0; uint32_t outAt = 0;

void setRelays() {
  digitalWrite(PIN_PUMP, logic.pumpOn() ? HIGH : LOW);
  digitalWrite(PIN_VALVE, logic.valveOpen() ? HIGH : LOW);
}

void readPressure() {
  static float avg = -1;
  uint32_t mv = 0;
  for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(PIN_PRESSURE);
  float v = mv / 8.0f / 1000.0f * DIVIDER;
  avg = avg < 0 ? v : avg * 0.6f + v * 0.4f;          // light smoothing, still reacts within ~0.2 s
  sensorV = avg;
  sensorOk = sensorV >= SENSOR_MIN_V;
  kpa = sensorOk ? max(0.0f, (sensorV - 0.5f) / 4.0f * SENSOR_FULL_KPA) : 0;
  supplyV = analogReadMilliVolts(PIN_12V) / 1000.0f * (47.0f + 10.0f) / 10.0f;
}

void sendEvent(pump::Event e) {
  if (e == pump::EV_NONE) return;
  outPacket = pump::eventPacket(e); outLeft = 2; outAt = millis();
  lastEvent = outPacket + 2;                            // "DONE", "NO_FLOW", ...
}

void serviceRadio() {
  if (!radioOk) return;
  if (rxFlag) {
    rxFlag = false;
    String p;
    if (radio.readData(p) == RADIOLIB_ERR_NONE) {
      pump::Command c;
      if (pump::parseCommand(p.c_str(), c)) {
        lastCmd = p; lastRssi = (int)radio.getRSSI();
        bool ok = logic.command(c, millis(), sensorOk);
        Serial.printf("cmd %s -> %s (%s)\n", p.c_str(), ok ? "accepted" : "refused", logic.lastReason());
        setRelays();
      }
    }
    radio.startReceive();
  }
  if (outLeft && (int32_t)(millis() - outAt) >= 0) {
    radio.transmit(outPacket);                          // ~0.2 s at SF9; the relays are already set
    radio.startReceive();
    Serial.printf("sent %s\n", outPacket);
    outLeft--; outAt = millis() + 2000 + random(0, 500);
  }
}

void serviceButton() {
  static uint32_t downAt = 0; static bool longDone = false;
  bool down = digitalRead(PIN_BUTTON) == LOW;
  uint32_t now = millis();
  if (down && !downAt) { downAt = now; longDone = false; }
  if (down && downAt && !longDone && now - downAt > 3000) {
    longDone = true;
    if (logic.state() == pump::IDLE && logic.buttonLong(now, sensorOk)) Serial.println("button: test run");
  }
  if (!down && downAt) {
    if (!longDone && now - downAt > 40) logic.buttonShort(now);   // short press = STOP
    downAt = 0;
  }
}

void draw() {
  uint32_t now = millis();
  screen.clearDisplay(); screen.setTextColor(SSD1306_WHITE); screen.setCursor(0, 0); screen.setTextSize(1);
  screen.println("AgriSense PUMP node");
  screen.setTextSize(2);
  if (logic.pumpOn()) {
    if (logic.tray() == 'T') screen.printf("TEST %lus\n", (unsigned long)logic.secondsLeft(now));
    else screen.printf("TRAY %c %lus\n", logic.tray(), (unsigned long)logic.secondsLeft(now));
  } else if (logic.pending()) screen.println("WAIT...");
  else if (logic.state() != pump::IDLE) screen.println("VALVE");
  else screen.println(sensorOk ? "READY" : "SENSOR?");
  screen.setTextSize(1);
  if (sensorOk) screen.printf("Pressure %.0f kPa\n", kpa); else screen.println("Pressure: unplugged");
  screen.printf("%s\n", logic.lastReason());
  screen.printf("Cmd %s %ddBm\n", lastCmd.c_str(), lastRssi);
  if (supplyV > 1) screen.printf("12V %.1f  Sent %s", supplyV, lastEvent.c_str());
  else screen.printf("12V --  Sent %s", lastEvent.c_str());
  if (!radioOk) { screen.setCursor(0, 56); screen.print("RADIO NOT FOUND     "); }
  screen.display();
}

void setup() {
  digitalWrite(PIN_PUMP, LOW); digitalWrite(PIN_VALVE, LOW);   // relays off before the pins become outputs
  pinMode(PIN_PUMP, OUTPUT); pinMode(PIN_VALVE, OUTPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_PRESSURE, ADC_11db);
  analogSetPinAttenuation(PIN_12V, ADC_11db);
#ifdef VEXT
  pinMode(VEXT, OUTPUT); digitalWrite(VEXT, LOW); delay(50);   // Heltec: power the built-in screen
#endif
  Wire.begin(OLED_SDA, OLED_SCL);
  screen.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  int st = radioBegin();                                       // agrisense_radio.h: same settings as the gateway
  radioOk = st == RADIOLIB_ERR_NONE;
  if (radioOk) { radio.setDio1Action(onRx); radio.startReceive(); }
  else Serial.printf("radio.begin failed: %d\n", st);
  randomSeed(esp_random());
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t wdt = {.timeout_ms = 5000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wdt);
#else
  esp_task_wdt_init(5, true);
#endif
  esp_task_wdt_add(NULL);
  Serial.println(FW_VERSION " ready");
}

void loop() {
  static uint32_t lastDraw = 0;
  esp_task_wdt_reset();
  readPressure();
  serviceRadio();
  serviceButton();
  sendEvent(logic.step(millis(), kpa, sensorOk));
  setRelays();
  if (millis() - lastDraw > 250) { lastDraw = millis(); draw(); }
  delay(10);
}
