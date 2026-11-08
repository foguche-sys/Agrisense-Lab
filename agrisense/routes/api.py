"""JSON endpoints.

/api/...      used by the pages (session cookie + X-CSRF header)
/api/v1/...   used by hardware and student code (X-Device-Key or X-Team-Key header; no cookies)
"""
from flask import Blueprint, abort, g, jsonify, request

from .. import auth
from ..db import ago, get_db, jload, now
from ..services import feeds as F
from ..services import ingest, safety
from ..services.live import tray_now, tray_series

bp = Blueprint("api", __name__, url_prefix="/api")


def _need_user():
    if not g.user:
        abort(401)


def _team_for_page(team_id):
    """A team the signed-in user may see in the Studio; returns (team, may_switch)."""
    d = get_db()
    team = d.one("SELECT * FROM teams WHERE id = ?", team_id)
    if not team:
        abort(404)
    if auth.allowed("studio.use", team_id=team["id"]) and any(m["role"] == "student" and m["team_id"] == team["id"] for m in g.memberships):
        return team, True
    if auth.allowed("studio.view", class_id=team["class_id"]):
        return team, auth.allowed("studio.lock", class_id=team["class_id"])
    abort(403)


# ---------------- pages ----------------

@bp.route("/class/<cid>/live")
def class_live(cid):
    _need_user()
    d = get_db()
    cls = d.one("SELECT * FROM classes WHERE id = ?", cid)
    if not cls or not (auth.allowed("live.view", class_id=cid) or auth.allowed("live.deid", class_id=cid)):
        abort(403)
    trays = d.q("SELECT * FROM trays WHERE kit_id = ? ORDER BY letter", cls["kit_id"]) if cls["kit_id"] else []
    running = d.q("SELECT p.tray_id, p.seconds, p.decided_at, p.simulated FROM pump_requests p WHERE p.class_id = ? AND p.status = 'approved'", cid)
    pending = d.val("SELECT COUNT(*) AS n FROM pump_requests WHERE class_id = ? AND status = 'pending'", cid)
    return jsonify({"ok": True, "simulated": bool(cls["sim_enabled"]), "pending": pending, "server_time": now(),
                    "trays": [{"id": t["id"], "letter": t["letter"], "soil": t["soil"], "label": t["label"], **(tray_now(d, cls, t) or {})} for t in trays],
                    "running": running})


@bp.route("/tray/<tid>/series")
def tray_history(tid):
    _need_user()
    d = get_db()
    tray = d.one("SELECT * FROM trays WHERE id = ?", tid)
    if not tray:
        abort(404)
    cls_id = request.args.get("class")
    cls = d.one("SELECT * FROM classes WHERE id = ? AND kit_id = ?", cls_id, tray["kit_id"])
    if not cls or not (auth.allowed("live.view", class_id=cls["id"]) or auth.allowed("live.deid", class_id=cls["id"])):
        abort(403)
    metric = request.args.get("metric", "moisture")
    if metric not in {m for m, _, _ in F.TRAY_METRICS}:
        abort(400)
    hours = max(1, min(720, int(request.args.get("hours", 48))))
    return jsonify({"ok": True, "metric": metric, "points": tray_series(d, cls, tray, metric, hours)})


@bp.route("/studio/<team_id>/state")
def studio_state(team_id):
    _need_user()
    team, may = _team_for_page(team_id)
    d = get_db()
    safety.auto_off_due(d)
    cls = d.one("SELECT * FROM classes WHERE id = ?", team["class_id"])
    keys = request.args.getlist("feed")
    out = {}
    for k in keys[:40]:
        f = d.one("SELECT * FROM feeds WHERE key = ?", k)
        if not f or (f["team_id"] != team["id"] and f["tray_id"] != team["tray_id"]):
            continue
        out[k] = {"value": f["last_value"], "at": f["last_at"], "unit": f["unit"]}
        if f["tray_id"] and cls["sim_enabled"]:
            tray = d.one("SELECT * FROM trays WHERE id = ?", f["tray_id"])
            r = tray_now(d, cls, tray)
            metric = k.split(".")[-1]
            if r and metric in r:
                out[k] = {"value": None if r[metric] is None else f"{r[metric]:g}", "at": r["at"], "unit": f["unit"], "simulated": True}
    return jsonify({"ok": True, "feeds": out, "unlocked": safety.controls_unlocked(cls), "may_switch": may, "server_time": now()})


