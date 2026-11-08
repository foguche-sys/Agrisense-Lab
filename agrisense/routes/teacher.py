"""Teacher: live bench, pump approvals and STOP, simulation, Studio unlock, lessons, gradebook, teams."""
import secrets

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import auth
from ..db import ahead, jdump, jload, new_id, now
from ..services import safety
from ..services.audit import log
from ..services.live import tray_now
from .util import db, err, need, ok, pick_class

bp = Blueprint("teacher", __name__, url_prefix="/teach")


@bp.before_request
def _signed_in():
    if not g.user:
        return redirect(url_for("public.login", next=request.path))


def _cls(cid):
    c = db().one("SELECT * FROM classes WHERE id = ?", cid)
    if not c:
        abort(404)
    return c


@bp.route("/")
def home():
    cls, ids = pick_class()
    if not cls:
        if any(m["role"] in ("teacher", "co_teacher", "substitute", "school_admin", "client_admin") for m in g.memberships):
            return render_template("teacher/no_class.html")
        abort(403)
    need("live.view", class_id=cls["id"])
    d = db()
    classes = [d.one("SELECT id, name, code FROM classes WHERE id = ?", i) for i in ids]
    trays = d.q("SELECT * FROM trays WHERE kit_id = ? ORDER BY letter", cls["kit_id"]) if cls["kit_id"] else []
    teams = d.q("SELECT t.*, tr.letter FROM teams t LEFT JOIN trays tr ON tr.id = t.tray_id WHERE t.class_id = ? ORDER BY t.name", cls["id"])
    pending = d.q("""SELECT p.*, u.name AS who, t.name AS team, tr.letter FROM pump_requests p JOIN users u ON u.id = p.requested_by
                     LEFT JOIN teams t ON t.id = p.team_id JOIN trays tr ON tr.id = p.tray_id
                     WHERE p.class_id = ? AND p.status = 'pending' ORDER BY p.created_at""", cls["id"])
    recent = d.q("""SELECT p.*, t.name AS team, tr.letter FROM pump_requests p LEFT JOIN teams t ON t.id = p.team_id
                    JOIN trays tr ON tr.id = p.tray_id WHERE p.class_id = ? AND p.status != 'pending'
                    ORDER BY p.created_at DESC LIMIT 8""", cls["id"])
    alerts = d.q("SELECT * FROM alerts WHERE (class_id = ? OR school_id = ?) AND resolved_at IS NULL ORDER BY created_at DESC LIMIT 6",
                 cls["id"], cls["school_id"])
    pending_actions = d.q("""SELECT a.*, t.name AS team FROM actions a JOIN teams t ON t.id = a.team_id
                             WHERE t.class_id = ? AND a.target_feed LIKE '%.pump' AND a.effect = 'on' AND a.approved_by IS NULL""", cls["id"])
    readings = {t["id"]: tray_now(d, cls, t) for t in trays}
    return render_template("teacher/home.html", cls=cls, classes=classes, trays=trays, readings=readings, teams=teams, pending=pending,
                           recent=recent, alerts=alerts, unlocked=safety.controls_unlocked(cls), pending_actions=pending_actions,
                           limit=min(safety.school_settings(d, cls["school_id"])["pump_max_seconds"], safety.KIT_MAX_SECONDS))


@bp.route("/<cid>/pump/<rid>", methods=["POST"])
def decide(cid, rid):
    cls = _cls(cid)
    try:
        r = safety.decide(db(), g.user, g.memberships, rid, request.form.get("do") == "approve")
        ok("Approved. The pump starts within a few seconds." if r == "approved" else "Request declined.")
    except safety.SafetyError as e:
        err(str(e))
    return redirect(url_for("teacher.home", **{"class": cls["id"]}))


@bp.route("/<cid>/stop", methods=["POST"])
def stop(cid):
    cls = _cls(cid)
    try:
        safety.stop_bench(db(), g.user, g.memberships, cls)
        for t in db().q("SELECT * FROM teams WHERE class_id = ?", cls["id"]):
            try:
                safety.set_output(db(), t, "pump", "OFF", actor_id=g.user["id"])
            except safety.SafetyError:
                pass
        ok("STOP sent to every pump in this class.")
    except safety.SafetyError as e:
        err(str(e))
    return redirect(url_for("teacher.home", **{"class": cls["id"]}))


