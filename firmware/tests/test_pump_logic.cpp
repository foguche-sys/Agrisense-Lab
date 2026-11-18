// PC unit test for the pump node safety logic:
//   g++ -std=c++17 -I../pump_node test_pump_logic.cpp -o test_pump && ./test_pump
#include "pump_logic.h"
#include <cassert>
#include <cstdio>
#include <cstring>

using namespace pump;

// run the logic from t0 to t1 in 10 ms steps at a fixed pressure; return the last event seen
static Event runFor(Logic &L, uint32_t &t, uint32_t ms, float kpa, bool ok = true) {
  Event last = EV_NONE;
  for (uint32_t done = 0; done < ms; done += 10, t += 10) { Event e = L.step(t, kpa, ok); if (e != EV_NONE) last = e; }
  return last;
}

int main() {
  Command c;
  // ---- parsing ----
  assert(parseCommand("STOP", c) && c.stop);
  assert(parseCommand("RUN,60,B", c) && !c.stop && c.seconds == 60 && c.tray == 'B');
  assert(parseCommand("RUN,45", c) && c.seconds == 45 && c.tray == '?');
  assert(parseCommand("RUN,900,A", c) && c.seconds == MAX_RUN_S);          // clamped to 300 s
  assert(!parseCommand("RUN,0,A", c));
  assert(!parseCommand("RUN,-5,A", c));
  assert(!parseCommand("RUN,abc", c));
  assert(!parseCommand("RUN,60,b", c));                                    // tray letters are capitals
  assert(!parseCommand("RUN,60,BB", c));
  assert(!parseCommand("RUN,60x", c));
  assert(!parseCommand("R,ND-1B33,24.1,19.2,410,6.5,37,12,94,3.31", c));  // a field node's reading
  assert(!parseCommand("STOP ", c) && !parseCommand("", c) && !parseCommand(nullptr, c));
  assert(strcmp(eventPacket(EV_NO_FLOW), "P,NO_FLOW") == 0 && strcmp(eventPacket(EV_DONE), "P,DONE") == 0);

  // ---- a normal run: valve first, pump, time up, DONE, valve last ----
  {
    Logic L; uint32_t t = 1000;
    parseCommand("RUN,5,C", c);
    assert(L.command(c, t, true));
    assert(L.valveOpen() && !L.pumpOn());
    runFor(L, t, 290, 0);
    assert(!L.pumpOn());                                                   // still waiting for the valve
    runFor(L, t, 20, 0);
    assert(L.pumpOn() && L.tray() == 'C');
    Event e = runFor(L, t, 4900, 60);                                      // healthy pressure
    assert(e == EV_NONE && L.pumpOn());
    e = runFor(L, t, 200, 60);
    assert(e == EV_DONE && !L.pumpOn() && L.valveOpen());                  // pump off, valve closing
    runFor(L, t, 400, 0);
    assert(!L.valveOpen() && L.state() == IDLE);
  }
  // ---- NO FLOW: pressure never builds ----
  {
    Logic L; uint32_t t = 0; parseCommand("RUN,60,A", c); L.command(c, t, true);
    Event e = runFor(L, t, 300 + FLOW_CHECK_MS - 20, 2);
    assert(e == EV_NONE && L.pumpOn());                                    // not judged before 3 s
    e = runFor(L, t, NO_FLOW_HOLD + 100, 2);
    assert(e == EV_NO_FLOW && !L.pumpOn());
  }
  // ---- BLOCKED, and a short spike is ignored ----
  {
    Logic L; uint32_t t = 0; parseCommand("RUN,60,A", c); L.command(c, t, true);
    runFor(L, t, 2000, 60);
    assert(runFor(L, t, 300, 200) == EV_NONE && L.pumpOn());               // 0.3 s spike: keep going
    runFor(L, t, 500, 60);
    assert(runFor(L, t, 600, 200) == EV_BLOCKED && !L.pumpOn());
  }
  // ---- STOP from the website and from the button ----
  {
    Logic L; uint32_t t = 0; parseCommand("RUN,60,A", c); L.command(c, t, true);
    runFor(L, t, 1000, 60); assert(L.pumpOn());
    Command s; parseCommand("STOP", s); assert(L.command(s, t, true));
    assert(!L.pumpOn());
    assert(runFor(L, t, 500, 60) == EV_NONE && L.state() == IDLE);          // a STOP is not a DONE
    parseCommand("RUN,60,A", c); runFor(L, t, REST_MS, 0); L.command(c, t, true);
    runFor(L, t, 1000, 60); assert(L.pumpOn());
    L.buttonShort(t); assert(!L.pumpOn());
  }
  // ---- one tray at a time; rest between runs; a RUN during the rest waits and then starts ----
  {
    Logic L; uint32_t t = 0; parseCommand("RUN,2,A", c); L.command(c, t, true);
    runFor(L, t, 400, 60);
    Command c2; parseCommand("RUN,30,B", c2);
    assert(!L.command(c2, t, true) && L.tray() == 'A');                    // busy
    assert(runFor(L, t, 2100, 60) == EV_DONE);
    runFor(L, t, 400, 0);
    assert(L.command(c2, t, true) && L.pending() && !L.valveOpen());       // queued: resting
    runFor(L, t, REST_MS - 3000, 0);
    assert(!L.valveOpen());
    runFor(L, t, 3000, 0);
    assert(L.valveOpen() && L.tray() == 'B');
  }
  // ---- never more than 300 s ----
  {
    Logic L; uint32_t t = 0; parseCommand("RUN,99999,A", c); L.command(c, t, true);
    runFor(L, t, 300 + 299000, 60); assert(L.pumpOn());
    assert(runFor(L, t, 1100, 60) == EV_DONE && !L.pumpOn());
  }
  // ---- pressure sensor unplugged: refuse, and stop a running pump ----
  {
    Logic L; uint32_t t = 0; parseCommand("RUN,60,A", c);
    assert(!L.command(c, t, false) && !L.valveOpen());
    assert(L.step(t, 0, false) == EV_PRESSURE_FAULT);
    L.command(c, t, true); runFor(L, t, 1000, 60); assert(L.pumpOn());
    assert(runFor(L, t, 20, 0, false) == EV_PRESSURE_FAULT && !L.pumpOn());
  }
  // ---- button test run: 5 s, not reported as DONE, but still stops on NO FLOW ----
  {
    Logic L; uint32_t t = 0;
    assert(L.buttonLong(t, true) && L.tray() == 'T');
    assert(runFor(L, t, 6000, 60) == EV_NONE && !L.pumpOn());
    runFor(L, t, REST_MS, 0);
    L.buttonLong(t, true);
    assert(runFor(L, t, 5000, 0) == EV_NO_FLOW);
    assert(!L.buttonLong(t, false));                                       // not with the sensor unplugged
  }
  // ---- millis() wrap-around (every 49.7 days) ----
  {
    Logic L; uint32_t t = 0xFFFFFFFFu - 2000; parseCommand("RUN,5,A", c); L.command(c, t, true);
    Event e = runFor(L, t, 5000 + 300 + 100, 60);
    assert(e == EV_DONE && !L.pumpOn());
  }
  puts("pump logic: all tests passed");
  return 0;
}
