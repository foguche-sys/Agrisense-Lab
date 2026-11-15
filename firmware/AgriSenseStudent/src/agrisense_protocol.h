/*
  AgriSense STUDENT port protocol (v1), shared by the Trainer firmware (I2C target) and the
  AgriSenseStudent library (UNO R4 WiFi, I2C controller). Plain C++: no Arduino calls, so it is
  unit-tested on a PC (firmware/tests/test_protocol.cpp).

  Wiring: STUDENT Qwiic socket -> Trainer Heltec 2nd I2C bus: SDA GPIO 38, SCL GPIO 39, GND.
  The socket's 3.3 V pad is NOT connected. Trainer address 0x42, 100 kHz.

  The student board writes one command, waits, then reads the reply:
    CMD_SNAPSHOT  (0x01)           -> 20-byte snapshot (see as_pack_snapshot)
    CMD_PUMP      (0x10, seconds)  -> 2-byte reply [result, wait_s]; read until result != AS_PENDING
    CMD_STOP      (0x11)           -> 2-byte reply [AS_OK, 0]
    CMD_BEEP      (0x20, tenths)   -> 2-byte reply (buzzer, max 1 s)
    CMD_LEDBAR    (0x21, 0..10)    -> 2-byte reply (LED bar on Outputs A)
  The Trainer decides every pump request itself (as_decide_pump). Student code can never switch
  the pump directly, and the Trainer's own limits (tank, NO FLOW, BLOCKED, 30 s) stay on.
*/
#pragma once
#include <stdint.h>
#include <string.h>

#define AS_I2C_ADDR 0x42
#define AS_PROTO_VERSION 1

enum : uint8_t { AS_CMD_SNAPSHOT = 0x01, AS_CMD_PUMP = 0x10, AS_CMD_STOP = 0x11, AS_CMD_BEEP = 0x20, AS_CMD_LEDBAR = 0x21 };

enum : uint8_t {
  AS_OK = 1, AS_PENDING = 0xFF,
  AS_LOCKED = 10,     // teacher has not unlocked the controls (website: Teach -> Unlock controls)
  AS_TOO_LONG = 11,   // more than AS_STUDENT_MAX_S seconds
  AS_TOO_SOON = 12,   // pump is resting after the last run
  AS_TANK_LOW = 13,   // no water in the water station
  AS_SOIL_WET = 14,   // soil already wet
  AS_NO_PROBE = 15,   // no soil reading
  AS_BUSY = 16,       // pump already running
  AS_BAD_CMD = 17,    // unknown command or bad value
  AS_OFFLINE = 18     // Trainer has no Wi-Fi, so it cannot check the teacher's unlock
};

#define AS_STUDENT_MAX_S 20       // longest run student code may ask for
#define AS_REST_S 60              // rest between runs (same as the Trainer's pump rest)
#define AS_WET_LIMIT 40.0f        // % moisture: at or above this the soil counts as wet

#define AS_SNAPSHOT_LEN 20
enum : uint8_t { AS_F_PROBE = 1, AS_F_TANK = 2, AS_F_PUMP = 4, AS_F_UNLOCKED = 8, AS_F_AIR = 16, AS_F_LIGHT = 32, AS_F_ONLINE = 64 };

struct AsSnapshot {
  uint8_t flags = 0;
  float moisture = 0, soilTemp = 0, ec = 0, ph = 0, pressure = 0, airTemp = 0, humidity = 0, lux = 0;
  uint8_t pumpLeft = 0;     // seconds left in the current run
};

inline void as_put16(uint8_t *b, int v) { uint16_t u = (uint16_t)v; b[0] = u >> 8; b[1] = u & 0xFF; }
inline int16_t as_get16s(const uint8_t *b) { return (int16_t)((b[0] << 8) | b[1]); }
inline uint16_t as_get16u(const uint8_t *b) { return (uint16_t)((b[0] << 8) | b[1]); }
inline int as_clamp(float v, int lo, int hi) { int i = (int)(v >= 0 ? v + 0.5f : v - 0.5f); return i < lo ? lo : i > hi ? hi : i; }

