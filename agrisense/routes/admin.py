"""School admin / client admin / IT: overview, people and classes, kits and devices, settings, privacy, billing, audit."""
import secrets

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import auth
from ..db import ahead, jdump, jload, new_id, now
from ..rbac import ASSIGNABLE_BY, ROLES, can
from ..services import feeds as F
from ..services.audit import log
from ..services.safety import school_settings
from .util import class_code, db, err, need, ok, pick_school

bp = Blueprint("admin", __name__, url_prefix="/admin")

SOIL_DEFAULT = [("A", "sandy", "Sandy"), ("B", "loam", "Loam"), ("C", "clay", "Clay"),
                ("D", "fertilized", "Fertilized loam"), ("E", "salty", "Salty loam")]


def _school_perm(perm, school):
    need(perm, school_id=school["id"])


@bp.before_request
def _signed_in():
    if not g.user:
        return redirect(url_for("public.login", next=request.path))


ADMIN_PERMS = ("people.manage", "devices.manage", "device.health", "billing.view", "privacy.manage", "audit.view", "school.settings")


@bp.route("/")
def overview():
    school, ids = pick_school()
    if not any(auth.allowed(p, school_id=school["id"]) for p in ADMIN_PERMS):
        abort(403)
    d = db()
    sid = school["id"]
    stats = {
        "classes": d.val("SELECT COUNT(*) AS n FROM classes WHERE school_id = ?", sid),
        "students": d.val("SELECT COUNT(*) AS n FROM memberships m JOIN classes c ON c.id = m.class_id WHERE c.school_id = ? AND m.role = 'student'", sid),
        "teachers": d.val("SELECT COUNT(DISTINCT m.user_id) AS n FROM memberships m JOIN classes c ON c.id = m.class_id WHERE c.school_id = ? AND m.role IN ('teacher','co_teacher')", sid),
        "devices": d.val("SELECT COUNT(*) AS n FROM devices WHERE school_id = ? AND status != 'retired'", sid),
        "online": d.val("SELECT COUNT(*) AS n FROM devices WHERE school_id = ? AND status = 'online'", sid),
    }
    alerts = d.q("SELECT * FROM alerts WHERE school_id = ? AND resolved_at IS NULL ORDER BY created_at DESC LIMIT 10", sid)
    kits = d.q("SELECT * FROM kits WHERE school_id = ? ORDER BY name", sid)
    classes = d.q("SELECT c.*, k.name AS kit_name FROM classes c LEFT JOIN kits k ON k.id = c.kit_id WHERE c.school_id = ? ORDER BY c.name", sid)
    schools = [d.one("SELECT id, name FROM schools WHERE id = ?", i) for i in ids]
    sub = d.one("SELECT s.*, p.name AS plan FROM subscriptions s JOIN plans p ON p.id = s.plan_id WHERE s.org_id = ? ORDER BY s.created_at DESC", school["org_id"])
    dpa = d.one("SELECT * FROM privacy_agreements WHERE org_id = ?", school["org_id"])
    steps = [("Register your kit", stats["devices"] > 0, url_for("admin.devices", school=sid)),
             ("Create a class", stats["classes"] > 0, url_for("admin.people", school=sid)),
             ("Add students", stats["students"] > 0, url_for("admin.people", school=sid)),
             ("Sign the privacy agreement", bool(dpa and dpa["status"] in ("signed", "countersigned")), url_for("admin.privacy", school=sid))]
    return render_template("admin/overview.html", school=school, schools=schools, stats=stats, alerts=alerts, kits=kits,
                           classes=classes, sub=sub, steps=steps)


# ---------------- people and classes ----------------

@bp.route("/people")
def people():
    school, ids = pick_school()
    need("people.manage", school_id=school["id"])
    d = db()
    sid = school["id"]
    classes = d.q("SELECT * FROM classes WHERE school_id = ? ORDER BY name", sid)
    staff = d.q("""SELECT u.id, u.name, u.email, u.last_login, m.role, m.id AS mid, m.class_id, m.expires_at, c.name AS class_name
                   FROM memberships m JOIN users u ON u.id = m.user_id LEFT JOIN classes c ON c.id = m.class_id
                   WHERE (m.school_id = ? OR c.school_id = ?) AND m.role != 'student' ORDER BY u.name""", sid, sid)
    students = d.q("""SELECT u.id, u.name, u.last_login, c.name AS class_name, t.name AS team FROM memberships m
                      JOIN users u ON u.id = m.user_id JOIN classes c ON c.id = m.class_id LEFT JOIN teams t ON t.id = m.team_id
                      WHERE c.school_id = ? AND m.role = 'student' ORDER BY c.name, u.name""", sid)
    kits = d.q("SELECT * FROM kits WHERE school_id = ?", sid)
    mine = {m["role"] for m in g.memberships}
    assignable = sorted({r for role in mine for r in ASSIGNABLE_BY.get(role, set())} - {"student", "owner", "ops", "support", "finance", "content", "sales"})
    return render_template("admin/people.html", school=school, classes=classes, staff=staff, students=students, kits=kits,
                           assignable=assignable)


