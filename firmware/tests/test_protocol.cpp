// PC unit test for the STUDENT port protocol: g++ -std=c++17 -I../AgriSenseStudent/src test_protocol.cpp && ./a.out
#include "agrisense_protocol.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <string>

static bool near(float a, float b, float tol) { return std::fabs(a - b) <= tol; }

int main() {
  AsSnapshot s; s.flags = AS_F_PROBE | AS_F_TANK | AS_F_UNLOCKED; s.moisture = 23.47f; s.soilTemp = -3.2f; s.ec = 412;
  s.ph = 6.5f; s.pressure = 88.3f; s.airTemp = 24.9f; s.humidity = 51.2f; s.lux = 40000; s.pumpLeft = 7;
  uint8_t b[AS_SNAPSHOT_LEN]; as_pack_snapshot(s, b);
  AsSnapshot r; assert(as_unpack_snapshot(b, r));
  assert(r.flags == s.flags && near(r.moisture, 23.5f, 0.051f) && near(r.soilTemp, -3.2f, 0.051f) && r.ec == 412);
  assert(near(r.ph, 6.5f, 0.01f) && near(r.pressure, 88.3f, 0.051f) && near(r.airTemp, 24.9f, 0.051f));
  assert(near(r.humidity, 51.2f, 0.051f) && r.lux == 40000 && r.pumpLeft == 7);
  b[5] ^= 1; assert(!as_unpack_snapshot(b, r));                     // checksum catches a flipped bit

  AsPumpState ok{true, true, true, true, false, 20.0f, 1000};
  uint8_t w;
  assert(as_decide_pump(ok, 10, w) == AS_OK && w == 0);
  AsPumpState t = ok; t.online = false; assert(as_decide_pump(t, 10, w) == AS_OFFLINE);
  t = ok; t.unlocked = false; assert(as_decide_pump(t, 10, w) == AS_LOCKED);
  assert(as_decide_pump(ok, 120, w) == AS_TOO_LONG);                // lesson 1.10: 120 s is refused
  assert(as_decide_pump(ok, 20, w) == AS_OK && as_decide_pump(ok, 21, w) == AS_TOO_LONG);
  t = ok; t.secondsSinceLastRun = 15; assert(as_decide_pump(t, 10, w) == AS_TOO_SOON && w == 45);   // second run within a minute
  t = ok; t.pumpOn = true; assert(as_decide_pump(t, 10, w) == AS_BUSY);
  t = ok; t.tankOk = false; assert(as_decide_pump(t, 10, w) == AS_TANK_LOW);
  t = ok; t.probeOk = false; assert(as_decide_pump(t, 10, w) == AS_NO_PROBE);
  t = ok; t.moisture = 45; assert(as_decide_pump(t, 10, w) == AS_SOIL_WET);                       // soil already wet
  assert(as_decide_pump(ok, 0, w) == AS_BAD_CMD);
  assert(std::string(as_reason(AS_TOO_LONG)).find("REFUSED") == 0);
  std::puts("protocol tests passed");
}
