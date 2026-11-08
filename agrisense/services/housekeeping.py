"""Routine upkeep: mark silent devices offline, show stale Trainer pumps OFF, apply each school's data retention.

Runs from the `housekeeping` CLI command (cron) and also, at most every 5 minutes per web process,
inside the app itself, so a simple one-service deploy needs no separate cron job."""
import threading
import time

from ..db import ago, new_id, now

_lock = threading.Lock()
_last = 0.0
INTERVAL = 300


def run(db):
    from .safety import auto_off_due, school_settings
    auto_off_due(db)
    stale = db.q("SELECT * FROM devices WHERE status = 'online' AND last_seen < ?", ago(minutes=15))
    for d in stale:
        db.update("devices", d["id"], status="offline")
        db.insert("alerts", id=new_id("al"), school_id=d["school_id"], device_id=d["id"], kind="offline",
                  message=f"{d['serial']} hasn't reported for 15 minutes. Check power and Wi-Fi.", created_at=now())
    pruned = 0
    for s in db.q("SELECT id FROM schools"):
        cutoff = ago(days=school_settings(db, s["id"]).get("retention_days", 365))
        ids = [r["id"] for r in db.q("SELECT f.id FROM feeds f LEFT JOIN kits k ON k.id = f.kit_id LEFT JOIN teams t ON t.id = f.team_id "
                                     "LEFT JOIN classes c ON c.id = t.class_id WHERE COALESCE(f.school_id, k.school_id, c.school_id) = ?", s["id"])]
        for fid in ids:
            pruned += db.val("SELECT COUNT(*) AS n FROM datapoints WHERE feed_id = ? AND created_at < ?", fid, cutoff) or 0
            db.run("DELETE FROM datapoints WHERE feed_id = ? AND created_at < ?", fid, cutoff)
    db.run("DELETE FROM commands WHERE expires_at < ?", ago(days=2))
    return len(stale), pruned


def maybe_run(database):
    """Called on requests; does the work in its own connection at most every INTERVAL seconds."""
    global _last
    if time.time() - _last < INTERVAL or not _lock.acquire(blocking=False):
        return
    try:
        _last = time.time()
        from ..db import Conn
        con = Conn(database)
        try:
            run(con)
            con.commit()
        except Exception:
            con.rollback()
        finally:
            con.close()
    finally:
        _lock.release()