@bp.route("/classes", methods=["POST"])
def add_class():
    school, _ = pick_school()
    need("classes.manage", school_id=school["id"])
    f = request.form
    if not f.get("name"):
        err("Give the class a name, e.g. Period 3 Ag Science.")
        return redirect(url_for("admin.people", school=school["id"]))
    d = db()
    cid = new_id("cls")
    code = class_code()
    d.insert("classes", id=cid, school_id=school["id"], name=f["name"][:120], code=code, kit_id=f.get("kit_id") or None,
             sim_enabled=0 if f.get("kit_id") else 1, sim_started_at=now(), sim_speed=60, pump_requests_allowed=1, created_at=now())
    teams = max(1, min(10, int(f.get("teams") or 5)))
    trays = d.q("SELECT * FROM trays WHERE kit_id = ? ORDER BY letter", f.get("kit_id")) if f.get("kit_id") else []
    prefix = code.lower()
    for i in range(teams):
        d.insert("teams", id=new_id("tm"), class_id=cid, name=f"Team {i + 1}", slug=f"{prefix}-team-{i + 1}",
                 tray_id=trays[i % len(trays)]["id"] if trays else None)
    if f.get("teacher_email"):
        u = d.one("SELECT * FROM users WHERE email = ?", f["teacher_email"].lower().strip())
        if u:
            auth.add_membership(d, u["id"], "teacher", class_id=cid)
    log(d, "class.create", f["name"], school_id=school["id"])
    ok(f"Class created. Class code: {code}")
    return redirect(url_for("admin.people", school=school["id"]))


@bp.route("/staff", methods=["POST"])
def add_staff():
    """Invite an adult: creates the account with a temporary password shown once."""
    school, _ = pick_school()
    need("people.manage", school_id=school["id"])
    f = request.form
    role = f.get("role")
    if role not in ROLES or not auth.allowed("roles.assign", school_id=school["id"]) and not auth.allowed("roles.assign.class", class_id=f.get("class_id")):
        abort(403)
    if not any(role in ASSIGNABLE_BY.get(m["role"], set()) for m in g.memberships):
        abort(403)
    d = db()
    email = (f.get("email") or "").lower().strip()
    if "@" not in email or not f.get("name"):
        err("Enter a name and an email.")
        return redirect(url_for("admin.people", school=school["id"]))
    u = d.one("SELECT * FROM users WHERE email = ?", email)
    temp = None
    if not u:
        temp = secrets.token_urlsafe(9)
        uid = auth.create_user(d, f["name"][:120], email, temp, must_change=True)
    else:
        uid = u["id"]
    expires = ahead(days=int(f.get("days") or 7)) if role in ("substitute", "observer") else None
    class_roles = ("teacher", "co_teacher", "substitute", "observer")
    if role in class_roles:
        if not f.get("class_id") or d.val("SELECT school_id FROM classes WHERE id = ?", f["class_id"]) != school["id"]:
            err("Choose the class for this role.")
            return redirect(url_for("admin.people", school=school["id"]))
        auth.add_membership(d, uid, role, class_id=f["class_id"], expires_at=expires)
    elif role in ("client_admin", "billing", "privacy"):
        auth.add_membership(d, uid, role, org_id=school["org_id"])
    else:
        auth.add_membership(d, uid, role, school_id=school["id"])
    log(d, "role.grant", f"{email} -> {role}", school_id=school["id"])
    ok(f"{f['name']} added as {ROLES[role]}." + (f" Temporary password (shown once): {temp}" if temp else ""))
    return redirect(url_for("admin.people", school=school["id"]))


