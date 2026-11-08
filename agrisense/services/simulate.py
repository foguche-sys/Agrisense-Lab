"""Simulation mode: believable readings for each soil, so a class can run lessons with no hardware.

Simulated time runs `sim_speed` times faster than real time from `sim_started_at`.
Each tray starts at field capacity, dries at its soil's rate (doubled in a dry spell,
x1.5 in a heat wave) and gains water from approved simulated pump runs.
"""
import math

from ..db import parse_ts, now

SOILS = {
    #            field cap, wilting, dry %/h, EC base, pH, temp offset
    "sandy":      (21.0, 6.0, 0.55, 180.0, 6.8, 0.6),
    "loam":       (30.0, 12.0, 0.25, 420.0, 6.5, 0.0),
    "clay":       (38.0, 18.0, 0.15, 620.0, 6.9, -0.4),
    "fertilized": (30.0, 12.0, 0.25, 1480.0, 6.1, 0.0),
    "salty":      (29.0, 12.0, 0.25, 2140.0, 7.4, 0.0),
}
PUMP_PCT_PER_S = 0.10      # % moisture added per second of pumping (Activity 1.4 default)


def sim_hours(cls, at=None):
    start = parse_ts(cls.get("sim_started_at") or now())
    end = parse_ts(at or now())
    return max(0.0, (end - start).total_seconds() / 3600.0 * (cls.get("sim_speed") or 60))


def tray_reading(db, cls, tray, at=None):
    fc, wp, dry, ec0, ph, toff = SOILS.get(tray["soil"], SOILS["loam"])
    h = sim_hours(cls, at)
    event = cls.get("sim_event") or "none"
    rate = dry * (2.0 if event == "dry_spell" else 1.5 if event == "heat_wave" else 1.0)
    runs = db.q("SELECT seconds, decided_at FROM pump_requests WHERE tray_id = ? AND class_id = ? AND simulated = 1 "
                "AND status IN ('approved', 'done') AND decided_at >= ? ORDER BY decided_at",
                tray["id"], cls["id"], cls.get("sim_started_at") or now())
    m, last_h = fc, 0.0
    for r in runs:
        rh = sim_hours(cls, r["decided_at"])
        m = max(2.0, m - rate * (rh - last_h))
        m = min(fc + 2.0, m + r["seconds"] * PUMP_PCT_PER_S)
        last_h = rh
    m = max(2.0, m - rate * (h - last_h))
    hour_of_day = (h + 8) % 24
    temp = 18.5 + toff + 2.2 * math.sin((hour_of_day - 9) / 24 * 2 * math.pi) + (7.5 if event == "heat_wave" else 0)
    too_dry = m < 10.0
    ec = None if too_dry else round(ec0 * (m / fc) ** 0.35)
    n = None if too_dry else round(ec * 0.09)
    p = None if too_dry else round(ec * 0.03)
    k = None if too_dry else round(ec * 0.23)
    return {"moisture": round(m, 1), "temp": round(temp, 1), "ec": ec, "ph": ph, "n": n, "p": p, "k": k,
            "too_dry": too_dry, "simulated": True, "at": at or now(), "sim_day": int(h // 24) + 1,
            "sim_clock": f"{int(hour_of_day):02d}:{int((hour_of_day % 1) * 60):02d}"}


def series(db, cls, tray, points=48, hours=48):
    """Simulated history: `points` readings over the last `hours` of simulated time."""
    from datetime import timedelta
    end = parse_ts(now())
    speed = cls.get("sim_speed") or 60
    out = []
    for i in range(points):
        real_back = (hours - i * hours / (points - 1)) * 3600 / speed
        at = now(end - timedelta(seconds=real_back))
        out.append(tray_reading(db, cls, tray, at))
    return out