@bp.route("/studio/<team_id>/series")
def studio_series(team_id):
    _need_user()
    team, _ = _team_for_page(team_id)
    d = get_db()
    f = d.one("SELECT * FROM feeds WHERE key = ?", request.args.get("feed"))
    if not f or (f["team_id"] != team["id"] and f["tray_id"] != team["tray_id"]):
        abort(404)
    hours = max(0.1, min(720.0, float(request.args.get("hours", 1))))
    cls = d.one("SELECT * FROM classes WHERE id = ?", team["class_id"])
    if f["tray_id"] and cls["sim_enabled"]:
        tray = d.one("SELECT * FROM trays WHERE id = ?", f["tray_id"])
        return jsonify({"ok": True, "points": tray_series(d, cls, tray, f["key"].split(".")[-1], max(1, int(hours)))})
    pts = F.history(d, f["id"], since=ago(seconds=int(hours * 3600)), limit=1000)
    return jsonify({"ok": True, "points": [{"t": p["created_at"], "v": p["num"], "s": p["value"]} for p in pts]})


@bp.route("/studio/<team_id>/set", methods=["POST"])
def studio_set(team_id):
    _need_user()
    team, _ = _team_for_page(team_id)
    body = request.get_json(silent=True) or {}
    comp = (body.get("feed") or "").split(".")[-1]
    if not (body.get("feed") or "").startswith(team["slug"] + "."):
        abort(400)
    try:
        v = safety.set_output(get_db(), team, comp, body.get("value"), actor_id=g.user["id"], memberships=g.memberships)
    except (safety.SafetyError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 409
    return jsonify({"ok": True, "value": v})


# ---------------- devices (firmware) ----------------

@bp.route("/v1/ingest", methods=["POST"])
def v1_ingest():
    d = get_db()
    try:
        dev = ingest.device_for_key(d, request.headers.get("X-Device-Key"))
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ingest.DeviceError("Send a JSON object.")
        return jsonify(ingest.handle(d, dev, body))
    except ingest.DeviceError as e:
        return jsonify({"ok": False, "error": str(e)}), e.code


@bp.route("/v1/commands")
def v1_commands():
    d = get_db()
    try:
        dev = ingest.device_for_key(d, request.headers.get("X-Device-Key"))
    except ingest.DeviceError as e:
        return jsonify({"ok": False, "error": str(e)}), e.code
    ingest.touch(d, dev)
    cfg = {"components": ingest.trainer_config(dev)} if dev["kind"] == "trainer" else {}
    return jsonify({"ok": True, "commands": ingest.take_commands(d, dev), "config": cfg, "server_time": now()})


# ---------------- team key (students' own code) ----------------

def _team_from_key():
    key = request.headers.get("X-Team-Key") or request.args.get("x-team-key")
    if not key:
        abort(401)
    d = get_db()
    team = d.one("SELECT * FROM teams WHERE key_hash = ?", auth.hash_key(key))
    if not team or (team["key_expires_at"] and team["key_expires_at"] < now()):
        abort(401)
    return team


def _team_feed(team, key):
    d = get_db()
    if not key.startswith(team["slug"] + "."):
        key = f"{team['slug']}.{key}"
    f = d.one("SELECT * FROM feeds WHERE key = ?", key)
    if not f:
        abort(404)
    return f


@bp.route("/v1/feeds")
def v1_feeds():
    team = _team_from_key()
    rows = get_db().q("SELECT key, name, unit, kind, last_value, last_at FROM feeds WHERE team_id = ? ORDER BY key", team["id"])
    return jsonify({"ok": True, "feeds": rows})


@bp.route("/v1/feeds/<path:key>/data", methods=["GET", "POST"])
def v1_feed_data(key):
    team = _team_from_key()
    d = get_db()
    f = _team_feed(team, key)
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        if "value" not in body:
            return jsonify({"ok": False, "error": 'Send {"value": ...}'}), 400
        comp = f["key"].split(".")[-1]
        if comp in F.OUTPUTS:
            cls = d.one("SELECT * FROM classes WHERE id = ?", team["class_id"])
            if str(body["value"]).upper() not in ("OFF", "0") and not safety.controls_unlocked(cls):
                return jsonify({"ok": False, "error": "Your teacher has locked the controls."}), 409
            try:
                v = safety.set_output(d, team, comp, body["value"], by_action="team-key")
            except (safety.SafetyError, ValueError) as e:
                return jsonify({"ok": False, "error": str(e)}), 409
            return jsonify({"ok": True, "value": v})
        if f["kind"] == "sensor" and f["device_id"]:
            return jsonify({"ok": False, "error": "This feed is written by the Trainer Board."}), 409
        v = F.write(d, f, body["value"], source=f"team:{team['slug']}")
        return jsonify({"ok": True, "value": v})
    limit = max(1, min(1000, int(request.args.get("limit", 100))))
    pts = F.history(d, f["id"], limit=limit)
    return jsonify({"ok": True, "feed": f["key"], "data": [{"value": p["value"], "created_at": p["created_at"]} for p in pts]})


@bp.route("/v1/feeds/<path:key>/data/last")
def v1_feed_last(key):
    team = _team_from_key()
    f = _team_feed(team, key)
    return jsonify({"ok": True, "feed": f["key"], "value": f["last_value"], "created_at": f["last_at"]})
