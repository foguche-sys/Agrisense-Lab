"""Device API: gateways, Trainer Boards and the pump node post here; they collect queued commands back.

Every device has a key (flashed in secrets.h). The platform only keeps its SHA-256 hash.
"""
from ..auth import hash_key
from ..db import jload, new_id, now, parse_ts
from . import feeds as F

ALERT_TEXT = {
    "too_dry": "Tray {t}: too dry to read EC/NPK (below 10 %). Water before the next reading.",
    "sensor_fault": "Tray {t}: the probe did not answer. Check the GX plug and the probe cable.",
    "no_flow": "Pump stopped: NO FLOW. Check the tank and the intake tube.",
    "blocked": "Pump stopped: BLOCKED. A tube is kinked or an emitter is clogged.",
    "tank_low": "Tank level LOW. Refill the reservoir.",
    "high_ec": "Tray {t}: EC above 2000 µS/cm (salty).",
}


class DeviceError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def device_for_key(db, key):
    if not key:
        raise DeviceError("Missing X-Device-Key header.", 401)
    d = db.one("SELECT * FROM devices WHERE key_hash = ?", hash_key(key))
    if not d or d["status"] == "retired":
        raise DeviceError("Unknown or retired device key.", 401)
    if not d["school_id"]:
        raise DeviceError("This device has not been claimed by a school yet.", 403)
    return d


def touch(db, dev, **status):
    cols = {"last_seen": now(), "status": "online"}
    for k in ("rssi", "supply_v", "firmware"):
        if status.get(k) is not None:
            cols[k] = status[k]
    db.update("devices", dev["id"], **cols)


def _alert(db, kind, dev, tray_letter=None, class_id=None):
    recent = db.one("SELECT id FROM alerts WHERE device_id = ? AND kind = ? AND resolved_at IS NULL", dev["id"], kind)
    if recent:
        return
    db.insert("alerts", id=new_id("al"), school_id=dev["school_id"], class_id=class_id, device_id=dev["id"], kind=kind,
              message=ALERT_TEXT.get(kind, kind).format(t=tray_letter or "?"), created_at=now())


def _resolve(db, kind, dev):
    db.run("UPDATE alerts SET resolved_at = ? WHERE device_id = ? AND kind = ? AND resolved_at IS NULL", now(), dev["id"], kind)


def node_reading(db, node, r):
    """One probe reading for the tray this node is assigned to."""
    touch(db, node, rssi=r.get("rssi"), supply_v=r.get("supply_v"), firmware=r.get("firmware"))
    if not node["tray_id"]:
        return 0
    tray = db.one("SELECT * FROM trays WHERE id = ?", node["tray_id"])
    kit = db.one("SELECT * FROM kits WHERE id = ?", tray["kit_id"])
    feeds = F.ensure_tray_feeds(db, kit, tray)
    if r.get("fault"):
        _alert(db, "sensor_fault", node, tray["letter"])
        return 0
    _resolve(db, "sensor_fault", node)
    at = r.get("at") or now()
    n = 0
    m = r.get("moisture")
    too_dry = m is not None and float(m) < 10
    for metric, _, _ in F.TRAY_METRICS:
        v = r.get(metric)
        if v is None:
            continue
        if too_dry and metric in ("ec", "n", "p", "k"):
            continue              # the probe can't read these in dry soil; don't store nonsense
        F.write(db, feeds[metric], float(v), source="device", at=at)
        n += 1
    if too_dry:
        _alert(db, "too_dry", node, tray["letter"])
    else:
        _resolve(db, "too_dry", node)
    if r.get("ec") is not None and not too_dry and float(r["ec"]) > 2000:
        _alert(db, "high_ec", node, tray["letter"])
    return n


