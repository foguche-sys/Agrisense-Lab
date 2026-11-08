"""IoT Studio (Adafruit IO style): each team builds dashboards from feeds, switches its Trainer outputs,
writes Actions, and gets a team key for its own code. Teachers can open any team in their class (read + lock)."""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import auth
from ..db import ahead, jdump, jload, new_id, now
from ..services import feeds as F
from ..services.actions import EFFECTS, OPS, describe
from ..services.safety import TRAINER_PUMP_MAX, TRAINER_PUMP_REST, controls_unlocked
from .util import db, err, ok, student_team

bp = Blueprint("studio", __name__, url_prefix="/studio")

BLOCKS = {
    "toggle": "Toggle (ON/OFF output)",
    "slider": "Slider (servo, LED bar, motor)",
    "gauge": "Gauge (one sensor)",
    "chart": "Line chart",
    "value": "Big number",
    "indicator": "Indicator light",
    "stream": "Stream (latest values)",
}


@bp.before_request
def _signed_in():
    if not g.user:
        return redirect(url_for("public.login", next=request.path))


def team_ctx():
    """(cls, team, can_edit). Students: their own team. Teachers: ?team= inside their class."""
    d = db()
    cls, team = student_team()
    if team:
        return cls, team, True
    tid = request.values.get("team")
    team = d.one("SELECT * FROM teams WHERE id = ?", tid) if tid else None
    if not team:
        from ..rbac import classes_for
        ids = classes_for(d, g.memberships)
        if ids:
            team = d.one("SELECT * FROM teams WHERE class_id = ? ORDER BY name", ids[0])
    if not team or not auth.allowed("studio.view", class_id=team["class_id"]):
        abort(403)
    cls = d.one("SELECT * FROM classes WHERE id = ?", team["class_id"])
    return cls, team, auth.allowed("studio.lock", class_id=cls["id"])


def team_feeds(d, team):
    feeds = d.q("SELECT * FROM feeds WHERE team_id = ? ORDER BY key", team["id"])
    if team["tray_id"]:
        tray = d.one("SELECT * FROM trays WHERE id = ?", team["tray_id"])
        feeds += d.q("SELECT * FROM feeds WHERE tray_id = ? ORDER BY key", tray["id"])
    return feeds


def _common(cls, team):
    d = db()
    teams = d.q("SELECT id, name FROM teams WHERE class_id = ? ORDER BY name", cls["id"]) if not student_team()[1] else []
    return {"cls": cls, "team": team, "teams": teams, "unlocked": controls_unlocked(cls),
            "unlock_until": cls["controls_unlocked_until"]}


def _url(endpoint, team, **kw):
    if not student_team()[1]:
        kw["team"] = team["id"]
    return url_for(endpoint, **kw)


@bp.route("/")
def dashboards():
    cls, team, can_edit = team_ctx()
    d = db()
    dash = d.q("SELECT * FROM dashboards WHERE team_id = ? ORDER BY created_at", team["id"])
    return render_template("studio/dashboards.html", dashboards=dash, can_edit=can_edit, **_common(cls, team))


@bp.route("/new", methods=["POST"])
def new_dashboard():
    cls, team, can_edit = team_ctx()
    if not can_edit:
        abort(403)
    d = db()
    did = new_id("db")
    name = (request.form.get("name") or "My dashboard")[:60]
    blocks = []
    if request.form.get("starter") == "1":
        F.ensure_team_feeds(d, team, F.DEFAULT_TRAINER)
        s = team["slug"]
        blocks = [
            {"id": new_id("b"), "type": "toggle", "feed": f"{s}.pump", "title": "Pump"},
            {"id": new_id("b"), "type": "toggle", "feed": f"{s}.fan", "title": "Fan"},
            {"id": new_id("b"), "type": "gauge", "feed": f"{s}.moisture", "title": "Soil moisture", "min": 0, "max": 50},
            {"id": new_id("b"), "type": "gauge", "feed": f"{s}.air-temp", "title": "Air temperature", "min": 0, "max": 45},
            {"id": new_id("b"), "type": "chart", "feed": f"{s}.pressure", "title": "Pressure (kPa)", "hours": 1},
            {"id": new_id("b"), "type": "indicator", "feed": f"{s}.tank", "title": "Tank", "on": "OK"},
            {"id": new_id("b"), "type": "slider", "feed": f"{s}.vent", "title": "Vent servo", "min": 0, "max": 180},
        ]
    d.insert("dashboards", id=did, team_id=team["id"], name=name, blocks=jdump(blocks), created_at=now())
    return redirect(_url("studio.dashboard", team, did=did))


