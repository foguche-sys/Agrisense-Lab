// AgriSense Lab - pump node safety logic (plain C++, no Arduino calls, so it can be unit-tested on a PC:
// firmware/tests/test_pump_logic.cpp). The sketch feeds it the time, the pressure and the radio commands,
// and switches the two relays exactly as it says.
#pragma once
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

namespace pump {

// ---- limits (the platform checks the same ones first; this is the last line of defence) ----
const uint16_t MAX_RUN_S      = 300;    // kit maximum, whatever the command says
const uint32_t REST_MS        = 10000;  // pump rests at least 10 s between runs; a RUN that arrives sooner waits
const uint32_t VALVE_LEAD_MS  = 300;    // valve opens this long before the pump starts ...
const uint32_t VALVE_LAG_MS   = 300;    // ... and closes this long after it stops
const uint32_t FLOW_CHECK_MS  = 3000;   // after the pump starts, pressure must be up by now
const uint32_t NO_FLOW_HOLD   = 1000;   // pressure must stay low this long to call NO FLOW
const uint32_t BLOCKED_HOLD   = 500;    // pressure must stay high this long to call BLOCKED (ignores spikes)
const float    NO_FLOW_KPA    = 10.0f;  // same numbers as the Trainer (lessons 1.4, 3.6)
const float    BLOCKED_KPA    = 150.0f;
const uint32_t TEST_RUN_MS    = 5000;   // hold the lid button 3 s when idle: 5 s test / priming run

enum Event : uint8_t { EV_NONE, EV_DONE, EV_NO_FLOW, EV_BLOCKED, EV_PRESSURE_FAULT };
inline const char *eventPacket(Event e) {         // what the gateway expects ("P,..."), see gateway_bridge.ino
  switch (e) {
    case EV_DONE: return "P,DONE";
    case EV_NO_FLOW: return "P,NO_FLOW";
    case EV_BLOCKED: return "P,BLOCKED";
    case EV_PRESSURE_FAULT: return "P,PRESSURE_FAULT";
    default: return "";
  }
}

enum State : uint8_t { IDLE, VALVE_OPENING, RUNNING, VALVE_CLOSING };

// Parse a radio packet. Accepts only "STOP", "RUN,<seconds>" and "RUN,<seconds>,<tray letter A-Z>".
// Everything else (other nodes' readings, noise) returns false and is ignored.
struct Command { bool stop = false; uint16_t seconds = 0; char tray = '?'; };
inline bool parseCommand(const char *p, Command &c) {
  c = Command();
  if (!p) return false;
  if (strcmp(p, "STOP") == 0) { c.stop = true; return true; }
  if (strncmp(p, "RUN,", 4) != 0) return false;
  const char *s = p + 4;
  if (*s < '0' || *s > '9') return false;
  char *end = nullptr;
  long secs = strtol(s, &end, 10);
  if (secs < 1 || secs > 100000) return false;
  if (*end == ',') {
    char t = end[1];
    if (t < 'A' || t > 'Z' || end[2] != '\0') return false;
    c.tray = t;
  } else if (*end != '\0') return false;
  c.seconds = (uint16_t)(secs > MAX_RUN_S ? MAX_RUN_S : secs);   // clamp, never refuse a sane stop time
  return true;
}

class Logic {
 public:
  // outputs for the relays
  bool pumpOn() const { return state_ == RUNNING; }
  bool valveOpen() const { return state_ != IDLE; }
  State state() const { return state_; }
  char tray() const { return tray_; }
  bool pending() const { return pendingMs_ > 0; }
  const char *lastReason() const { return reason_; }
  uint32_t secondsLeft(uint32_t now) const {
    if (state_ != RUNNING || now >= stopAt_) return 0;
    return (stopAt_ - now + 999) / 1000;
  }

  // A radio command. Returns true if it was accepted (run started, queued, or stopped).
  bool command(const Command &c, uint32_t now, bool sensorOk) {
    if (c.stop) { pendingMs_ = 0; stop(now, "STOP from website"); return true; }
    if (state_ != IDLE) { reason_ = "busy: one tray at a time"; return false; }
    if (!sensorOk) { reason_ = "pressure sensor fault"; queueEvent(EV_PRESSURE_FAULT); return false; }
    return startOrQueue(c.seconds * 1000UL, c.tray, now, true);
  }

