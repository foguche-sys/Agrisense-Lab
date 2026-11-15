"""Public site and sign-in: landing, plans, quote request, pilot sign-up, staff sign-in, student picture sign-in, school sign-up."""
from flask import Blueprint, g, redirect, render_template, request, session, url_for

from .. import auth
from ..db import jdump, new_id, now
from ..rbac import home_for
from ..services import kits as K
from ..services import privacy as PRIV
from .util import db, err, ok

bp = Blueprint("public", __name__)


@bp.route("/")
def landing():
    plans = db().q("SELECT * FROM plans ORDER BY COALESCE(price_cents, 99999999)")
    lessons = db().q("SELECT * FROM lessons ORDER BY code")
    return render_template("public/landing.html", plans=plans, lessons=lessons)


@bp.route("/kits")
def kits():
    """Kits and pricing: the options, what the school provides, how to buy (quote -> PO -> invoice), FAQ."""
    return render_template("public/kits.html", K=K, video="Video3_Power_Up_Safety_Checks")


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
            return render_template("public/quote.html", form=f, quote_choices=K.QUOTE_CHOICES)
        try:
            kits = max(1, int(f.get("kits") or 1))
        except ValueError:
            kits = 1
        db().insert("leads", id=new_id("ld"), name=f.get("name", "")[:120], email=f["email"][:200].lower(),
                    school=f.get("school", "")[:200], state=f.get("state", "")[:40], plan=f.get("plan") if f.get("plan") in K.QUOTE_CODES else "starter",
                    kits=kits, created_at=now())
        return render_template("public/quote.html", sent=True, form={}, quote_choices=K.QUOTE_CHOICES)
    return render_template("public/quote.html", form={"plan": request.args.get("plan", "starter")}, quote_choices=K.QUOTE_CHOICES)


PILOT_ROLES = ["Agriculture teacher", "Science teacher", "Computer science teacher", "CTE director", "School or district leader", "Other"]
PILOT_INTEREST = ["Starter", "Starter + Field add-on", "Virtual only", "Not sure yet"]
PILOT_TERMS = ["Fall 2027", "Spring 2028", "Later"]
PILOT_SITES = ["Greenhouse", "School garden or FFA plot", "Classroom only"]


@bp.route("/pilot", methods=["GET", "POST"])
def pilot():
    """Teacher sign-up for the fall 2027 pilot. Saves contact details only; staff see them in the console."""
    if request.method == "POST":
        f = request.form
        if f.get("website"):                     # hidden field: only bots fill it in
            return render_template("public/pilot.html", sent=True, form={}, **_pilot_lists())
        ip = "pilot:" + (request.remote_addr or "?")
        if auth.throttle(ip, limit=5, window=3600):
            err("Too many sign-ups from this network. Try again in an hour, or email us.")
            return render_template("public/pilot.html", form=f, **_pilot_lists()), 429
        email = (f.get("email") or "").strip().lower()
        if not f.get("name", "").strip() or not f.get("school", "").strip() or "@" not in email or "." not in email.split("@")[-1]:
            err("Please fill in your name, your school and a working email.")
            return render_template("public/pilot.html", form=f, **_pilot_lists()), 400
        try:
            students = max(0, min(5000, int(f.get("students") or 0))) or None
        except ValueError:
            students = None
        pick = lambda key, allowed: f.get(key) if f.get(key) in allowed else None
        db().insert("pilot_signups", id=new_id("pl"), name=f["name"].strip()[:120], email=email[:200],
                    phone=(f.get("phone") or "").strip()[:40], school=f["school"].strip()[:200],
                    district=(f.get("district") or "").strip()[:200], county=(f.get("county") or "").strip()[:80],
                    role=pick("role", PILOT_ROLES), students=students, interest=pick("interest", PILOT_INTEREST),
                    start_term=pick("start_term", PILOT_TERMS), site=pick("site", PILOT_SITES),
                    notes=(f.get("notes") or "").strip()[:1000], created_at=now())
        auth.failed_attempt(ip)                  # counts sign-ups per network for the limit above
        return render_template("public/pilot.html", sent=True, form={}, **_pilot_lists())
    return render_template("public/pilot.html", form={}, **_pilot_lists())


def _pilot_lists():
    return {"roles": PILOT_ROLES, "interests": PILOT_INTEREST, "terms": PILOT_TERMS, "sites": PILOT_SITES}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if auth.throttle(request.remote_addr or "?", limit=20):
            err("Too many tries. Wait 5 minutes and try again.")
            return render_template("public/login.html"), 429
        u, why = auth.check_staff_login(request.form.get("email"), request.form.get("password"))
        if not u:
            auth.failed_attempt(request.remote_addr or "?")
            err("Too many wrong tries for this account. Wait 15 minutes, or ask your school admin." if why == "locked"
                else "That email and password don't match.")
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
        if auth.throttle(request.remote_addr or "?", limit=60):       # a whole class shares one school address
            err("Too many tries. Ask your teacher.")
            return render_template("public/student_code.html", code=code), 429
        pics = request.form.get("pics").split(",")
        u, why = auth.check_student_login(code, uid, pics)
        if why == "locked":
            err("Too many wrong pictures. Ask your teacher to unlock you.")
            return render_template("public/student_code.html", code=code), 423
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
        d.insert("privacy_agreements", id=new_id("dpa"), org_id=org, version=PRIV.DPA_VERSION, status="not_started")
        u = d.one("SELECT * FROM users WHERE id = ?", uid)
        auth.login_user(u)
        ok("Your school is ready. Next: register your kit and create a class.")
        return redirect(url_for("admin.overview"))
    return render_template("public/signup.html", form={})


@bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html", schedule=PRIV.DATA_SCHEDULE, retention=PRIV.RETENTION, version=PRIV.DPA_VERSION)


@bp.route("/standards")
def standards():
    """Public standards alignment: NGSS, CSTA and AFNR for every lesson, for purchasing and curriculum reviews."""
    from ..services import standards as S
    lessons = db().q("SELECT code, title, duration FROM lessons ORDER BY code")
    return render_template("public/standards.html", S=S, lessons=lessons, cov=S.coverage())


@bp.route("/privacy/agreement")
def agreement():
    """The key terms of the Student Data Privacy Agreement, for districts to read before signing."""
    return render_template("public/agreement.html", schedule=PRIV.DATA_SCHEDULE, retention=PRIV.RETENTION, version=PRIV.DPA_VERSION)


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
