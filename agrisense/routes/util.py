"""Small helpers shared by the page blueprints."""
import secrets
import string

from flask import abort, flash, g, redirect, request, url_for

from ..db import get_db
from ..rbac import can, classes_for, schools_for


def db():
    return get_db()


def need(perm, **scope):
    if not g.user:
        abort(401)
    if not can(get_db(), g.memberships, perm, **scope):
        abort(403)


def back(default="public.landing", **kw):
    return redirect(request.referrer or url_for(default, **kw))


def ok(msg):
    flash(msg, "ok")


def err(msg):
    flash(msg, "err")


def class_code():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        c = "".join(secrets.choice(alphabet) for _ in range(6))
        if not get_db().val("SELECT id FROM classes WHERE code = ?", c):
            return c


def claim_code():
    return "-".join("".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)) for _ in range(2))


def pick_school():
    """The school an admin page works on: ?school= if allowed, else the first one they have."""
    ids = schools_for(get_db(), g.memberships)
    if not ids:
        abort(403)
    sid = request.args.get("school") or request.form.get("school_id")
    if sid and sid in ids:
        return get_db().one("SELECT * FROM schools WHERE id = ?", sid), ids
    return get_db().one("SELECT * FROM schools WHERE id = ?", ids[0]), ids


def pick_class():
    ids = classes_for(get_db(), g.memberships)
    if not ids:
        return None, []
    cid = request.args.get("class") or request.form.get("class_id")
    cid = cid if cid in ids else ids[0]
    return get_db().one("SELECT * FROM classes WHERE id = ?", cid), ids


def student_team():
    """The (class, team) a signed-in student belongs to."""
    for m in g.memberships:
        if m["role"] == "student" and m["team_id"]:
            d = get_db()
            return d.one("SELECT * FROM classes WHERE id = ?", m["class_id"]), d.one("SELECT * FROM teams WHERE id = ?", m["team_id"])
    return None, None
