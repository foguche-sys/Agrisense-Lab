#include "AgriSenseStudent.h"

bool AgriSenseStudent::begin(TwoWire &bus) {
  _bus = &bus;
  _bus->begin();
  _bus->setClock(100000);
  delay(50);
  return update();
}

bool AgriSenseStudent::update() {
  if (!_bus) return false;
  _bus->beginTransmission(AS_I2C_ADDR);
  _bus->write(AS_CMD_SNAPSHOT);
  if (_bus->endTransmission() != 0) { _ok = false; return false; }
  delay(5);
  uint8_t buf[AS_SNAPSHOT_LEN];
  if (_bus->requestFrom((uint8_t)AS_I2C_ADDR, (uint8_t)AS_SNAPSHOT_LEN) != AS_SNAPSHOT_LEN) { _ok = false; return false; }
  for (int i = 0; i < AS_SNAPSHOT_LEN; i++) buf[i] = _bus->read();
  AsSnapshot s;
  _ok = as_unpack_snapshot(buf, s);
  if (_ok) _s = s;
  return _ok;
}

uint8_t AgriSenseStudent::command(uint8_t cmd, uint8_t arg, bool withArg, uint32_t timeoutMs) {
  if (!_bus) return 0;
  _bus->beginTransmission(AS_I2C_ADDR);
  _bus->write(cmd);
  if (withArg) _bus->write(arg);
  if (_bus->endTransmission() != 0) return 0;
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {                 // the Trainer answers PENDING until it has decided
    delay(20);
    if (_bus->requestFrom((uint8_t)AS_I2C_ADDR, (uint8_t)2) != 2) continue;
    uint8_t res = _bus->read(), wait = _bus->read();
    if (res != AS_PENDING) { _wait = wait; return res; }
  }
  return 0;                                           // no answer: reason(0) explains
}

uint8_t AgriSenseStudent::askForWater(int seconds) {
  if (seconds < 1 || seconds > 255) return AS_BAD_CMD;
  return command(AS_CMD_PUMP, (uint8_t)seconds, true, 1500);
}
uint8_t AgriSenseStudent::stopPump() { return command(AS_CMD_STOP, 0, false, 1000); }
uint8_t AgriSenseStudent::beep(float seconds) { return command(AS_CMD_BEEP, (uint8_t)constrain((int)(seconds * 10), 1, 10), true, 1000); }
uint8_t AgriSenseStudent::ledBar(int segments) { return command(AS_CMD_LEDBAR, (uint8_t)constrain(segments, 0, 10), true, 1000); }
