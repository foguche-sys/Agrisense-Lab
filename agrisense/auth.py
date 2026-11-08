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

from .db import get_db, new_id, now
from .rbac import can, load_memberships

PICTURES = ["Corn", "Bee", "Tractor", "Rain", "Sun", "Seed", "Cow", "Leaf"]

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


def check_staff_login(email, password):
    db = get_db()
    u = db.one("SELECT * FROM users WHERE email = ? AND is_active = 1", (email or "").lower().strip())
    if u and u["password_hash"] and check_password_hash(u["password_hash"], password or ""):
        return u
    return None


def check_student_login(class_code, user_id, pics):
    db = get_db()
    cls = db.one("SELECT * FROM classes WHERE code = ?", (class_code or "").upper().strip())
    if not cls:
        return None
    m = db.one("SELECT * FROM memberships WHERE user_id = ? AND class_id = ? AND role = 'student'", user_id, cls["id"])
    if not m:
        return None
    u = db.one("SELECT * FROM users WHERE id = ? AND is_active = 1", user_id)
    if u and u["picture_hash"] and len(pics) == 2 and hmac.compare_digest(u["picture_hash"], picture_hash(pics, user_id)):
        return u
    return None
