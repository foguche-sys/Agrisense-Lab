"""The 'now' reading for a tray: simulated when the class is in simulation mode, else the latest device values."""
from ..db import ago
from . import feeds as F
from .simulate import tray_reading

STALE_MINUTES = 15


def tray_now(db, cls, tray):
    out = _tray_now(db, cls, tray)
    if out:
        from .agronomy import advise
        from .safety import KIT_MAX_SECONDS, school_settings
        limit = min(school_settings(db, cls["school_id"])["pump_max_seconds"], KIT_MAX_SECONDS)
        out["advice"] = advise(db, cls, tray, out.get("moisture"), limit)
    return out


def _tray_now(db, cls, tray):
    if not tray:
        return None
    if cls["sim_enabled"]:
        return tray_reading(db, cls, tray)
    kit = db.one("SELECT * FROM kits WHERE id = ?", tray["kit_id"])
    out = {"simulated": False, "at": None}
    for metric, _, _ in F.TRAY_METRICS:
        f = db.one("SELECT last_value, last_at FROM feeds WHERE key = ?", F.tray_feed_key(kit["id"], tray["letter"], metric))
        v = F.to_num(f["last_value"]) if f else None
        out[metric] = v
        if f and f["last_at"] and (not out["at"] or f["last_at"] > out["at"]):
            out["at"] = f["last_at"]
    out["too_dry"] = out.get("moisture") is not None and out["moisture"] < 10
    out["stale"] = not out["at"] or out["at"] < ago(minutes=STALE_MINUTES)
    return out


def tray_series(db, cls, tray, metric="moisture", hours=48):
    if cls["sim_enabled"]:
        from .simulate import series
        return [{"t": r["at"], "v": r[metric]} for r in series(db, cls, tray, 48, hours)]
    kit = db.one("SELECT * FROM kits WHERE id = ?", tray["kit_id"])
    f = db.one("SELECT id FROM feeds WHERE key = ?", F.tray_feed_key(kit["id"], tray["letter"], metric))
    if not f:
        return []
    return [{"t": p["created_at"], "v": p["num"]} for p in F.history(db, f["id"], since=ago(hours=hours), limit=2000)]