@bp.route("/dash/<did>", methods=["GET", "POST"])
def dashboard(did):
    cls, team, can_edit = team_ctx()
    d = db()
    dash = d.one("SELECT * FROM dashboards WHERE id = ? AND team_id = ?", did, team["id"])
    if not dash:
        abort(404)
    blocks = jload(dash["blocks"], [])
    feeds = team_feeds(d, team)
    keys = {f["key"] for f in feeds}
    if request.method == "POST":
        if not can_edit:
            abort(403)
        f = request.form
        act = f.get("do")
        if act == "add":
            if f.get("type") not in BLOCKS or f.get("feed") not in keys:
                err("Choose a block type and one of your feeds.")
            else:
                b = {"id": new_id("b"), "type": f["type"], "feed": f["feed"], "title": (f.get("title") or f["feed"].split(".")[-1])[:40]}
                for k in ("min", "max", "hours"):
                    if f.get(k):
                        try:
                            b[k] = float(f[k])
                        except ValueError:
                            pass
                if f["type"] == "indicator":
                    b["on"] = (f.get("on") or "ON")[:12]
                blocks.append(b)
                ok("Block added.")
        elif act == "remove":
            blocks = [b for b in blocks if b["id"] != f.get("block")]
        elif act in ("up", "down"):
            i = next((n for n, b in enumerate(blocks) if b["id"] == f.get("block")), None)
            j = None if i is None else (i - 1 if act == "up" else i + 1)
            if i is not None and 0 <= j < len(blocks):
                blocks[i], blocks[j] = blocks[j], blocks[i]
        elif act == "rename":
            d.update("dashboards", did, name=(f.get("name") or dash["name"])[:60])
        elif act == "delete":
            d.run("DELETE FROM dashboards WHERE id = ?", did)
            return redirect(_url("studio.dashboards", team))
        d.update("dashboards", did, blocks=jdump(blocks[:24]))
        return redirect(_url("studio.dashboard", team, did=did))
    fmap = {f["key"]: f for f in feeds}
    return render_template("studio/dashboard.html", dash=dash, blocks=blocks, feeds=feeds, fmap=fmap, block_types=BLOCKS,
                           can_edit=can_edit, outputs=F.OUTPUTS, pump_max=TRAINER_PUMP_MAX, pump_rest=TRAINER_PUMP_REST,
                           **_common(cls, team))


@bp.route("/feeds", methods=["GET", "POST"])
def feeds():
    cls, team, can_edit = team_ctx()
    d = db()
    if request.method == "POST":
        if not can_edit:
            abort(403)
        name = (request.form.get("name") or "").strip()[:40]
        slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        if not slug:
            err("Give the feed a name, e.g. leaf count.")
        elif d.val("SELECT id FROM feeds WHERE key = ?", f"{team['slug']}.{slug}"):
            err("You already have a feed with that name.")
        else:
            F.get_or_create(d, f"{team['slug']}.{slug}", name, (request.form.get("unit") or "")[:12], "manual", team_id=team["id"])
            ok("Feed created. Add values here or send them from your code with the team key.")
        return redirect(_url("studio.feeds", team))
    return render_template("studio/feeds.html", feeds=team_feeds(d, team), can_edit=can_edit, **_common(cls, team))


@bp.route("/feeds/<path:key>", methods=["GET", "POST"])
def feed(key):
    cls, team, can_edit = team_ctx()
    d = db()
    f = next((x for x in team_feeds(d, team) if x["key"] == key), None)
    if not f:
        abort(404)
    if request.method == "POST":
        if not can_edit or f["kind"] != "manual":
            abort(403)
        v = (request.form.get("value") or "").strip()[:40]
        if v:
            F.write(d, f, v, source=f"user:{g.user['id']}")
            ok("Value added.")
        return redirect(_url("studio.feed", team, key=key))
    pts = F.history(d, f["id"], limit=200)
    return render_template("studio/feed.html", f=f, points=list(reversed(pts)), can_edit=can_edit, **_common(cls, team))


