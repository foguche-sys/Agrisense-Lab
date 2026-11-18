# STUDENT port and node E firmware (Nov 2026)

## What runs where
| Board | Sketch | What it does |
| --- | --- | --- |
| Trainer (XIAO ESP32S3 Radio Board, 2026; or Heltec V3) | `firmware/trainer_studio` (v1.4.0) | Trainer outputs and sensors (v1.3 adds the knobs and the motor for Lab 3); **STUDENT port** I2C target at 0x42 on D0/D1 (XIAO) or GPIO 38/39 (Heltec); v1.4 adds a status screen and the XIAO pins |
| Student Arduino UNO R4 WiFi | `firmware/AgriSenseStudent` library + examples | Reads the Trainer, asks for pump runs (lesson 1.10) |
| Build deck, node E, and field nodes A-D (XIAO Radio Board or Heltec V3) | `firmware/build_deck_node` (v1.1.0) | Soil probe + pods on its screen; sends to the website over **Wi-Fi** (Starter) or LoRa to the gateway (Field add-on) |

## Safety: who decides
Student code only asks. The Trainer answers with `as_decide_pump()` (`agrisense_protocol.h`), tested on a PC in
`firmware/tests/test_protocol.cpp`. It refuses unless all of these hold:
the website says the teacher has unlocked the class controls (Teach → Unlock controls), the Trainer is online,
the run is 1–20 s, the pump has rested 60 s, the tank is OK, the probe answers and the soil is below 40 %.
The Trainer's own limits (30 s, NO FLOW, BLOCKED, tank) still apply to every run. Each answer is logged on the website
(audit log: `student.pump`, `student.refused`).

## Flashing (teacher or AgriSense staff)
1. **Trainer:** Arduino IDE → board "XIAO_ESP32S3" (2026 kits) or "Heltec WiFi LoRa 32(V3)" (first kits), ESP32 core 3.x. The sketch picks the pins itself. Libraries: Adafruit ADS1X15,
   Adafruit MCP23017, Adafruit PWM Servo Driver, Adafruit AHTX0, ArduinoJson 7. Copy `secrets.h.example` to
   `secrets.h`, fill in Wi-Fi and the device key, upload. Serial Monitor (115200) shows `STUDENT pump 10 s -> OK` when a student asks.
2. **Node E:** same board. Libraries: Adafruit AHTX0, Adafruit SSD1306, Adafruit GFX, ArduinoJson 7 (RadioLib for LoRa mode).
   Fill `secrets.h` with the deck's own device key. The screen shows moisture, pods and "sent" once a minute (press the button to send now: D1 button or the XIAO's BOOT key; PRG on a Heltec).
   With the Field add-on you may switch `SEND_MODE` to `SEND_LORA`; leave it on Wi-Fi otherwise.
3. **Student Arduino:** import `AgriSenseStudent.zip` (website, signed in as a teacher: Lessons page > Student Arduino library, `/downloads/AgriSenseStudent.zip`) into the Arduino
   Cloud Editor once, then open Examples → AgriSenseStudent → ReadSoil.

## Fix in this release
The Trainer sketch called `Wire.begin()` with the Heltec V3's default pins (SDA 41, which is also the RS485 DE pin).
v1.2.0 starts the module bus on the wired pins: `Wire.begin(5, 6)`.

## Still to check on the bench
These sketches have not been compiled or run on hardware yet. On the first build: compile each sketch, then check
ReadSoil prints the same moisture as the website, AskForWater gets OK when unlocked and REFUSED (too long) at 120 s,
and node E appears on Our tray.