  // Lid button. shortPress: STOP. longPress (held 3 s) while idle: test run, not reported as DONE.
  void buttonShort(uint32_t now) { pendingMs_ = 0; if (state_ != IDLE) stop(now, "button STOP"); }
  bool buttonLong(uint32_t now, bool sensorOk) {
    if (state_ != IDLE || !sensorOk) return false;
    return startOrQueue(TEST_RUN_MS, 'T', now, false);
  }

  // Call every loop with the latest (averaged) pressure. Returns an event to send, or EV_NONE.
  Event step(uint32_t now, float kpa, bool sensorOk) {
    switch (state_) {
      case IDLE:
        if (pendingMs_ && restOver(now)) {
          if (!sensorOk) { pendingMs_ = 0; reason_ = "pressure sensor fault"; queueEvent(EV_PRESSURE_FAULT); break; }
          begin(now);
        }
        break;
      case VALVE_OPENING:
        if (now - t0_ >= VALVE_LEAD_MS) { state_ = RUNNING; pumpStart_ = now; stopAt_ = now + runMs_; lowSince_ = highSince_ = 0; }
        break;
      case RUNNING: {
        uint32_t ran = now - pumpStart_;
        if (!sensorOk) { stop(now, "pressure sensor fault"); queueEvent(EV_PRESSURE_FAULT); break; }
        if (kpa > BLOCKED_KPA) { if (!highSince_) highSince_ = now ? now : 1; } else highSince_ = 0;
        if (ran >= FLOW_CHECK_MS && kpa < NO_FLOW_KPA) { if (!lowSince_) lowSince_ = now ? now : 1; } else lowSince_ = 0;
        if (highSince_ && now - highSince_ >= BLOCKED_HOLD) { stop(now, "BLOCKED"); queueEvent(EV_BLOCKED); }
        else if (lowSince_ && now - lowSince_ >= NO_FLOW_HOLD) { stop(now, "NO FLOW"); queueEvent(EV_NO_FLOW); }
        else if ((int32_t)(now - stopAt_) >= 0) { stop(now, "time up"); if (report_) queueEvent(EV_DONE); }
        break;
      }
      case VALVE_CLOSING:
        if (now - t0_ >= VALVE_LAG_MS) state_ = IDLE;
        break;
    }
    Event e = event_; event_ = EV_NONE; return e;
  }

 private:
  bool restOver(uint32_t now) const { return !everRan_ || now - pumpOffAt_ >= REST_MS; }
  bool startOrQueue(uint32_t ms, char tray, uint32_t now, bool report) {
    if (ms > MAX_RUN_S * 1000UL) ms = MAX_RUN_S * 1000UL;
    runMs_ = ms; tray_ = tray; report_ = report; pendingMs_ = ms;
    if (restOver(now)) begin(now); else reason_ = "resting, will start soon";
    return true;
  }
  void begin(uint32_t now) { pendingMs_ = 0; state_ = VALVE_OPENING; t0_ = now; reason_ = "running"; }
  void stop(uint32_t now, const char *why) {
    if (state_ == RUNNING) { pumpOffAt_ = now; everRan_ = true; }
    if (state_ == RUNNING || state_ == VALVE_OPENING) { state_ = VALVE_CLOSING; t0_ = now; }
    reason_ = why;
  }
  void queueEvent(Event e) { if (event_ == EV_NONE || e != EV_DONE) event_ = e; }

  State state_ = IDLE;
  Event event_ = EV_NONE;
  uint32_t t0_ = 0, pumpStart_ = 0, stopAt_ = 0, runMs_ = 0, pendingMs_ = 0, pumpOffAt_ = 0, lowSince_ = 0, highSince_ = 0;
  bool everRan_ = false, report_ = true;
  char tray_ = '?';
  const char *reason_ = "ready";
};

}  // namespace pump
