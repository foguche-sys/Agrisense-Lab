"""Student: my team's tray, request water, observations, lab journal (claim-evidence-reasoning); parent view."""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from ..db import jdump, jload, new_id, now
from ..services import safety
from ..services.live import tray_now
from .util import db, err, ok, student_team

bp = Blueprint("student", __name__, url_prefix="/me")


@bp.before_request
def _signed_in():
    if not g.user:
        return redirect(url_for("public.student_code"))


@bp.route("/")
def home():
    cls, team = student_team()
    if not team:
        if any(m["role"] == "parent" for m in g.memberships):
            return redirect(url_for("student.parent"))
        abort(403)
    d = db()
    tray = d.one("SELECT * FROM trays WHERE id = ?", team["tray_id"]) if team["tray_id"] else None
    reading = tray_now(d, cls, tray) if tray else None
    mates = d.q("SELECT u.name FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.team_id = ? AND m.role = 'student' ORDER BY u.name", team["id"])
    assigns = d.q("SELECT a.*, l.code, l.title, l.summary, l.equipment, j.status AS jstatus, j.score FROM assignments a "
                  "JOIN lessons l ON l.id = a.lesson_id LEFT JOIN journals j ON j.assignment_id = a.id AND j.team_id = ? "
                  "WHERE a.class_id = ? ORDER BY l.code", team["id"], cls["id"])
    return render_template("student/home.html", cls=cls, team=team, tray=tray, reading=reading, mates=mates, assigns=assigns)


@bp.route("/tray", methods=["GET", "POST"])
def tray():
    cls, team = student_team()
    if not team or not team["tray_id"]:
        abort(403)
    d = db()
    tr = d.one("SELECT * FROM trays WHERE id = ?", team["tray_id"])
    if request.method == "POST":
        act = request.form.get("do")
        if act == "water":
            reading = tray_now(d, cls, tr)
            try:
                safety.request_bench(d, g.user, g.memberships, cls, tr, request.form.get("seconds"), request.form.get("reason"),
                                     team_id=team["id"], moisture=reading.get("moisture") if reading else None)
                ok("Request sent to your teacher.")
            except safety.SafetyError as e:
                err(str(e))
        elif act == "observe":
            what = (request.form.get("what") or "").strip()
            if what:
                d.insert("observations", id=new_id("ob"), tray_id=tr["id"], team_id=team["id"], user_id=g.user["id"], what=what[:80],
                         amount=(request.form.get("amount") or "")[:40], note=(request.form.get("note") or "")[:500], created_at=now())
                ok("Observation saved.")
        return redirect(url_for("student.tray"))
    reading = tray_now(d, cls, tr)
    reqs = d.q("SELECT * FROM pump_requests WHERE team_id = ? ORDER BY created_at DESC LIMIT 6", team["id"])
    obs = d.q("SELECT o.*, u.name FROM observations o JOIN users u ON u.id = o.user_id WHERE o.team_id = ? ORDER BY o.created_at DESC LIMIT 12", team["id"])
    limit = min(safety.school_settings(d, cls["school_id"])["pump_max_seconds"], safety.KIT_MAX_SECONDS)
    return render_template("student/tray.html", cls=cls, team=team, tray=tr, reading=reading, reqs=reqs, obs=obs, limit=limit)


@bp.route("/journal/<aid>", methods=["GET", "POST"])
def journal(aid):
    cls, team = student_team()
    if not team:
        abort(403)
    d = db()
    a = d.one("SELECT a.*, l.code, l.title, l.summary, l.parts FROM assignments a JOIN lessons l ON l.id = a.lesson_id WHERE a.id = ? AND a.class_id = ?", aid, cls["id"])
    if not a:
        abort(404)
    j = d.one("SELECT * FROM journals WHERE assignment_id = ? AND team_id = ?", aid, team["id"])
    if not j:
        jid = new_id("jr")
        d.insert("journals", id=jid, assignment_id=aid, team_id=team["id"], data_table="[]", status="draft", updated_at=now())
        j = d.one("SELECT * FROM journals WHERE id = ?", jid)
    if request.method == "POST":
        if j["status"] == "graded":
            err("This journal has been graded. Ask your teacher to return it if you need to change it.")
            return redirect(url_for("student.journal", aid=aid))
        f = request.form
        rows = []
        for t, m, note in zip(f.getlist("row_time"), f.getlist("row_value"), f.getlist("row_note")):
            if t or m or note:
                rows.append({"time": t[:20], "value": m[:20], "note": note[:120]})
        status = "submitted" if f.get("do") == "submit" else "draft"
        d.update("journals", j["id"], claim=f.get("claim", "")[:3000], evidence=f.get("evidence", "")[:3000],
                 reasoning=f.get("reasoning", "")[:3000], data_table=jdump(rows[:60]), status=status, updated_at=now())
        ok("Submitted to your teacher." if status == "submitted" else "Draft saved.")
        return redirect(url_for("student.journal", aid=aid))
    tray = d.one("SELECT * FROM trays WHERE id = ?", team["tray_id"]) if team["tray_id"] else None
    return render_template("student/journal.html", cls=cls, team=team, a=a, j=j, rows=jload(j["data_table"], []),
                           parts=jload(a["parts"], []), tray=tray)


@bp.route("/parent")
def parent():
    d = db()
    kids = []
    for m in g.memberships:
        if m["role"] == "parent" and m["child_user_id"]:
            child = d.one("SELECT id, name FROM users WHERE id = ?", m["child_user_id"])
            sm = d.one("SELECT * FROM memberships WHERE user_id = ? AND role = 'student'", m["child_user_id"])
            if not child or not sm:
                continue
            cls = d.one("SELECT * FROM classes WHERE id = ?", sm["class_id"])
            team = d.one("SELECT * FROM teams WHERE id = ?", sm["team_id"]) if sm["team_id"] else None
            work = d.q("SELECT l.code, l.title, j.status, j.score, a.points FROM assignments a JOIN lessons l ON l.id = a.lesson_id "
                       "LEFT JOIN journals j ON j.assignment_id = a.id AND j.team_id = ? WHERE a.class_id = ? ORDER BY l.code",
                       team["id"] if team else "", cls["id"])
            kids.append({"child": child, "cls": cls, "team": team, "work": work})
    if not kids:
        abort(403)
    return render_template("student/parent.html", kids=kids)
