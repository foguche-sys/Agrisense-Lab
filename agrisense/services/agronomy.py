"""Irrigation agronomy for the bench: when should this tray be watered, and for how long?

Uses the soil's field capacity (FC) and wilting point (WP) and the crop's allowed depletion (p, after FAO-56):
    refill point = FC - p x (FC - WP)
Water before moisture drops below the refill point; fill back to just under field capacity
(more than that drains away). How fast the tray dries comes from its own recent readings.
"""
from ..db import ago, now, parse_ts
from . import feeds as F
from .simulate import PUMP_PCT_PER_S, SOILS

# crop: (label, allowed depletion p, note)
CROPS = {
    "none":    ("No crop (bare soil)", 0.50, "Generic 50 % allowed depletion."),
    "lettuce": ("Lettuce", 0.30, "Shallow roots, wilts fast: water early."),
    "pepper":  ("Pepper", 0.30, "Sensitive to dry spells at flowering."),
    "tomato":  ("Tomato", 0.40, "Uneven watering causes fruit cracking."),
    "beans":   ("Beans", 0.45, "Most sensitive at flowering and pod fill."),
    "soybean": ("Soybean", 0.50, "Tolerant early, critical at pod fill."),
    "corn":    ("Corn", 0.55, "Critical at tasseling and silking."),
    "wheat":   ("Wheat", 0.55, "Deep roots once established."),
    "turf":    ("Turf / pasture grass", 0.50, "Tolerant; aim for steady moisture."),
}


def bands(tray):
    fc, wp, *_ = SOILS.get(tray["soil"], SOILS["loam"])
    p = CROPS.get(tray.get("crop") or "none", CROPS["none"])[1]
    refill = round(fc - p * (fc - wp), 1)
    return {"wp": wp, "refill": refill, "fc": fc, "target": round(fc - 1.0, 1), "p": p,
            "crop": CROPS.get(tray.get("crop") or "none", CROPS["none"])[0]}


def drying_rate(db, cls, tray, hours=6):
    """% moisture lost per hour (positive), from the last `hours` of readings; None if unknown."""
    if cls and cls["sim_enabled"]:
        rate = SOILS.get(tray["soil"], SOILS["loam"])[2]
        ev = cls.get("sim_event") or "none"
        return rate * (2.0 if ev == "dry_spell" else 1.5 if ev == "heat_wave" else 1.0)
    kit = db.one("SELECT * FROM kits WHERE id = ?", tray["kit_id"])
    f = db.one("SELECT id FROM feeds WHERE key = ?", F.tray_feed_key(kit["id"], tray["letter"], "moisture"))
    if not f:
        return None
    pts = [p for p in F.history(db, f["id"], since=ago(hours=hours), limit=500) if p["num"] is not None]
    # use only the last stretch since the most recent rise (a watering resets the curve)
    for i in range(len(pts) - 1, 0, -1):
        if pts[i]["num"] - pts[i - 1]["num"] > 1.0:
            pts = pts[i:]
            break
    if len(pts) < 4:
        return None
    t0 = parse_ts(pts[0]["created_at"]).timestamp()
    xs = [(parse_ts(p["created_at"]).timestamp() - t0) / 3600 for p in pts]
    ys = [p["num"] for p in pts]
    n, mx, my = len(xs), sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den < 0.25:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return round(max(0.0, -slope), 3)


def pump_rate(db, tray):
    """% moisture gained per pump second for this tray, learned from checked runs; else the bench default."""
    rows = db.q("SELECT seconds, moisture_before, moisture_after FROM pump_requests WHERE tray_id = ? AND moisture_after IS NOT NULL "
                "AND moisture_before IS NOT NULL AND seconds > 0 ORDER BY created_at DESC LIMIT 5", tray["id"])
    rates = [(r["moisture_after"] - r["moisture_before"]) / r["seconds"] for r in rows if r["moisture_after"] > r["moisture_before"]]
    if rates:
        return round(sum(rates) / len(rates), 3), True
    return PUMP_PCT_PER_S, False


