"""Sign-in: staff/adults by email + password, students by class code + picture password.

Sessions are signed cookies. Every POST form carries a CSRF token; JSON calls from the
pages send it in the X-CSRF header.
"""
import functools
import hashlib
import hmac
import secrets
import time

from flask import abort, current_app, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import ahead, get_db, new_id, now
from .rbac import can, load_memberships

# 16 pictures = 120 possible pairs (was 8 = 28). The first 8 keep their names, so cards already printed still work.
PICTURES = ["Corn", "Bee", "Tractor", "Rain", "Sun", "Seed", "Cow", "Leaf",
            "Apple", "Fish", "Tree", "Moon", "Star", "Carrot", "Pig", "Hen"]

# Per-account lockout, kept in the database so it works across workers and restarts:
# (wrong tries before locking, minutes locked). A teacher can unlock a student straight away.
LOCKOUT = {"student": (5, 15), "staff": (10, 15)}

_attempts = {}   # ip -> [timestamps]; simple brute-force guard (per process)


def hash_password(pw):
    return generate_password_hash(pw)


def picture_hash(pics, user_id):
    pair = "|".join(sorted(pics))
    return hmac.new(current_app.config["SECRET_KEY"].encode(), f"{user_id}:{pair}".encode(), hashlib.sha256).hexdigest()


def hash_key(key):
    return hashlib.sha256(key.encode()).hexdigest()


def new_key(prefix):
    return f"{prefix}_{secrets.token_urlsafe(18)}"


def throttle(ip, limit=10, window=300):
    """True when this address has failed to sign in more than `limit` times in `window` seconds."""
    t = time.time()
    hits = [x for x in _attempts.get(ip, []) if t - x < window]
    _attempts[ip] = hits
    return len(hits) >= limit


def failed_attempt(ip):
    _attempts.setdefault(ip, []).append(time.time())


def login_user(user):
    db = get_db()
    session.clear()
    session["uid"] = user["id"]
    session["csrf"] = secrets.token_urlsafe(24)
    session.permanent = True
    db.run("UPDATE users SET last_login = ? WHERE id = ?", now(), user["id"])


def load_user():
    g.user = None
    g.memberships = []
    g.pending = False
    uid = session.get("uid")
    if not uid:
        return
    db = get_db()
    u = db.one("SELECT * FROM users WHERE id = ? AND is_active = 1", uid)
    if not u:
        session.clear()
        return
    g.user = u
    g.memberships = load_memberships(db, uid)
    g.pending = waiting_for_approval(db, g.memberships)


def waiting_for_approval(db, memberships):
    """True when this person's school signed up on the website and AgriSense staff have not approved it yet.
    Until then they can see the public pages and their account, but no lessons, data, AI Lab or downloads."""
    from .rbac import resolve_scope
    orgs = set()
    for m in memberships:
        orgs.add(resolve_scope(db, team_id=m.get("team_id"), class_id=m.get("class_id"),
                               school_id=m.get("school_id"), org_id=m.get("org_id"))[3])
    orgs.discard(None)
    return any(db.val("SELECT approved FROM orgs WHERE id = ?", o) == 0 for o in orgs)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def check_csrf():
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and not request.path.startswith("/api/v1/"):
        sent = request.form.get("_csrf") or request.headers.get("X-CSRF")
        if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Your session expired. Reload the page and try again.")


def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("public.login", next=request.path))
        return fn(*a, **kw)
    return wrapper


def require(perm, **scope_from_view):
    """Decorator: user must hold perm. scope_from_view maps scope names to view kwargs."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if not g.user:
                return redirect(url_for("public.login", next=request.path))
            scope = {k: kw.get(v) for k, v in scope_from_view.items()}
            if not can(get_db(), g.memberships, perm, **scope):
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def allowed(perm, **scope):
    return bool(g.user) and can(get_db(), g.memberships, perm, **scope)


def create_user(db, name, email=None, password=None, must_change=False):
    uid = new_id("usr")
    db.insert("users", id=uid, email=email.lower().strip() if email else None, name=name,
              password_hash=hash_password(password) if password else None, is_active=1,
              must_change_password=1 if must_change else 0, created_at=now())
    return uid


def add_membership(db, user_id, role, org_id=None, school_id=None, class_id=None, team_id=None,
                   child_user_id=None, expires_at=None):
    mid = new_id("mem")
    db.insert("memberships", id=mid, user_id=user_id, role=role, org_id=org_id, school_id=school_id,
              class_id=class_id, team_id=team_id, child_user_id=child_user_id, expires_at=expires_at, created_at=now())
    return mid


def is_locked(u):
    return bool(u and u.get("locked_until") and u["locked_until"] > now())


def _failed(db, u, kind):
    """Count a wrong try against this account; lock it after too many."""
    limit, minutes = LOCKOUT[kind]
    n = (u.get("failed_logins") or 0) + 1
    if n >= limit:
        db.update("users", u["id"], failed_logins=0, locked_until=ahead(minutes=minutes))
        from .services.audit import log
        log(db, "signin.locked", f"{kind} account locked for {minutes} min after {n} wrong tries", user_id=u["id"])
    else:
        db.update("users", u["id"], failed_logins=n)
    db.commit()


def _cleared(db, u):
    if u.get("failed_logins") or u.get("locked_until"):
        db.update("users", u["id"], failed_logins=0, locked_until=None)


def unlock(db, user_id):
    db.update("users", user_id, failed_logins=0, locked_until=None)


def check_staff_login(email, password):
    """Returns (user, None) on success, else (None, "wrong" | "locked")."""
    db = get_db()
    u = db.one("SELECT * FROM users WHERE email = ? AND is_active = 1", (email or "").lower().strip())
    if u and is_locked(u):
        return None, "locked"
    if u and u["password_hash"] and check_password_hash(u["password_hash"], password or ""):
        _cleared(db, u)
        return u, None
    if u:
        _failed(db, u, "staff")
    return None, "wrong"


def check_student_login(class_code, user_id, pics):
    db = get_db()
    cls = db.one("SELECT * FROM classes WHERE code = ?", (class_code or "").upper().strip())
    if not cls:
        return None, "wrong"
    m = db.one("SELECT * FROM memberships WHERE user_id = ? AND class_id = ? AND role = 'student'", user_id, cls["id"])
    if not m:
        return None, "wrong"
    u = db.one("SELECT * FROM users WHERE id = ? AND is_active = 1", user_id)
    if u and is_locked(u):
        return None, "locked"
    if u and u["picture_hash"] and len(pics) == 2 and hmac.compare_digest(u["picture_hash"], picture_hash(pics, user_id)):
        _cleared(db, u)
        return u, None
    if u:
        _failed(db, u, "student")
    return None, "wrong"
