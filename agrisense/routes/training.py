"""Teacher training: Level 1 self-paced modules, Level 2 workshop, Level 3 project; certificates with a public check."""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import auth
from ..services import training as T
from ..services import training_content as C
from ..services.audit import log
from .util import db, err, ok

bp = Blueprint("training", __name__, url_prefix="/training")


def _staff():
    return auth.allowed("platform.content") or auth.allowed("platform.support")


@bp.before_request
def _signed_in():
    if request.endpoint == "training.verify":
        return None
    if not g.user:
        return redirect(url_for("public.login", next=request.path))
    if not (T.is_teacherish(g.memberships) or _staff()):
        abort(403)


@bp.route("/", methods=["GET", "POST"])
def home():
    d = db()
    uid = g.user["id"]
    if request.method == "POST":
        act = request.form.get("do")
        if act == "step":
            T.toggle(d, uid, request.form.get("item", ""), request.form.get("on") == "1")
            if T.check_level1(d, uid) and not request.form.get("quiet"):
                ok("Level 1 complete. Your certificate is ready.")
        elif act == "project":
            if not T.awards(d, uid).get(2):
                err("Finish the Level 2 workshop before you send a Level 3 project.")
            elif not (request.form.get("title") or "").strip() or len((request.form.get("summary") or "").strip()) < 200:
                err("Give the project a title and a write-up of at least 200 characters.")
            else:
                T.submit_project(d, uid, request.form["title"].strip(), request.form["summary"].strip(), request.form.get("link"))
                ok("Project sent. AgriSense Hub reviews it and replies on this page.")
        nxt = request.form.get("next") or ""
        if nxt.startswith("/training/module/"):
            return redirect(nxt)
        return redirect(url_for("training.home") + (f"#{request.form.get('anchor')}" if request.form.get("anchor") else ""))
    return render_template("training/home.html", levels=T.LEVELS, prog=T.progress(d, uid), awards=T.awards(d, uid),
                           project=T.project(d, uid), staff=_staff(), ideas=C.PROJECT_IDEAS, writeup=C.PROJECT_WRITEUP,
                           rubric=C.PROJECT_RUBRIC)


@bp.route("/module/<key>")
def module(key):
    prog = T.progress(db(), g.user["id"])
    mods = prog["modules"]
    i = next((n for n, m in enumerate(mods) if m["key"] == key), None)
    if i is None or key not in C.GUIDES:
        abort(404)
    return render_template("training/module.html", m=mods[i], n=i + 1, guide=C.GUIDES[key], prog=prog,
                           prev=mods[i - 1] if i > 0 else None, nxt=mods[i + 1] if i + 1 < len(mods) else None)


@bp.route("/workshop")
def workshop():
    return render_template("training/workshop.html", agenda=C.WORKSHOP, bring=C.WORKSHOP_BRING, level=T.LEVELS[2],
                           done=T.awards(db(), g.user["id"]).get(2))


@bp.route("/certificate/<code>")
def certificate(code):
    d = db()
    a = d.one("SELECT a.*, u.name, u.email FROM pd_awards a JOIN users u ON u.id = a.user_id WHERE a.code = ?", code)
    if not a or (a["user_id"] != g.user["id"] and not _staff()):
        abort(404)
    return render_template("training/certificate.html", a=a, level=T.LEVELS[a["level"]])


@bp.route("/verify/<code>")
def verify(code):
    """Public: anyone (a principal, a district office) can check a certificate code."""
    a = db().one("SELECT a.level, a.hours, a.awarded_at, a.code, u.name FROM pd_awards a JOIN users u ON u.id = a.user_id WHERE a.code = ?",
                 code.strip().upper())
    return render_template("training/verify.html", a=a, level=T.LEVELS.get(a["level"]) if a else None, code=code)


@bp.route("/admin", methods=["GET", "POST"])
def admin():
    if not _staff():
        abort(403)
    d = db()
    if request.method == "POST":
        act = request.form.get("do")
        uid = request.form.get("user_id")
        user = d.one("SELECT * FROM users WHERE id = ?", uid) if uid else None
        if act == "workshop" and user:
            note = f"Workshop {request.form.get('date') or ''} {request.form.get('place') or ''}".strip()
            T.award(d, user["id"], 2, by=g.user["id"], note=note)
            log(d, "training.workshop", detail=f"{user['email']} {note}")
            ok(f"Level 2 recorded for {user['name']}.")
        elif act == "review":
            if T.review_project(d, request.form.get("project_id"), g.user["id"], request.form.get("approve") == "1", request.form.get("feedback")):
                ok("Project reviewed.")
        return redirect(url_for("training.admin"))
    teachers = d.q("SELECT DISTINCT u.id, u.name, u.email FROM users u JOIN memberships m ON m.user_id = u.id "
                   "WHERE m.role IN ('teacher','co_teacher','substitute','school_admin','client_admin') ORDER BY u.name")
    for t in teachers:
        t["awards"] = T.awards(d, t["id"])
        t["steps"] = len(T.done_steps(d, t["id"]))
    projects = d.q("SELECT p.*, u.name, u.email FROM pd_projects p JOIN users u ON u.id = p.user_id WHERE p.status = 'submitted' ORDER BY p.submitted_at")
    return render_template("training/admin.html", teachers=teachers, projects=projects, total=len(T.STEP_KEYS), levels=T.LEVELS)