@bp.route("/<cid>/settings", methods=["POST"])
def class_settings(cid):
    cls = _cls(cid)
    d = db()
    f = request.form
    act = f.get("do")
    if act == "sim":
        need("sim.control", class_id=cid)
        on = f.get("on") == "1"
        event = f.get("event") if f.get("event") in ("none", "dry_spell", "heat_wave") else "none"
        cols = {"sim_enabled": 1 if on else 0, "sim_event": event}
        if on and not cls["sim_enabled"]:
            cols["sim_started_at"] = now()
        if f.get("speed"):
            cols["sim_speed"] = max(1, min(720, int(f["speed"])))
        d.update("classes", cid, **cols)
        log(d, "class.sim", jdump(cols), school_id=cls["school_id"])
        ok("Simulation on. Readings are labelled SIMULATED." if on else "Live data from the bench.")
    elif act == "unlock":
        need("studio.lock", class_id=cid)
        minutes = max(0, min(120, int(f.get("minutes") or 40)))
        d.update("classes", cid, controls_unlocked_until=ahead(minutes=minutes) if minutes else None)
        ok(f"Studio controls unlocked for {minutes} min." if minutes else "Studio controls locked.")
    elif act == "pump_requests":
        need("pump.approve", class_id=cid)
        d.update("classes", cid, pump_requests_allowed=1 if f.get("on") == "1" else 0)
        ok("Pump requests updated.")
    elif act == "approve_action":
        need("actions.approve", class_id=cid)
        a = d.one("SELECT a.* FROM actions a JOIN teams t ON t.id = a.team_id WHERE a.id = ? AND t.class_id = ?", f.get("action_id"), cid)
        if a:
            d.update("actions", a["id"], approved_by=g.user["id"], seconds=min(a["seconds"], safety.TRAINER_PUMP_MAX),
                     rest_seconds=max(a["rest_seconds"], safety.TRAINER_PUMP_REST))
            log(d, "action.approve", a["name"], school_id=cls["school_id"])
            ok(f"Action “{a['name']}” approved. It can now run the Trainer pump (max {safety.TRAINER_PUMP_MAX} s).")
    elif act == "resolve_alert":
        d.run("UPDATE alerts SET resolved_at = ? WHERE id = ? AND (class_id = ? OR school_id = ?)", now(), f.get("alert_id"), cid, cls["school_id"])
    return redirect(request.referrer or url_for("teacher.home", **{"class": cid}))


# ---------------- lessons ----------------

@bp.route("/<cid>/lessons", methods=["GET", "POST"])
def lessons(cid):
    cls = _cls(cid)
    need("live.view", class_id=cid)
    d = db()
    if request.method == "POST":
        need("classes.manage", class_id=cid)
        lesson = d.one("SELECT * FROM lessons WHERE id = ?", request.form.get("lesson_id"))
        if lesson:
            d.insert("assignments", id=new_id("as"), class_id=cid, lesson_id=lesson["id"], starts_on=request.form.get("starts_on") or None,
                     due_on=request.form.get("due_on") or None, data_source=request.form.get("data_source") or ("sim" if cls["sim_enabled"] else "live"),
                     allow_pump=1 if request.form.get("allow_pump", "1") == "1" else 0,
                     points=int(request.form.get("points") or 20), created_by=g.user["id"], created_at=now())
            ok(f"Lesson {lesson['code']} assigned. Students see it on their home page.")
        return redirect(url_for("teacher.lessons", cid=cid))
    all_lessons = d.q("SELECT * FROM lessons ORDER BY code")
    assigned = d.q("SELECT a.*, l.code, l.title FROM assignments a JOIN lessons l ON l.id = a.lesson_id WHERE a.class_id = ? ORDER BY l.code", cid)
    return render_template("teacher/lessons.html", cls=cls, lessons=all_lessons, assigned=assigned)


