# AgriSenseStudent (Arduino library)

Lets the student's **Arduino UNO R4 WiFi** talk to the AgriSense Trainer through the **STUDENT** Qwiic socket.
Used in lesson 1.10 "Code it yourself".

## Install (teacher, once per school Arduino account)
1. Download `AgriSenseStudent.zip` from the website (lesson 1.10, "Download the examples").
2. Arduino Cloud Editor: **Libraries** (left bar) → **Import** → choose the zip. In the desktop Arduino IDE: **Sketch → Include Library → Add .ZIP Library**.
3. Open **Examples → AgriSenseStudent → ReadSoil**, choose the board **Arduino UNO R4 WiFi**, press **Upload**.
4. Open the **Serial Monitor** at 115200. You should see `Moisture 23.4 %  Soil temp 19.2 C ...` every 2 seconds.

## Examples
| Example | What it does |
| --- | --- |
| ReadSoil | Prints moisture, soil temperature, EC and pH every 2 s |
| LedFace | Happy face on the LED grid when the soil is fine, sad face when it is below the refill point |
| AskForWater | Asks the Trainer for water when the soil is dry and prints the answer (OK or REFUSED + reason) |

## What the Trainer allows
Student code can only **ask**. The Trainer decides, and refuses when:
the teacher has not unlocked the controls, the run is longer than 20 s, the pump ran less than 60 s ago,
the tank is low, there is no probe reading, the soil is already wet (40 % or more), or the Trainer is offline.
Its own pump limits (30 s, NO FLOW, BLOCKED, tank) always stay on.

## Wiring
Qwiic cable (200 mm, JST-SH 4-pin) from the UNO R4's Qwiic connector to the Trainer's STUDENT socket.
Inside the Trainer: SDA → Heltec GPIO 38, SCL → GPIO 39, GND → GND; the socket's 3.3 V pad is not connected.
I2C address 0x42, 100 kHz. Protocol: `src/agrisense_protocol.h`.
