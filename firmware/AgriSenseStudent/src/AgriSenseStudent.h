/*
  AgriSenseStudent: the student's Arduino UNO R4 WiFi talks to the AgriSense Trainer.
  Plug a Qwiic cable from the UNO R4's Qwiic connector to the Trainer's STUDENT socket.

    #include <AgriSenseStudent.h>
    AgriSenseStudent trainer;
    void setup() { Serial.begin(115200); trainer.begin(); }
    void loop() {
      if (trainer.update()) Serial.println(trainer.moisture());
      delay(2000);
    }
*/
#pragma once
#include <Arduino.h>
#include <Wire.h>
#include "agrisense_protocol.h"

class AgriSenseStudent {
 public:
  // The UNO R4 WiFi's Qwiic connector is Wire1.
  bool begin(TwoWire &bus = Wire1);
  bool update();                       // read a fresh snapshot; false if the Trainer did not answer
  bool connected() const { return _ok; }

  float moisture() const { return _s.moisture; }      // soil moisture, %
  float soilTemp() const { return _s.soilTemp; }      // soil temperature, °C
  float ec() const { return _s.ec; }                  // electrical conductivity, µS/cm
  float ph() const { return _s.ph; }
  float pressure() const { return _s.pressure; }      // pump pressure, kPa
  float airTemp() const { return _s.airTemp; }        // AIR pod, °C
  float humidity() const { return _s.humidity; }      // AIR pod, %
  float light() const { return _s.lux; }              // LIGHT pod, lux
  bool probeOk() const { return _s.flags & AS_F_PROBE; }
  bool tankOk() const { return _s.flags & AS_F_TANK; }
  bool pumpOn() const { return _s.flags & AS_F_PUMP; }
  bool unlocked() const { return _s.flags & AS_F_UNLOCKED; }
  bool hasAir() const { return _s.flags & AS_F_AIR; }
  bool hasLight() const { return _s.flags & AS_F_LIGHT; }

  // Ask for a pump run. Returns AS_OK or a REFUSED code; reason(code) gives the words.
  uint8_t askForWater(int seconds);
  uint8_t waitSeconds() const { return _wait; }       // after AS_TOO_SOON: how long to wait
  uint8_t stopPump();
  uint8_t beep(float seconds = 0.2);
  uint8_t ledBar(int segments);                       // 0..10 on Outputs A
  static const char *reason(uint8_t code) { return as_reason(code); }

 private:
  uint8_t command(uint8_t cmd, uint8_t arg, bool withArg, uint32_t timeoutMs);
  TwoWire *_bus = nullptr;
  AsSnapshot _s;
  bool _ok = false;
  uint8_t _wait = 0;
};