@bp.route("/<cid>/gradebook", methods=["GET", "POST"])
def gradebook(cid):
    cls = _cls(cid)
    if not (auth.allowed("grade", class_id=cid) or auth.allowed("grade.assist", class_id=cid) or auth.allowed("journal.view", class_id=cid)):
        abort(403)
    d = db()
    if request.method == "POST":
        if not auth.allowed("grade", class_id=cid):
            abort(403)
        j = d.one("SELECT j.* FROM journals j JOIN teams t ON t.id = j.team_id WHERE j.id = ? AND t.class_id = ?", request.form.get("journal_id"), cid)
        if j:
            act = request.form.get("do")
            if act == "return":
                d.update("journals", j["id"], status="returned", feedback=request.form.get("feedback", "")[:2000], graded_by=g.user["id"], updated_at=now())
                ok("Returned to the team with your feedback.")
            else:
                try:
                    score = int(request.form.get("score"))
                except (TypeError, ValueError):
                    err("Enter a score.")
                    return redirect(url_for("teacher.gradebook", cid=cid))
                d.update("journals", j["id"], status="graded", score=score, feedback=request.form.get("feedback", "")[:2000],
                         graded_by=g.user["id"], updated_at=now())
                ok("Grade saved.")
        return redirect(url_for("teacher.gradebook", cid=cid, open=request.form.get("journal_id")))
    assigns = d.q("SELECT a.*, l.code, l.title FROM assignments a JOIN lessons l ON l.id = a.lesson_id WHERE a.class_id = ? ORDER BY l.code", cid)
    teams = d.q("SELECT * FROM teams WHERE class_id = ? ORDER BY name", cid)
    jr = d.q("SELECT j.* FROM journals j JOIN teams t ON t.id = j.team_id WHERE t.class_id = ?", cid)
    grid = {(j["assignment_id"], j["team_id"]): j for j in jr}
    opened = d.one("SELECT j.*, t.name AS team, l.title, l.code, a.points FROM journals j JOIN teams t ON t.id = j.team_id "
                   "JOIN assignments a ON a.id = j.assignment_id JOIN lessons l ON l.id = a.lesson_id WHERE j.id = ? AND t.class_id = ?",
                   request.args.get("open"), cid) if request.args.get("open") else None
    return render_template("teacher/gradebook.html", cls=cls, assigns=assigns, teams=teams, grid=grid, opened=opened)


# ---------------- teams and students ----------------

@bp.route("/<cid>/teams", methods=["GET", "POST"])
def teams(cid):
    cls = _cls(cid)
    need("live.view", class_id=cid)
    d = db()
    if request.method == "POST":
        need("people.manage", class_id=cid)
        f = request.form
        act = f.get("do")
        if act == "move":
            m = d.one("SELECT * FROM memberships WHERE user_id = ? AND class_id = ? AND role = 'student'", f.get("user_id"), cid)
            t = d.one("SELECT * FROM teams WHERE id = ? AND class_id = ?", f.get("team_id"), cid)
            if m and t:
                d.update("memberships", m["id"], team_id=t["id"])
                ok("Student moved.")
        elif act == "tray":
            t = d.one("SELECT * FROM teams WHERE id = ? AND class_id = ?", f.get("team_id"), cid)
            tray = d.one("SELECT * FROM trays WHERE id = ? AND kit_id = ?", f.get("tray_id"), cls["kit_id"]) if f.get("tray_id") else None
            if t:
                d.update("teams", t["id"], tray_id=tray["id"] if tray else None)
                ok("Tray assigned.")
        elif act == "reset_pics":
            m = d.one("SELECT * FROM memberships WHERE user_id = ? AND class_id = ? AND role = 'student'", f.get("user_id"), cid)
            if m:
                pics = secrets.SystemRandom().sample(auth.PICTURES, 2)
                d.update("users", m["user_id"], picture_hash=auth.picture_hash(pics, m["user_id"]))
                name = d.val("SELECT name FROM users WHERE id = ?", m["user_id"])
                ok(f"New pictures for {name}: {pics[0]} + {pics[1]}")
        elif act == "remove":
            m = d.one("SELECT * FROM memberships WHERE user_id = ? AND class_id = ? AND role = 'student'", f.get("user_id"), cid)
            if m:
                d.run("DELETE FROM memberships WHERE id = ?", m["id"])
                d.run("UPDATE users SET is_active = 0 WHERE id = ? AND email IS NULL", m["user_id"])
                log(d, "student.remove", m["user_id"], school_id=cls["school_id"])
                ok("Student removed from the class.")
        return redirect(url_for("teacher.teams", cid=cid))
    teams_ = d.q("SELECT t.*, tr.letter, tr.label FROM teams t LEFT JOIN trays tr ON tr.id = t.tray_id WHERE t.class_id = ? ORDER BY t.name", cid)
    students = d.q("SELECT u.id, u.name, u.last_login, m.team_id FROM memberships m JOIN users u ON u.id = m.user_id "
                   "WHERE m.class_id = ? AND m.role = 'student' ORDER BY u.name", cid)
    trays = d.q("SELECT * FROM trays WHERE kit_id = ? ORDER BY letter", cls["kit_id"]) if cls["kit_id"] else []
    return render_template("teacher/teams.html", cls=cls, teams=teams_, students=students, trays=trays)
