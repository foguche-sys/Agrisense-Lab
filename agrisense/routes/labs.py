"""Student lab instructions and printable lab sheets, one per lesson."""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from ..rbac import PLATFORM_ROLES
from ..services.lab_content import LABS
from ..services.teacher_guides import GUIDES
from ..services.training import is_teacherish
from .util import db, student_team

bp = Blueprint("labs", __name__, url_prefix="/labs")

TOOLS = {  # where the work happens for each lab: (endpoint, label)
    "1.1": ("student.tray", "Open our tray"), "1.2": ("student.tray", "Open our tray"), "1.3": ("studio.dashboards", "Open the Field Studio"),
    "1.4": ("student.tray", "Open our tray"), "1.5": ("student.tray", "Open our tray"), "1.6": ("student.tray", "Open our tray"),
    "1.7": ("data.explorer", "Open the data"), "1.8": ("studio.dashboards", "Open the Field Studio"), "1.9": ("studio.dashboards", "Open the Field Studio"),
    "1.10": ("student.tray", "Open our tray"), "1.11": ("data.explorer", "Open the data"),
    "2.1": ("ai.predict", "Open AI Lab 2.1"), "2.2": ("ai.leaf", "Open AI Lab 2.2"), "2.3": ("ai.sensor", "Open AI Lab 2.3"),
    "2.4": ("ai.zones", "Open AI Lab 2.4"), "2.5": ("ai.decide", "Open AI Lab 2.5"),
    "3.1": ("studio.dashboards", "Open the Field Studio"), "3.2": ("studio.dashboards", "Open the Field Studio"),
    "3.3": ("studio.dashboards", "Open the Field Studio"), "3.4": ("studio.dashboards", "Open the Field Studio"),
    "3.5": ("studio.dashboards", "Open the Field Studio"), "3.6": ("studio.dashboards", "Open the Field Studio"),
    "4.1": ("data.explorer", "Open the data"), "4.2": ("student.tray", "Open our tray"), "4.3": ("ai.zones", "Open AI Lab zones"),
    "4.4": ("data.explorer", "Open the data"),
}


@bp.before_request
def _signed_in():
    if not g.user:
        return redirect(url_for("public.login", next=request.path))


def _load(code):
    d = db()
    lesson = d.one("SELECT * FROM lessons WHERE code = ?", code)
    content = LABS.get(code)
    if not lesson or not content:
        abort(404)
    cls, team = student_team()
    assignment = None
    if team:
        assignment = d.one("SELECT * FROM assignments WHERE class_id = ? AND lesson_id = ?", cls["id"], lesson["id"])
    return lesson, content, cls, team, assignment


@bp.route("/<code>")
def lab(code):
    lesson, c, cls, team, assignment = _load(code)
    tool = TOOLS.get(code)
    if tool and tool[0].startswith("student.") and not team:
        tool = None
    return render_template("labs/lab.html", lesson=lesson, c=c, team=team, assignment=assignment, tool=tool, teacher=is_teacher())


@bp.route("/<code>/sheet")
def sheet(code):
    lesson, c, cls, team, assignment = _load(code)
    return render_template("labs/sheet.html", lesson=lesson, c=c, team=team, cls=cls)


def is_teacher():
    """Teachers, school admins and AgriSense staff. Students (and parents, observers) never see teacher guides."""
    return is_teacherish(g.memberships) or any(m["role"] in PLATFORM_ROLES for m in g.memberships)


@bp.route("/<code>/guide")
def guide(code):
    """Teacher guide: set-up, timing, expected results, answers, troubleshooting. Teachers only."""
    if not is_teacher():
        abort(403)
    d = db()
    lesson = d.one("SELECT * FROM lessons WHERE code = ?", code)
    if not lesson or code not in GUIDES:
        abort(404)
    return render_template("labs/guide.html", lesson=lesson, c=LABS[code], t=GUIDES[code])