inline void as_pack_snapshot(const AsSnapshot &s, uint8_t out[AS_SNAPSHOT_LEN]) {
  out[0] = AS_PROTO_VERSION; out[1] = s.flags;
  as_put16(out + 2, as_clamp(s.moisture * 10, 0, 1000));
  as_put16(out + 4, as_clamp(s.soilTemp * 10, -400, 800));
  as_put16(out + 6, as_clamp(s.ec, 0, 20000));
  as_put16(out + 8, as_clamp(s.ph * 10, 0, 140));
  as_put16(out + 10, as_clamp(s.pressure * 10, 0, 6000));
  as_put16(out + 12, as_clamp(s.airTemp * 10, -400, 850));
  as_put16(out + 14, as_clamp(s.humidity * 10, 0, 1000));
  as_put16(out + 16, as_clamp(s.lux, 0, 65535));
  out[18] = s.pumpLeft;
  uint8_t x = 0; for (int i = 0; i < 19; i++) x ^= out[i]; out[19] = x;
}

inline bool as_unpack_snapshot(const uint8_t in[AS_SNAPSHOT_LEN], AsSnapshot &s) {
  uint8_t x = 0; for (int i = 0; i < 19; i++) x ^= in[i];
  if (in[0] != AS_PROTO_VERSION || x != in[19]) return false;
  s.flags = in[1];
  s.moisture = as_get16u(in + 2) / 10.0f; s.soilTemp = as_get16s(in + 4) / 10.0f; s.ec = as_get16u(in + 6);
  s.ph = as_get16u(in + 8) / 10.0f; s.pressure = as_get16u(in + 10) / 10.0f; s.airTemp = as_get16s(in + 12) / 10.0f;
  s.humidity = as_get16u(in + 14) / 10.0f; s.lux = as_get16u(in + 16); s.pumpLeft = in[18];
  return true;
}

// Everything the Trainer knows when a request arrives.
struct AsPumpState {
  bool online, unlocked, tankOk, probeOk, pumpOn;
  float moisture;
  uint32_t secondsSinceLastRun;   // a large number if the pump has not run yet
};

// The Trainer's decision on "please run the pump for `seconds`". Returns a result code;
// wait_s gets how long to wait before asking again (for AS_TOO_SOON), else 0.
inline uint8_t as_decide_pump(const AsPumpState &st, int seconds, uint8_t &wait_s) {
  wait_s = 0;
  if (seconds < 1) return AS_BAD_CMD;
  if (!st.online) return AS_OFFLINE;
  if (!st.unlocked) return AS_LOCKED;
  if (seconds > AS_STUDENT_MAX_S) return AS_TOO_LONG;
  if (st.pumpOn) return AS_BUSY;
  if (st.secondsSinceLastRun < AS_REST_S) { wait_s = (uint8_t)(AS_REST_S - st.secondsSinceLastRun); return AS_TOO_SOON; }
  if (!st.tankOk) return AS_TANK_LOW;
  if (!st.probeOk) return AS_NO_PROBE;
  if (st.moisture >= AS_WET_LIMIT) return AS_SOIL_WET;
  return AS_OK;
}

inline const char *as_reason(uint8_t code) {
  switch (code) {
    case AS_OK: return "OK";
    case AS_PENDING: return "waiting for the Trainer";
    case AS_LOCKED: return "REFUSED: your teacher has not unlocked the controls";
    case AS_TOO_LONG: return "REFUSED: too long (20 s is the most student code may ask for)";
    case AS_TOO_SOON: return "REFUSED: the pump is resting after the last run";
    case AS_TANK_LOW: return "REFUSED: the water tank is low";
    case AS_SOIL_WET: return "REFUSED: the soil is already wet";
    case AS_NO_PROBE: return "REFUSED: no soil reading (is the probe plugged in?)";
    case AS_BUSY: return "REFUSED: the pump is already running";
    case AS_BAD_CMD: return "REFUSED: that request doesn't make sense";
    case AS_OFFLINE: return "REFUSED: the Trainer is offline, so it can't check your teacher's unlock";
    default: return "no answer from the Trainer (check the STUDENT cable)";
  }
}