@bp.route("/membership/<mid>/remove", methods=["POST"])
def remove_membership(mid):
    d = db()
    m = d.one("SELECT * FROM memberships WHERE id = ?", mid)
    if not m:
        abort(404)
    school, _ = pick_school()
    m_school = m["school_id"] or (d.val("SELECT school_id FROM classes WHERE id = ?", m["class_id"]) if m["class_id"] else None)
    if m_school != school["id"]:
        abort(403)
    need("people.manage", school_id=school["id"])
    if m["user_id"] == g.user["id"]:
        err("You can't remove your own role.")
        return redirect(url_for("admin.people", school=school["id"]))
    d.run("DELETE FROM memberships WHERE id = ?", mid)
    log(d, "role.revoke", f"{m['role']} for {m['user_id']}", school_id=school["id"])
    ok("Role removed.")
    return redirect(url_for("admin.people", school=school["id"]))


# ---------------- kits and devices ----------------

@bp.route("/devices")
def devices():
    school, _ = pick_school()
    if not (auth.allowed("devices.manage", school_id=school["id"]) or auth.allowed("device.health", school_id=school["id"])):
        abort(403)
    d = db()
    kits = d.q("SELECT * FROM kits WHERE school_id = ? ORDER BY name", school["id"])
    for k in kits:
        k["trays"] = d.q("SELECT * FROM trays WHERE kit_id = ? ORDER BY letter", k["id"])
    devs = d.q("""SELECT dv.*, k.name AS kit_name, t.letter AS tray_letter, tm.name AS team_name, c.name AS class_name
                  FROM devices dv LEFT JOIN kits k ON k.id = dv.kit_id LEFT JOIN trays t ON t.id = dv.tray_id
                  LEFT JOIN teams tm ON tm.id = dv.team_id LEFT JOIN classes c ON c.id = tm.class_id
                  WHERE dv.school_id = ? ORDER BY dv.kind, dv.serial""", school["id"])
    teams = d.q("SELECT tm.id, tm.name, c.name AS class_name FROM teams tm JOIN classes c ON c.id = tm.class_id WHERE c.school_id = ? ORDER BY c.name, tm.name", school["id"])
    return render_template("admin/devices.html", school=school, kits=kits, devices=devs, teams=teams,
                           components=F.TRAINER_COMPONENTS)


@bp.route("/kits", methods=["POST"])
def add_kit():
    school, _ = pick_school()
    need("devices.manage", school_id=school["id"])
    d = db()
    kid = new_id("kit")
    d.insert("kits", id=kid, school_id=school["id"], name=(request.form.get("name") or "Soil bench")[:80], created_at=now())
    for letter, soil, label in SOIL_DEFAULT:
        d.insert("trays", id=new_id("tr"), kit_id=kid, letter=letter, soil=soil, label=label)
    log(d, "kit.create", request.form.get("name", ""), school_id=school["id"])
    ok("Kit added with trays A–E. Now claim its gateway and nodes.")
    return redirect(url_for("admin.devices", school=school["id"]))


@bp.route("/devices/claim", methods=["POST"])
def claim():
    """Register hardware: serial + claim code from the QR label moves the device from AgriSense inventory to this school."""
    school, _ = pick_school()
    need("devices.manage", school_id=school["id"])
    d = db()
    serial = (request.form.get("serial") or "").upper().strip()
    code = (request.form.get("claim_code") or "").upper().strip()
    dev = d.one("SELECT * FROM devices WHERE serial = ?", serial)
    if not dev or dev["claim_code"] != code:
        err("That serial and claim code don't match. Check the label on the device.")
        return redirect(url_for("admin.devices", school=school["id"]))
    if dev["school_id"] and dev["school_id"] != school["id"]:
        err("That device is registered to another school. Contact AgriSense support to transfer it.")
        return redirect(url_for("admin.devices", school=school["id"]))
    d.update("devices", dev["id"], school_id=school["id"], status="offline", claimed_at=now(),
             kit_id=request.form.get("kit_id") or None, name=request.form.get("name") or serial)
    log(d, "device.claim", serial, school_id=school["id"])
    ok(f"{serial} registered. Power it on; it shows Online after its first report.")
    return redirect(url_for("admin.devices", school=school["id"]))