def handle(db, dev, body):
    """POST /api/v1/ingest. Returns the response dict (including queued commands)."""
    stored = 0
    touch(db, dev, rssi=body.get("rssi"), supply_v=body.get("supply_v"), firmware=body.get("firmware"))
    if dev["kind"] == "gateway":
        for r in body.get("readings", []):
            node = db.one("SELECT * FROM devices WHERE serial = ? AND school_id = ?", r.get("node"), dev["school_id"])
            if node:
                stored += node_reading(db, node, r)
    elif dev["kind"] in ("node", "deck"):
        stored += node_reading(db, dev, body)
    elif dev["kind"] == "pump":
        ev = (body.get("event") or "").lower()
        if ev in ("no_flow", "blocked", "tank_low"):
            _alert(db, ev, dev)
            db.run("UPDATE pump_requests SET status = 'stopped' WHERE status = 'approved' AND class_id IN "
                   "(SELECT id FROM classes WHERE kit_id = ?)", dev["kit_id"])
        if ev == "done":
            db.run("UPDATE pump_requests SET status = 'done' WHERE status = 'approved' AND class_id IN "
                   "(SELECT id FROM classes WHERE kit_id = ?)", dev["kit_id"])
        if body.get("tank") == "OK":
            _resolve(db, "tank_low", dev)
    elif dev["kind"] == "trainer":
        team = db.one("SELECT * FROM teams WHERE id = ?", dev["team_id"]) if dev["team_id"] else None
        if team:
            for comp, v in (body.get("feeds") or {}).items():
                if comp not in F.TRAINER_COMPONENTS or v is None:
                    continue
                name, kind, unit, _ = F.TRAINER_COMPONENTS[comp]
                feed = F.get_or_create(db, f"{team['slug']}.{comp}", name, unit, kind if kind == "output" else "sensor",
                                       team_id=team["id"], device_id=dev["id"])
                F.write(db, feed, v, source="device")
                stored += 1
            ev = (body.get("event") or "").lower()
            if ev in ("no_flow", "blocked", "tank_low"):
                cls_id = db.val("SELECT class_id FROM teams WHERE id = ?", team["id"])
                _alert(db, ev, dev, class_id=cls_id)
            student_event(db, dev, team, body.get("student_event"))
    out = {"ok": True, "stored": stored, "server_time": now(), "commands": take_commands(db, dev)}
    if dev["kind"] == "trainer":
        out["student"] = student_status(db, dev)
    return out


STUDENT_REASONS = {10: "controls locked", 11: "too long", 12: "pump resting", 13: "tank low", 14: "soil already wet",
                   15: "no probe reading", 16: "pump already running", 17: "bad request", 18: "Trainer offline"}


def student_status(db, dev):
    """What the Trainer needs for its STUDENT port: seconds left on the teacher's unlock (0 = locked)."""
    cls = db.one("SELECT c.* FROM classes c JOIN teams t ON t.class_id = c.id WHERE t.id = ?", dev["team_id"]) if dev["team_id"] else None
    left = 0
    if cls and cls["controls_unlocked_until"] and cls["controls_unlocked_until"] > now():
        left = int(parse_ts(cls["controls_unlocked_until"]).timestamp() - parse_ts(now()).timestamp())
    return {"unlocked_s": max(0, left)}


def student_event(db, dev, team, ev):
    """The student's UNO R4 asked the Trainer for water: 'pump_ok:10' or 'refused:12'. Logged for the teacher."""
    if not ev or not isinstance(ev, str):
        return
    from .audit import log
    kind, _, val = ev.partition(":")
    if kind == "pump_ok" and val.isdigit():
        feed = F.get_or_create(db, f"{team['slug']}.pump", F.TRAINER_COMPONENTS["pump"][0], F.TRAINER_COMPONENTS["pump"][2], "output",
                               team_id=team["id"], device_id=dev["id"])
        F.write(db, feed, "ON", source="student-arduino", run_actions=False)
        log(db, "student.pump", f"{team['name']}: student Arduino ran the pump for {int(val)} s", school_id=dev["school_id"])
    elif kind == "refused" and val.isdigit():
        log(db, "student.refused", f"{team['name']}: Trainer refused the student Arduino ({STUDENT_REASONS.get(int(val), val)})",
            school_id=dev["school_id"])


def take_commands(db, dev):
    rows = db.q("SELECT id, command FROM commands WHERE device_id = ? AND delivered_at IS NULL AND expires_at > ? ORDER BY id",
                dev["id"], now())
    for r in rows:
        db.run("UPDATE commands SET delivered_at = ? WHERE id = ?", now(), r["id"])
    return [r["command"] for r in rows]


def trainer_config(dev):
    cfg = jload(dev["config"], {}) or {}
    return cfg.get("components") or F.DEFAULT_TRAINER
