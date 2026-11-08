"""Public site and sign-in: landing, plans, quote request, staff sign-in, student picture sign-in, school sign-up."""
from flask import Blueprint, g, redirect, render_template, request, session, url_for

from .. import auth
from ..db import jdump, new_id, now
from ..rbac import home_for
from .util import db, err, ok

bp = Blueprint("public", __name__)


@bp.route("/")
def landing():
    plans = db().q("SELECT * FROM plans ORDER BY COALESCE(price_cents, 99999999)")
    lessons = db().q("SELECT * FROM lessons ORDER BY code")
    return render_template("public/landing.html", plans=plans, lessons=lessons)


@bp.route("/home")
@auth.login_required
def home():
    return redirect(url_for(home_for(g.memberships)))


@bp.route("/quote", methods=["GET", "POST"])
def quote():
    if request.method == "POST":
        f = request.form
        if not f.get("email") or "@" not in f.get("email", ""):
            err("Enter an email so we can send the quote.")
            return render_template("public/quote.html", form=f)
        try:
            kits = max(1, int(f.get("kits") or 1))
        except ValueError:
            kits = 1
        db().insert("leads", id=new_id("ld"), name=f.get("name", "")[:120], email=f["email"][:200].lower(),
                    school=f.get("school", "")[:200], state=f.get("state", "")[:40], plan=f.get("plan", "school"),
                    kits=kits, created_at=now())
        return render_template("public/quote.html", sent=True, form={})
    return render_template("public/quote.html", form={"plan": request.args.get("plan", "school")})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if auth.throttle(request.remote_addr or "?"):
            err("Too many tries. Wait 5 minutes and try again.")
            return render_template("public/login.html"), 429
        u = auth.check_staff_login(request.form.get("email"), request.form.get("password"))
        if not u:
            auth.failed_attempt(request.remote_addr or "?")
            err("That email and password don't match.")
            return render_template("public/login.html", email=request.form.get("email", "")), 401
        auth.login_user(u)
        nxt = request.args.get("next")
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(url_for("public.home"))
    return render_template("public/login.html")


@bp.route("/login/class", methods=["GET", "POST"])
def student_code():
    """Step 1: type the class code. Step 2: tap your name. Step 3: tap your two pictures."""
    code = (request.values.get("code") or "").upper().strip()
    cls = db().one("SELECT * FROM classes WHERE code = ?", code) if code else None
    if code and not cls:
        err("We couldn't find that class code. Check the board in your classroom.")
    if not cls:
        return render_template("public/student_code.html", code=code)
    students = db().q("SELECT u.id, u.name, t.name AS team FROM memberships m JOIN users u ON u.id = m.user_id "
                      "LEFT JOIN teams t ON t.id = m.team_id WHERE m.class_id = ? AND m.role = 'student' AND u.is_active = 1 "
                      "ORDER BY u.name", cls["id"])
    uid = request.values.get("uid")
    if uid and request.method == "POST" and request.form.get("pics"):
        if auth.throttle(request.remote_addr or "?", limit=20):
            err("Too many tries. Ask your teacher.")
            return render_template("public/student_code.html", code=code), 429
        pics = request.form.get("pics").split(",")
        u = auth.check_student_login(code, uid, pics)
        if u:
            auth.login_user(u)
            return redirect(url_for("student.home"))
        auth.failed_attempt(request.remote_addr or "?")
        err("Those aren't your pictures. Try again, or ask your teacher to reset them.")
    me = next((s for s in students if s["id"] == uid), None)
    return render_template("public/student_code.html", code=code, cls=cls, students=students, me=me, pictures=auth.PICTURES)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("public.landing"))


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    """A teacher or admin starts a school on the Pilot plan. They become the school admin and a teacher."""
    if request.method == "POST":
        f = request.form
        need = ["name", "email", "password", "school", "state"]
        if any(not f.get(k) for k in need):
            err("Fill in every field.")
            return render_template("public/signup.html", form=f)
        if len(f["password"]) < 10:
            err("Use a password of at least 10 characters.")
            return render_template("public/signup.html", form=f)
        d = db()
        if d.val("SELECT id FROM users WHERE email = ?", f["email"].lower().strip()):
            err("That email already has an account. Sign in instead.")
            return render_template("public/signup.html", form=f)
        org = new_id("org")
        d.insert("orgs", id=org, name=f["school"][:200], kind="client", client_type=f.get("client_type") or "school",
                 state=f["state"][:40], created_at=now())
        sch = new_id("sch")
        d.insert("schools", id=sch, org_id=org, name=f["school"][:200], city=f.get("city", "")[:80], state=f["state"][:40],
                 timezone=f.get("timezone") or "America/Chicago", settings=jdump({}), created_at=now())
        uid = auth.create_user(d, f["name"][:120], f["email"], f["password"])
        auth.add_membership(d, uid, "client_admin", org_id=org)
        auth.add_membership(d, uid, "school_admin", school_id=sch)
        plan = d.val("SELECT id FROM plans WHERE code = 'pilot'")
        if plan:
            d.insert("subscriptions", id=new_id("sub"), org_id=org, plan_id=plan, licences=1, status="trial", created_at=now())
        d.insert("privacy_agreements", id=new_id("dpa"), org_id=org, version="2026.1", status="not_started")
        u = d.one("SELECT * FROM users WHERE id = ?", uid)
        auth.login_user(u)
        ok("Your school is ready. Next: register your kit and create a class.")
        return redirect(url_for("admin.overview"))
    return render_template("public/signup.html", form={})


@bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html")


@bp.route("/account", methods=["GET", "POST"])
@auth.login_required
def account():
    """Change password. Adults given a temporary password are sent here until they pick their own."""
    from werkzeug.security import check_password_hash
    u = g.user
    if not u["email"]:
        return render_template("public/account.html", student=True)
    if request.method == "POST":
        f = request.form
        if not check_password_hash(u["password_hash"] or "", f.get("current", "")):
            err("Your current password isn't right.")
        elif len(f.get("new", "")) < 10:
            err("Use at least 10 characters for the new password.")
        elif f.get("new") != f.get("again"):
            err("The two new passwords don't match.")
        elif f.get("new") == f.get("current"):
            err("Pick a password different from the temporary one.")
        else:
            db().update("users", u["id"], password_hash=auth.hash_password(f["new"]), must_change_password=0)
            ok("Password changed.")
            return redirect(url_for("public.home"))
    return render_template("public/account.html", forced=bool(u["must_change_password"]))