@bp.route("/devices/<dev_id>", methods=["POST"])
def update_device(dev_id):
    school, _ = pick_school()
    d = db()
    dev = d.one("SELECT * FROM devices WHERE id = ? AND school_id = ?", dev_id, school["id"])
    if not dev:
        abort(404)
    f = request.form
    act = f.get("do")
    if act == "assign":
        if not (auth.allowed("devices.manage", school_id=school["id"]) or auth.allowed("devices.assign_tray", school_id=school["id"])):
            abort(403)
        tray = f.get("tray_id") or None
        if tray and d.one("SELECT id FROM devices WHERE tray_id = ? AND id != ? AND status != 'retired'", tray, dev_id):
            err("Another node already reads that tray. Unassign it first.")
            return redirect(url_for("admin.devices", school=school["id"]))
        kit = d.val("SELECT kit_id FROM trays WHERE id = ?", tray) if tray else (f.get("kit_id") or dev["kit_id"])
        d.update("devices", dev_id, tray_id=tray, kit_id=kit, team_id=f.get("team_id") or None)
        ok("Assignment saved.")
    elif act == "components":
        need("devices.manage", school_id=school["id"])
        comps = [c for c in f.getlist("components") if c in F.TRAINER_COMPONENTS]
        cfg = jload(dev["config"], {}) or {}
        cfg["components"] = comps
        d.update("devices", dev_id, config=jdump(cfg))
        ok("Trainer components saved.")
    elif act == "restart":
        if not (auth.allowed("devices.manage", school_id=school["id"]) or auth.allowed("device.restart", school_id=school["id"])):
            abort(403)
        d.insert("commands", device_id=dev_id, command="RESTART", created_by=g.user["id"], created_at=now(), expires_at=ahead(minutes=10))
        ok("Restart sent. The device picks it up on its next check-in.")
    elif act == "retire":
        need("devices.manage", school_id=school["id"])
        d.update("devices", dev_id, status="retired", tray_id=None, team_id=None)
        ok("Device retired. Its data stays in your records.")
    log(d, f"device.{act}", dev["serial"], school_id=school["id"])
    return redirect(url_for("admin.devices", school=school["id"]))


@bp.route("/trays/<tray_id>", methods=["POST"])
def update_tray(tray_id):
    school, _ = pick_school()
    need("devices.manage", school_id=school["id"])
    d = db()
    tray = d.one("SELECT t.* FROM trays t JOIN kits k ON k.id = t.kit_id WHERE t.id = ? AND k.school_id = ?", tray_id, school["id"])
    if not tray:
        abort(404)
    soil = request.form.get("soil")
    from ..services.simulate import SOILS
    if soil in SOILS:
        d.update("trays", tray_id, soil=soil, label=(request.form.get("label") or soil.title())[:40])
        ok(f"Tray {tray['letter']} saved.")
    return redirect(url_for("admin.devices", school=school["id"]))


# ---------------- settings, privacy, billing, audit ----------------

@bp.route("/settings", methods=["GET", "POST"])
def settings():
    school, _ = pick_school()
    need("school.settings", school_id=school["id"])
    d = db()
    s = school_settings(d, school["id"])
    if request.method == "POST":
        f = request.form
        try:
            s["pump_max_seconds"] = max(5, min(300, int(f.get("pump_max_seconds") or 300)))
            s["retention_days"] = max(30, min(3650, int(f.get("retention_days") or 365)))
        except ValueError:
            err("Use whole numbers.")
            return redirect(url_for("admin.settings", school=school["id"]))
        s["class_hours_only"] = f.get("class_hours_only") == "1"
        s["class_hours"] = [f.get("hours_from") or "07:00", f.get("hours_to") or "16:30"]
        s["student_signin"] = f.get("student_signin") or "pictures"
        s["parents_enabled"] = f.get("parents_enabled") == "1"
        s["units"] = f.get("units") or "metric"
        d.update("schools", school["id"], settings=jdump(s), timezone=f.get("timezone") or school["timezone"])
        log(d, "school.settings", jdump(s), school_id=school["id"])
        ok("Settings saved.")
        return redirect(url_for("admin.settings", school=school["id"]))
    s.setdefault("retention_days", 365)
    return render_template("admin/settings.html", school=school, s=s)


@bp.route("/privacy", methods=["GET", "POST"])
def privacy():
    school, _ = pick_school()
    d = db()
    if not (auth.allowed("privacy.manage", school_id=school["id"]) or auth.allowed("privacy.request", school_id=school["id"])):
        abort(403)
    dpa = d.one("SELECT * FROM privacy_agreements WHERE org_id = ?", school["org_id"])
    if request.method == "POST":
        if request.form.get("do") == "sign":
            need("privacy.manage", school_id=school["id"])
            if not dpa:
                d.insert("privacy_agreements", id=new_id("dpa"), org_id=school["org_id"], version="2026.1", status="signed",
                         signed_by=g.user["name"], signed_at=now())
            else:
                d.update("privacy_agreements", dpa["id"], status="signed", signed_by=g.user["name"], signed_at=now())
            log(d, "privacy.sign", "DPA 2026.1", school_id=school["id"])
            ok("Agreement signed. AgriSense Hub will countersign and email a copy.")
        elif request.form.get("do") == "support":
            need("privacy.manage", school_id=school["id"]) if not auth.allowed("people.manage", school_id=school["id"]) else None
            d.insert("support_access", id=new_id("sa"), school_id=school["id"], ticket=(request.form.get("ticket") or "")[:40],
                     granted_by=g.user["id"], expires_at=ahead(hours=int(request.form.get("hours") or 24)), created_at=now())
            log(d, "support.grant", request.form.get("ticket", ""), school_id=school["id"])
            ok("Support can see your school for the time you chose. You can end it any time.")
        elif request.form.get("do") == "end_support":
            d.run("UPDATE support_access SET expires_at = ? WHERE school_id = ? AND expires_at > ?", now(), school["id"], now())
            ok("Support access ended.")
        return redirect(url_for("admin.privacy", school=school["id"]))
    grants = d.q("SELECT * FROM support_access WHERE school_id = ? ORDER BY created_at DESC LIMIT 10", school["id"])
    return render_template("admin/privacy.html", school=school, dpa=dpa, grants=grants, nowts=now())