def advise(db, cls, tray, moisture, limit=300):
    """Status, hours until the refill point, and the pump seconds to get back to the target."""
    if moisture is None:
        return None
    b = bands(tray)
    rate = drying_rate(db, cls, tray)
    per_s, learned = pump_rate(db, tray)
    if moisture < b["wp"]:
        status, tone, text = "wilting", "bad", "Below wilting point: plants are stressed. Water now."
    elif moisture <= b["refill"]:
        status, tone, text = "water", "warn", "At or below the refill point: water now."
    elif moisture > b["fc"] + 1:
        status, tone, text = "wet", "info", "Wetter than field capacity: extra water will drain. Don't water."
    else:
        status, tone, text = "ok", "ok", "In the healthy range."
    hours = None
    if status == "ok" and rate and rate > 0.01:
        hours = round((moisture - b["refill"]) / rate, 1)
        text = f"About {hours:g} h until the refill point." if hours < 72 else "More than 3 days until the refill point."
    seconds = None
    if status in ("water", "wilting", "ok") and moisture < b["target"]:
        seconds = int(min(limit, max(1, round((b["target"] - moisture) / per_s))))
    return {**b, "status": status, "tone": tone, "text": text, "hours": hours, "rate": rate,
            "seconds": seconds, "per_s": per_s, "learned": learned, "moisture": moisture}


def check_runs(db, cls, tray):
    """Fill in 'moisture_after' for finished runs (the 'check' in predict -> act -> check)."""
    from .simulate import tray_reading
    rows = db.q("SELECT * FROM pump_requests WHERE tray_id = ? AND class_id = ? AND status IN ('approved', 'done') "
                "AND moisture_after IS NULL", tray["id"], cls["id"])
    for r in rows:
        if not r["decided_at"]:
            continue
        done = parse_ts(r["decided_at"]).timestamp() + r["seconds"]
        if r["simulated"]:
            soak = 60                       # simulated runs: check one real minute after the run
            if parse_ts(now()).timestamp() < done + soak:
                continue
            from datetime import datetime, timezone
            at = now(datetime.fromtimestamp(done + soak, timezone.utc))
            after = tray_reading(db, cls, tray, at)["moisture"]
        else:
            soak = 600                      # real soil: let water soak in for 10 minutes
            if parse_ts(now()).timestamp() < done + soak:
                continue
            from datetime import datetime, timezone
            since = now(datetime.fromtimestamp(done + soak, timezone.utc))
            kit = db.one("SELECT * FROM kits WHERE id = ?", tray["kit_id"])
            f = db.one("SELECT id FROM feeds WHERE key = ?", F.tray_feed_key(kit["id"], tray["letter"], "moisture"))
            p = db.one("SELECT num FROM datapoints WHERE feed_id = ? AND created_at >= ? AND num IS NOT NULL ORDER BY created_at LIMIT 1",
                       f["id"], since) if f else None
            if not p:
                continue
            after = p["num"]
        db.run("UPDATE pump_requests SET moisture_after = ?, checked_at = ? WHERE id = ?", round(after, 1), now(), r["id"])


def decision_log(db, cls, tray, limit=8):
    check_runs(db, cls, tray)
    rows = db.q("SELECT p.*, u.name AS who FROM pump_requests p JOIN users u ON u.id = p.requested_by WHERE p.tray_id = ? AND p.class_id = ? "
                "ORDER BY p.created_at DESC LIMIT ?", tray["id"], cls["id"], limit)
    for r in rows:
        r["error"] = round(r["moisture_after"] - r["prediction"], 1) if r["moisture_after"] is not None and r["prediction"] is not None else None
        r["gain"] = round(r["moisture_after"] - r["moisture_before"], 1) if r["moisture_after"] is not None and r["moisture_before"] is not None else None
    return rows
