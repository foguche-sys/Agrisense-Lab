"""Pump and output safety. Every switch goes through here, whoever (or whatever rule) asks.

Bench pump (pump node): students request -> teacher/co-teacher approves -> one tray at a time,
  never longer than the school's limit (300 s kit maximum), optionally class hours only.
Trainer outputs (IoT Studio): a team may switch its own Trainer while the teacher has
  controls unlocked; pump ON needs tank OK, max 30 s, then 60 s rest. OFF/STOP is always allowed.
The device firmware enforces the same limits again; this layer just refuses early and explains why.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import ago, ahead, jload, new_id, now, parse_ts
from ..rbac import can
from . import feeds as F
from .audit import log

KIT_MAX_SECONDS = 300
TRAINER_PUMP_MAX = 30
TRAINER_PUMP_REST = 60


class SafetyError(Exception):
    pass


def school_settings(db, school_id):
    s = jload(db.val("SELECT settings FROM schools WHERE id = ?", school_id), {}) or {}
    s.setdefault("pump_max_seconds", KIT_MAX_SECONDS)
    s.setdefault("class_hours_only", True)
    s.setdefault("class_hours", ["07:00", "16:30"])
    s.setdefault("pump_needs_approval", True)
    return s


def in_class_hours(db, school_id):
    s = school_settings(db, school_id)
    if not s["class_hours_only"]:
        return True
    tz = ZoneInfo(db.val("SELECT timezone FROM schools WHERE id = ?", school_id) or "America/Chicago")
    local = datetime.now(tz)
    hm = local.strftime("%H:%M")
    return local.weekday() < 5 and s["class_hours"][0] <= hm <= s["class_hours"][1]


def pump_device(db, kit_id):
    return db.one("SELECT * FROM devices WHERE kit_id = ? AND kind = 'pump' AND status != 'retired'", kit_id)


def queue_command(db, device_id, command, actor=None, ttl=60):
    db.insert("commands", device_id=device_id, command=command, created_by=actor, created_at=now(), expires_at=ahead(seconds=ttl))


def running_request(db, class_or_kit_classes):
    """An approved, still-running bench run for any class sharing this kit."""
    for r in db.q("SELECT * FROM pump_requests WHERE status = 'approved' AND class_id IN (%s)" %
                  ",".join("?" for _ in class_or_kit_classes), *class_or_kit_classes):
        end = parse_ts(r["decided_at"]).timestamp() + r["seconds"]
        if end > parse_ts(now()).timestamp():
            return r
        db.run("UPDATE pump_requests SET status = 'done' WHERE id = ?", r["id"])
    return None


def request_bench(db, user, memberships, cls, tray, seconds, reason, team_id=None, moisture=None, prediction=None):
    if not can(db, memberships, "pump.request", class_id=cls["id"], team_id=team_id):
        raise SafetyError("You can't request pump runs in this class.")
    if not cls["pump_requests_allowed"]:
        raise SafetyError("Your teacher has turned pump requests off for now.")
    limit = min(school_settings(db, cls["school_id"])["pump_max_seconds"], KIT_MAX_SECONDS)
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        raise SafetyError("Enter the number of seconds.")
    if not 1 <= seconds <= limit:
        raise SafetyError(f"Pick between 1 and {limit} seconds.")
    if team_id and db.one("SELECT id FROM pump_requests WHERE team_id = ? AND status = 'pending'", team_id):
        raise SafetyError("Your team already has a request waiting.")
    try:
        prediction = None if prediction in (None, "") else round(float(prediction), 1)
    except (TypeError, ValueError):
        raise SafetyError("Your prediction should be a number, like 24.5.")
    rid = new_id("pr")
    db.insert("pump_requests", id=rid, prediction=prediction, class_id=cls["id"], team_id=team_id, tray_id=tray["id"], requested_by=user["id"],
              seconds=seconds, reason=(reason or "")[:200], moisture_before=moisture, status="pending",
              simulated=1 if cls["sim_enabled"] else 0, created_at=now())
    return rid


def decide(db, user, memberships, req_id, approve):
    req = db.one("SELECT * FROM pump_requests WHERE id = ?", req_id)
    if not req or req["status"] != "pending":
        raise SafetyError("That request is no longer waiting.")
    if not can(db, memberships, "pump.approve", class_id=req["class_id"]):
        raise SafetyError("Only the class teacher can approve pump runs.")
    cls = db.one("SELECT * FROM classes WHERE id = ?", req["class_id"])
    if not approve:
        db.run("UPDATE pump_requests SET status = 'declined', decided_by = ?, decided_at = ? WHERE id = ?", user["id"], now(), req_id)
        return "declined"
    if not req["simulated"]:
        if not in_class_hours(db, cls["school_id"]):
            raise SafetyError("Pump runs are only allowed during class hours (school setting).")
        kit_classes = [r["id"] for r in db.q("SELECT id FROM classes WHERE kit_id = ?", cls["kit_id"])] or [cls["id"]]
        busy = running_request(db, kit_classes)
        if busy:
            raise SafetyError("Another tray is being watered right now. Approve again when it finishes.")
        dev = pump_device(db, cls["kit_id"])
        if not dev:
            raise SafetyError("This kit has no pump node registered.")
        letter = db.val("SELECT letter FROM trays WHERE id = ?", req["tray_id"])
        queue_command(db, dev["id"], f"RUN,{req['seconds']},{letter}", user["id"])
    db.run("UPDATE pump_requests SET status = 'approved', decided_by = ?, decided_at = ? WHERE id = ?", user["id"], now(), req_id)
    log(db, "pump.approve", f"{req['seconds']} s tray {req['tray_id']}{' (simulated)' if req['simulated'] else ''}", school_id=cls["school_id"])
    return "approved"


def stop_bench(db, user, memberships, cls):
    if not can(db, memberships, "pump.stop", class_id=cls["id"]):
        raise SafetyError("You can't stop the pump here.")
    dev = pump_device(db, cls["kit_id"]) if cls["kit_id"] else None
    if dev:
        queue_command(db, dev["id"], "STOP", user["id"], ttl=300)
    db.run("UPDATE pump_requests SET status = 'stopped' WHERE class_id = ? AND status = 'approved'", cls["id"])
    log(db, "pump.stop", "STOP pressed", school_id=cls["school_id"])


# ---------------- Trainer outputs (IoT Studio) ----------------

def controls_unlocked(cls):
    return bool(cls["controls_unlocked_until"]) and cls["controls_unlocked_until"] > now()


def set_output(db, team, comp, value, actor_id=None, memberships=None, by_action=None, seconds=None):
    """Switch a Trainer output for a team. Returns the value written; raises SafetyError."""
    if comp not in F.OUTPUTS:
        raise SafetyError("That feed is a sensor; it can't be switched.")
    cls = db.one("SELECT * FROM classes WHERE id = ?", team["class_id"])
    value = str(value).upper() if comp in ("pump", "fan", "buzzer") else str(value)
    stopping = value in ("OFF", "0")
    if memberships is not None and not by_action:
        teacherish = can(db, memberships, "studio.lock", class_id=cls["id"])
        member = can(db, memberships, "studio.use", team_id=team["id"])
        if not (teacherish or member):
            raise SafetyError("Only your team can switch these outputs.")
        if not teacherish and not stopping and not controls_unlocked(cls):
            raise SafetyError("Your teacher has locked the controls.")
    feed = F.get_or_create(db, f"{team['slug']}.{comp}", F.TRAINER_COMPONENTS[comp][0], F.TRAINER_COMPONENTS[comp][2], "output", team_id=team["id"])
    if comp == "pump" and value == "ON":
        tank = db.one("SELECT last_value FROM feeds WHERE key = ?", f"{team['slug']}.tank")
        if tank and (tank["last_value"] or "").upper() == "LOW":
            raise SafetyError("Tank level is LOW. Refill the reservoir first.")
        off = F.last_off_at(db, feed["id"])
        if off and off > ago(seconds=TRAINER_PUMP_REST):
            wait = TRAINER_PUMP_REST - int(parse_ts(now()).timestamp() - parse_ts(off).timestamp())
            raise SafetyError(f"The pump is resting. Try again in {max(wait, 1)} s.")
    if comp == "vent":
        v = max(0, min(180, int(float(value))))
        value = str(v)
    if comp == "ledbar":
        value = str(max(0, min(10, int(float(value)))))
    if comp == "motor":
        value = str(max(-100, min(100, int(float(value)))))
    dev = db.one("SELECT * FROM devices WHERE team_id = ? AND kind = 'trainer' AND status != 'retired'", team["id"])
    if dev:
        run_s = max(1, min(int(seconds or TRAINER_PUMP_MAX), TRAINER_PUMP_MAX))
        extra = f",{run_s}" if comp in ("pump", "fan", "buzzer") and value == "ON" and (comp == "pump" or seconds) else ""
        queue_command(db, dev["id"], f"SET,{comp},{value}{extra}", actor_id, ttl=30)
    src = f"action:{by_action}" if by_action else (f"user:{actor_id}" if actor_id else "system")
    F.write(db, feed, value, source=src, run_actions=False)
    return value


def auto_off_due(db):
    """Fallback for dashboards: show the Trainer pump OFF once its 30 s window has passed."""
    for f in db.q("SELECT * FROM feeds WHERE key LIKE '%.pump' AND team_id IS NOT NULL AND last_value = 'ON'"):
        if f["last_at"] and f["last_at"] < ago(seconds=TRAINER_PUMP_MAX):
            F.write(db, f, "OFF", source="safety:auto-off", run_actions=False)
