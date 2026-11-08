"""Actions: "WHEN feed <op> value THEN do something", checked every time a feed gets a value."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ..db import new_id, now, parse_ts

OPS = {"lt": "is below", "gt": "is above", "eq": "equals"}
EFFECTS = {"on": "turn ON", "off": "turn OFF", "alert": "send an alert", "beep": "beep the buzzer"}


def matches(op, value, threshold):
    try:
        v, t = float(value), float(threshold)
        return {"lt": v < t, "gt": v > t, "eq": v == t}[op]
    except (TypeError, ValueError):
        return op == "eq" and str(value).upper() == str(threshold).upper()


def describe(a):
    s = f"When {a['feed_key']} {OPS.get(a['op'], a['op'])} {a['threshold']}, {EFFECTS.get(a['effect'], a['effect'])}"
    if a["effect"] in ("on", "off") and a.get("target_feed"):
        s += f" {a['target_feed']}"
        if a["effect"] == "on":
            s += f" for {a['seconds']} s"
    s += f"; wait {a['rest_seconds']} s before repeating; only {a['start_hhmm']}-{a['end_hhmm']}."
    return s


def _school_tz(db, team_id):
    tz = db.val("SELECT s.timezone FROM teams t JOIN classes c ON c.id = t.class_id JOIN schools s ON s.id = c.school_id WHERE t.id = ?", team_id)
    return ZoneInfo(tz or "America/Chicago")


def evaluate(db, feed, value):
    from . import safety
    rules = db.q("SELECT * FROM actions WHERE feed_key = ? AND enabled = 1", feed["key"])
    fired = []
    for a in rules:
        if not matches(a["op"], value, a["threshold"]):
            continue
        if a["last_fired_at"] and (parse_ts(now()).timestamp() - parse_ts(a["last_fired_at"]).timestamp()) < a["rest_seconds"]:
            continue
        hm = datetime.now(_school_tz(db, a["team_id"])).strftime("%H:%M")
        if not (a["start_hhmm"] <= hm <= a["end_hhmm"]):
            continue
        team = db.one("SELECT * FROM teams WHERE id = ?", a["team_id"])
        try:
            if a["effect"] in ("on", "off"):
                comp = (a["target_feed"] or "").split(".")[-1]
                if comp == "pump" and a["effect"] == "on" and not a["approved_by"]:
                    continue                      # pump rules wait for the teacher's OK
                safety.set_output(db, team, comp, "ON" if a["effect"] == "on" else "OFF", by_action=a["id"], seconds=a["seconds"])
            elif a["effect"] == "beep":
                safety.set_output(db, team, "buzzer", "ON", by_action=a["id"], seconds=2)
            elif a["effect"] == "alert":
                cls_id = team["class_id"]
                db.insert("alerts", id=new_id("al"), class_id=cls_id, kind="action",
                          message=f"{team['name']}: {a['name']} ({feed['key']} = {value})", created_at=now())
        except safety.SafetyError:
            continue
        db.run("UPDATE actions SET last_fired_at = ? WHERE id = ?", now(), a["id"])
        fired.append(a["id"])
    return fired
