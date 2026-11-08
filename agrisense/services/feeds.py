"""Feeds: every sensor reading, output state and hand-entered value is a datapoint on a feed."""
from ..db import new_id, now

TRAY_METRICS = [
    ("moisture", "Soil moisture", "%"),
    ("temp", "Soil temperature", "°C"),
    ("ec", "EC", "µS/cm"),
    ("ph", "pH", ""),
    ("n", "Nitrogen (est.)", "mg/kg"),
    ("p", "Phosphorus (est.)", "mg/kg"),
    ("k", "Potassium (est.)", "mg/kg"),
]

# Components a Trainer Board can carry in the IoT Studio, with the feed each one creates.
TRAINER_COMPONENTS = {
    "pump":     ("Relay 1 · Pump", "output", "ON/OFF", "MCP23017 pin 11 · load jacks L1"),
    "fan":      ("Relay 2 · Fan", "output", "ON/OFF", "MCP23017 pin 12 · load jacks L2"),
    "moisture": ("Soil probe", "sensor", "%", "FIELD I/O · PROBE (RS485)"),
    "air-temp": ("AIR pod (AHT20)", "sensor", "°C", "Qwiic · 0x38"),
    "humidity": ("AIR pod humidity", "sensor", "%RH", "Qwiic · 0x38"),
    "pressure": ("Pressure", "sensor", "kPa", "FIELD I/O · PRESSURE · ADS A2"),
    "tank":     ("Tank level", "sensor", "OK/LOW", "FIELD I/O · LEVEL · MCP pin 13"),
    "vent":     ("Servo (vent)", "output", "°", "PCA9685 ch 0"),
    "ledbar":   ("LED bar", "output", "0-10", "MCP23017 pins 0-9"),
    "buzzer":   ("Buzzer", "output", "ON/OFF", "MCP23017 pin 10"),
    "light":    ("LIGHT pod (BH1750)", "sensor", "lux", "Qwiic · 0x23"),
    "knob-1":   ("Knob 1", "sensor", "%", "ADS1115 A0"),
    "knob-2":   ("Knob 2", "sensor", "%", "ADS1115 A1"),
    "motor":    ("Motor (TB6612)", "output", "-100..100", "PCA ch 1 + MCP 14/15 · L3"),
    "post-a1":  ("Coding post A1", "sensor", "V", "GPIO 7 · post 12"),
    "post-d1":  ("Coding post D1", "sensor", "HIGH/LOW", "GPIO 47 · post 14"),
}
DEFAULT_TRAINER = ["pump", "fan", "moisture", "air-temp", "pressure", "tank", "vent"]
OUTPUTS = {k for k, v in TRAINER_COMPONENTS.items() if v[1] == "output"}


def kit_slug(kit_id):
    return "kit-" + kit_id.split("_")[-1][:6]


def tray_feed_key(kit_id, letter, metric):
    return f"{kit_slug(kit_id)}.tray-{letter.lower()}.{metric}"


def get_or_create(db, key, name, unit=None, kind="sensor", **owner):
    f = db.one("SELECT * FROM feeds WHERE key = ?", key)
    if f:
        return f
    fid = new_id("fd")
    db.insert("feeds", id=fid, key=key, name=name, unit=unit, kind=kind, created_at=now(),
              school_id=owner.get("school_id"), kit_id=owner.get("kit_id"), tray_id=owner.get("tray_id"),
              team_id=owner.get("team_id"), device_id=owner.get("device_id"))
    return db.one("SELECT * FROM feeds WHERE id = ?", fid)


def to_num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        if isinstance(v, str) and v.upper() in ("ON", "OK", "HIGH"):
            return 1.0
        if isinstance(v, str) and v.upper() in ("OFF", "LOW"):
            return 0.0
        return None


def write(db, feed, value, source="device", at=None, run_actions=True):
    at = at or now()
    sval = value if isinstance(value, str) else (f"{value:g}" if isinstance(value, float) else str(value))
    db.insert("datapoints", feed_id=feed["id"], value=sval, num=to_num(value), source=source, created_at=at)
    if not feed.get("last_at") or at >= feed["last_at"]:
        db.run("UPDATE feeds SET last_value = ?, last_at = ? WHERE id = ?", sval, at, feed["id"])
        feed["last_value"], feed["last_at"] = sval, at
    if run_actions:
        from .actions import evaluate
        evaluate(db, feed, sval)
    return sval


def history(db, feed_id, since=None, until=None, limit=5000):
    sql = "SELECT value, num, source, created_at FROM datapoints WHERE feed_id = ?"
    params = [feed_id]
    if since:
        sql += " AND created_at >= ?"
        params.append(since)
    if until:
        sql += " AND created_at <= ?"
        params.append(until)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.q(sql, *params)
    rows.reverse()
    return rows


def last_off_at(db, feed_id):
    return db.val("SELECT created_at FROM datapoints WHERE feed_id = ? AND value = 'OFF' ORDER BY created_at DESC LIMIT 1", feed_id)


def last_on_at(db, feed_id):
    return db.val("SELECT created_at FROM datapoints WHERE feed_id = ? AND value = 'ON' ORDER BY created_at DESC LIMIT 1", feed_id)


def ensure_team_feeds(db, team, components):
    out = []
    for c in components:
        name, kind, unit, _ = TRAINER_COMPONENTS[c]
        out.append(get_or_create(db, f"{team['slug']}.{c}", name, unit, "output" if kind == "output" else "sensor",
                                 team_id=team["id"]))
    return out


def ensure_tray_feeds(db, kit, tray):
    school_id = kit["school_id"]
    return {m: get_or_create(db, tray_feed_key(kit["id"], tray["letter"], m), f"Tray {tray['letter']} {label}", unit,
                             "sensor", school_id=school_id, kit_id=kit["id"], tray_id=tray["id"])
            for m, label, unit in TRAY_METRICS}
