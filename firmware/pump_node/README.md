# Pump node (Field add-on)

The pump node waters one tray at a time when the teacher approves a run on the website. The gateway picks up the command and sends it to the pump node by LoRa. The pump node runs the pump, watches the pressure, and reports what happened.

It has no Wi-Fi and no keys, so there is no `secrets.h` to fill in.

## What it does on its own (even if the website or the radio misbehaves)

| Rule | Value |
|---|---|
| Longest run | 300 s, whatever the command says |
| Runs at a time | one; a second RUN while running is ignored |
| Rest between runs | 10 s; a RUN that arrives sooner waits, then starts |
| NO FLOW stop | pressure under 10 kPa for 1 s, checked from 3 s after the start |
| BLOCKED stop | pressure over 150 kPa for 0.5 s |
| Pressure sensor unplugged | will not start; stops if already running |
| Program hangs | watchdog restarts the board within 5 s; relays are off at start-up |
| Valve | opens 0.3 s before the pump, closes 0.3 s after |

Lid button: **press** = STOP. **Hold 3 s** while idle = a 5 s test run, to prime the line. A test run is not reported to the website.

## Upload it (first time)

1. Install the Arduino IDE 2 from arduino.cc.
2. **File > Preferences > Additional boards manager URLs**: paste
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json` and click **OK**.
3. **Tools > Board > Boards Manager**: search **esp32**, install **esp32 by Espressif Systems** (3.0.x).
4. **Tools > Manage Libraries**: install **RadioLib**, **Adafruit SSD1306** (click **Install all** so Adafruit GFX and BusIO come too).
5. Open `pump_node.ino`. `pump_logic.h` opens as a second tab; that is correct.
6. **Tools > Board > esp32 > Heltec WiFi LoRa 32(V3)**, plug the Heltec in by USB-C, and pick its port under **Tools > Port**.
7. Click **Upload** (the arrow). It's working when the bottom says **Hard resetting via RTS pin** and the screen shows **AgriSense PUMP node / READY**.

If the screen says **SENSOR?**, the pressure sensor is not plugged into the 2 mm jacks (5 V, SIG, GND). The pump will not run until it is.

## Check it on the bench (before connecting the pump)

1. Leave the PUMP and VALVE jacks empty and plug the pressure sensor in. The screen shows **READY** and about **0 kPa**.
2. Hold the lid button 3 s. You hear both relays click (valve first, then pump). The screen shows **TEST 5s** counting down.
3. With no water, the pressure stays near 0, so after about 4 s it stops on its own and shows **NO FLOW**. **This is the safety stop working.**
4. Approve a short run (5 s) on the website. Within a few seconds the screen shows **TRAY A 5s** (or your tray letter) and the gateway's serial monitor prints `-> pump RUN,5,A`.

## Settings you might change (top of `pump_node.ino`)

- `SENSOR_FULL_KPA`: 1200 for the kit's 0–1.2 MPa sensor. Use 206.8 if you fit the 0–30 psi Trainer sensor.
- The limits are in `pump_logic.h`. The PC test (`firmware/tests/test_pump_logic.cpp`) checks every rule; run it after any change:
  `g++ -std=c++17 -I../pump_node test_pump_logic.cpp -o test_pump && ./test_pump`