@bp.route("/devices", methods=["GET", "POST"])
def devices():
    cls, team, can_edit = team_ctx()
    d = db()
    dev = d.one("SELECT * FROM devices WHERE team_id = ? AND kind = 'trainer' AND status != 'retired'", team["id"])
    comps = (jload(dev["config"], {}) or {}).get("components") if dev else None
    comps = comps or F.DEFAULT_TRAINER
    if request.method == "POST":
        if not can_edit:
            abort(403)
        chosen = [c for c in request.form.getlist("components") if c in F.TRAINER_COMPONENTS]
        if dev:
            cfg = jload(dev["config"], {}) or {}
            cfg["components"] = chosen
            d.update("devices", dev["id"], config=jdump(cfg))
        F.ensure_team_feeds(d, team, chosen)
        ok("Components saved. Each one now has a feed you can add to a dashboard.")
        return redirect(_url("studio.devices", team))
    tray = d.one("SELECT * FROM trays WHERE id = ?", team["tray_id"]) if team["tray_id"] else None
    return render_template("studio/devices.html", dev=dev, comps=comps, components=F.TRAINER_COMPONENTS, tray=tray,
                           can_edit=can_edit, **_common(cls, team))


@bp.route("/actions", methods=["GET", "POST"])
def actions():
    cls, team, can_edit = team_ctx()
    d = db()
    feeds_ = team_feeds(d, team)
    keys = {f["key"] for f in feeds_}
    if request.method == "POST":
        if not can_edit:
            abort(403)
        f = request.form
        act = f.get("do")
        if act == "create":
            target = f.get("target_feed") or None
            if f.get("feed_key") not in keys or f.get("op") not in OPS or f.get("effect") not in EFFECTS:
                err("Pick a feed, a test and what to do.")
            elif f["effect"] in ("on", "off") and (not target or target not in keys or target.split(".")[-1] not in F.OUTPUTS):
                err("Pick an output (pump, fan…) to switch.")
            else:
                try:
                    seconds = max(1, min(TRAINER_PUMP_MAX, int(f.get("seconds") or 20)))
                    rest = max(TRAINER_PUMP_REST, int(f.get("rest_seconds") or 120))
                except ValueError:
                    err("Use whole numbers for seconds.")
                    return redirect(_url("studio.actions", team))
                d.insert("actions", id=new_id("ac"), team_id=team["id"], name=(f.get("name") or "My rule")[:60], feed_key=f["feed_key"],
                         op=f["op"], threshold=(f.get("threshold") or "0")[:20], effect=f["effect"], target_feed=target,
                         seconds=seconds, rest_seconds=rest, start_hhmm=f.get("start_hhmm") or "08:00",
                         end_hhmm=f.get("end_hhmm") or "15:30", enabled=1, created_at=now(),
                         approved_by=g.user["id"] if auth.allowed("actions.approve", class_id=cls["id"]) else None)
                needs_ok = target and target.endswith(".pump") and f["effect"] == "on" and not auth.allowed("actions.approve", class_id=cls["id"])
                ok("Action saved." + (" Your teacher has to approve it before it can run the pump." if needs_ok else ""))
        else:
            a = d.one("SELECT * FROM actions WHERE id = ? AND team_id = ?", f.get("action_id"), team["id"])
            if a and act == "toggle":
                d.update("actions", a["id"], enabled=0 if a["enabled"] else 1)
            elif a and act == "delete":
                d.run("DELETE FROM actions WHERE id = ?", a["id"])
        return redirect(_url("studio.actions", team))
    rules = d.q("SELECT * FROM actions WHERE team_id = ? ORDER BY created_at", team["id"])
    for r in rules:
        r["text"] = describe(r)
    outputs = [f for f in feeds_ if f["key"].split(".")[-1] in F.OUTPUTS and f["team_id"]]
    return render_template("studio/actions.html", rules=rules, feeds=feeds_, outputs=outputs, ops=OPS, effects=EFFECTS,
                           can_edit=can_edit, pump_max=TRAINER_PUMP_MAX, pump_rest=TRAINER_PUMP_REST, **_common(cls, team))


@bp.route("/code", methods=["GET", "POST"])
def code():
    cls, team, can_edit = team_ctx()
    d = db()
    new_key = None
    if request.method == "POST":
        if not can_edit:
            abort(403)
        if request.form.get("do") == "revoke":
            d.update("teams", team["id"], key_hash=None, key_hint=None, key_expires_at=None)
            ok("Key revoked. Code using it stops working now.")
        else:
            new_key = auth.new_key("ask")
            d.update("teams", team["id"], key_hash=auth.hash_key(new_key), key_hint=new_key[-4:], key_expires_at=ahead(days=120))
        team = d.one("SELECT * FROM teams WHERE id = ?", team["id"])
    base = request.host_url.rstrip("/")
    return render_template("studio/code.html", new_key=new_key, base=base, can_edit=can_edit, feeds=team_feeds(d, team),
                           **_common(cls, team))