@bp.route("/billing", methods=["GET", "POST"])
def billing():
    school, _ = pick_school()
    if not auth.allowed("billing.view", school_id=school["id"]):
        abort(403)
    d = db()
    if request.method == "POST":
        need("billing.manage", school_id=school["id"])
        inv = d.one("SELECT * FROM invoices WHERE id = ? AND org_id = ?", request.form.get("invoice_id"), school["org_id"])
        if inv and request.form.get("do") == "po":
            po = (request.form.get("po_number") or "").strip()[:40]
            if not po:
                err("Enter the purchase order number.")
            else:
                d.update("invoices", inv["id"], po_number=po, status="accepted" if inv["kind"] == "quote" else inv["status"])
                log(d, "billing.po", f"{inv['number']} PO {po}", school_id=school["id"])
                ok("PO recorded. Our finance team will invoice against it.")
        return redirect(url_for("admin.billing", school=school["id"]))
    sub = d.one("SELECT s.*, p.name AS plan, p.price_cents FROM subscriptions s JOIN plans p ON p.id = s.plan_id WHERE s.org_id = ? ORDER BY s.created_at DESC", school["org_id"])
    invoices = d.q("SELECT * FROM invoices WHERE org_id = ? ORDER BY created_at DESC", school["org_id"])
    plans = d.q("SELECT * FROM plans ORDER BY COALESCE(price_cents, 99999999)")
    return render_template("admin/billing.html", school=school, sub=sub, invoices=invoices, plans=plans)


@bp.route("/audit")
def audit():
    school, _ = pick_school()
    if not (auth.allowed("audit.view", school_id=school["id"]) or auth.allowed("audit.devices", school_id=school["id"])):
        abort(403)
    rows = db().q("SELECT a.*, u.name AS who FROM audit_log a LEFT JOIN users u ON u.id = a.user_id WHERE a.school_id = ? ORDER BY a.id DESC LIMIT 300", school["id"])
    if not auth.allowed("audit.view", school_id=school["id"]):
        rows = [r for r in rows if r["action"].startswith("device.")]
    return render_template("admin/audit.html", school=school, rows=rows)


@bp.route("/students", methods=["POST"])
def add_students():
    """Paste a list of names (one per line); each gets a random two-picture password, printed on cards."""
    d = db()
    cls = d.one("SELECT * FROM classes WHERE id = ?", request.form.get("class_id"))
    if not cls:
        abort(404)
    if not (auth.allowed("people.manage", class_id=cls["id"])):
        abort(403)
    names = [n.strip()[:60] for n in (request.form.get("names") or "").splitlines() if n.strip()][:60]
    teams = d.q("SELECT * FROM teams WHERE class_id = ? ORDER BY name", cls["id"])
    cards = []
    count = d.val("SELECT COUNT(*) AS n FROM memberships WHERE class_id = ? AND role = 'student'", cls["id"])
    for i, nm in enumerate(names):
        parts = nm.split()
        short = parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")    # first name + last initial only
        uid = auth.create_user(d, short)
        pics = secrets.SystemRandom().sample(auth.PICTURES, 2)
        d.update("users", uid, picture_hash=auth.picture_hash(pics, uid))
        team = teams[(count + i) % len(teams)] if teams else None
        auth.add_membership(d, uid, "student", class_id=cls["id"], team_id=team["id"] if team else None)
        cards.append({"name": short, "pics": pics, "team": team["name"] if team else ""})
    log(d, "students.add", f"{len(cards)} to {cls['name']}", school_id=cls["school_id"])
    return render_template("admin/cards.html", cls=cls, cards=cards)
