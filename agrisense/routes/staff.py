"""AgriSense Hub staff console: clients and schools, device inventory (make serials + keys), fleet health,
quotes and invoices, leads, staff roles. Support only sees a school while the school has granted access."""
import secrets

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for

from .. import auth
from ..db import ago, jdump, jload, new_id, now
from ..rbac import PLATFORM_ROLES, can, platform_org_id
from ..services.audit import log
from .util import claim_code, db, err, ok

bp = Blueprint("staff", __name__, url_prefix="/staff")
PREFIX = {"gateway": "GW", "node": "ND", "deck": "DK", "pump": "PM", "trainer": "TR"}


@bp.before_request
def _staff_only():
    if not g.user:
        return redirect(url_for("public.login", next=request.path))
    if not any(m["role"] in PLATFORM_ROLES and m["org_id"] == platform_org_id(db()) for m in g.memberships):
        abort(403)


def sp(perm):
    return can(db(), g.memberships, perm)


@bp.route("/")
def console():
    d = db()
    clients = d.q("""SELECT o.*, (SELECT COUNT(*) FROM schools s WHERE s.org_id = o.id) AS schools,
                     (SELECT p.name FROM subscriptions su JOIN plans p ON p.id = su.plan_id WHERE su.org_id = o.id ORDER BY su.created_at DESC LIMIT 1) AS plan,
                     (SELECT status FROM privacy_agreements pa WHERE pa.org_id = o.id LIMIT 1) AS dpa
                     FROM orgs o WHERE o.kind = 'client' ORDER BY o.name""") if (sp("platform.clients") or sp("platform.clients.view")) else []
    fleet = {k: d.val("SELECT COUNT(*) AS n FROM devices WHERE status = ?", k) for k in ("inventory", "online", "offline", "retired")}
    stale = d.q("SELECT dv.serial, dv.kind, dv.last_seen, s.name AS school FROM devices dv JOIN schools s ON s.id = dv.school_id "
                "WHERE dv.status != 'retired' AND (dv.last_seen IS NULL OR dv.last_seen < ?) ORDER BY dv.last_seen LIMIT 20", ago(hours=2)) \
        if (sp("platform.fleet") or sp("device.health")) else []
    leads = d.q("SELECT * FROM leads ORDER BY created_at DESC LIMIT 20") if (sp("platform.clients.leads") or sp("platform.clients")) else []
    invoices = d.q("SELECT i.*, o.name AS client FROM invoices i JOIN orgs o ON o.id = i.org_id ORDER BY i.created_at DESC LIMIT 30") \
        if (sp("platform.billing") or sp("platform.quotes")) else []
    grants = d.q("SELECT sa.*, s.name AS school FROM support_access sa JOIN schools s ON s.id = sa.school_id WHERE sa.expires_at > ? ORDER BY sa.expires_at", now()) \
        if sp("platform.support") else []
    staff = d.q("SELECT u.name, u.email, m.role, m.id AS mid FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.org_id = ? ORDER BY u.name",
                platform_org_id(d)) if sp("platform.staff") else []
    alive = d.q("SELECT dv.status, COUNT(*) AS n FROM devices dv GROUP BY dv.status")
    return render_template("staff/console.html", clients=clients, fleet=fleet, stale=stale, leads=leads, invoices=invoices,
                           grants=grants, staff=staff, alive=alive, roles=PLATFORM_ROLES)


@bp.route("/inventory", methods=["GET", "POST"])
def inventory():
    if not sp("platform.fleet"):
        abort(403)
    d = db()
    made = []
    if request.method == "POST":
        kind = request.form.get("kind")
        if kind not in PREFIX:
            abort(400)
        n = max(1, min(50, int(request.form.get("count") or 1)))
        for _ in range(n):
            while True:
                serial = f"{PREFIX[kind]}-{secrets.token_hex(2).upper()}"
                if not d.val("SELECT id FROM devices WHERE serial = ?", serial):
                    break
            key = auth.new_key("dev")
            cc = claim_code()
            d.insert("devices", id=new_id("dv"), serial=serial, kind=kind, claim_code=cc, key_hash=auth.hash_key(key),
                     status="inventory", config=jdump({}), created_at=now())
            made.append({"serial": serial, "kind": kind, "claim_code": cc, "key": key})
        log(d, "inventory.add", f"{n} × {kind}", org_id=platform_org_id(d))
        if request.form.get("fmt") == "csv":
            lines = ["serial,kind,claim_code,device_key"] + [f"{m['serial']},{m['kind']},{m['claim_code']},{m['key']}" for m in made]
            return Response("\n".join(lines) + "\n", mimetype="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="agrisense-labels-{now()[:10]}.csv"'})
    devs = d.q("SELECT dv.*, s.name AS school FROM devices dv LEFT JOIN schools s ON s.id = dv.school_id ORDER BY dv.created_at DESC LIMIT 300")
    return render_template("staff/inventory.html", made=made, devices=devs, kinds=PREFIX)


@bp.route("/invoices", methods=["POST"])
def invoices():
    if not (sp("platform.billing") or sp("platform.quotes")):
        abort(403)
    d = db()
    f = request.form
    act = f.get("do")
    if act == "create":
        org = d.one("SELECT * FROM orgs WHERE id = ? AND kind = 'client'", f.get("org_id"))
        if not org:
            err("Choose a client.")
            return redirect(url_for("staff.console"))
        lines = []
        for desc, qty, unit in zip(f.getlist("desc"), f.getlist("qty"), f.getlist("unit")):
            if desc.strip():
                try:
                    lines.append({"desc": desc[:120], "qty": int(qty or 1), "unit_cents": int(round(float(unit or 0) * 100))})
                except ValueError:
                    err("Check the quantity and price fields.")
                    return redirect(url_for("staff.console"))
        kind = "quote" if f.get("kind") == "quote" else "invoice"
        seq = (d.val("SELECT COUNT(*) AS n FROM invoices WHERE kind = ?", kind) or 0) + 1
        number = ("Q-" if kind == "quote" else "INV-") + f"{1000 + seq}"
        d.insert("invoices", id=new_id("in"), org_id=org["id"], number=number, kind=kind, lines=jdump(lines),
                 amount_cents=sum(l["qty"] * l["unit_cents"] for l in lines), status="sent", due_on=f.get("due_on") or None, created_at=now())
        log(d, "billing.create", number, org_id=org["id"])
        ok(f"{number} created.")
    elif act in ("paid", "void"):
        if not sp("platform.billing"):
            abort(403)
        inv = d.one("SELECT * FROM invoices WHERE id = ?", f.get("invoice_id"))
        if inv:
            d.update("invoices", inv["id"], status="paid" if act == "paid" else "void", paid_via=f.get("paid_via") or inv["paid_via"])
            log(d, f"billing.{act}", inv["number"], org_id=inv["org_id"])
            ok(f"{inv['number']} marked {act}.")
    return redirect(url_for("staff.console"))


@bp.route("/invoice/<iid>")
def invoice(iid):
    d = db()
    inv = d.one("SELECT i.*, o.name AS client FROM invoices i JOIN orgs o ON o.id = i.org_id WHERE i.id = ?", iid)
    if not inv:
        abort(404)
    if not (sp("platform.billing") or sp("platform.quotes")):
        abort(403)
    return render_template("billing/invoice.html", inv=inv, lines=jload(inv["lines"], []))


@bp.route("/staff", methods=["POST"])
def staff_roles():
    if not sp("platform.staff"):
        abort(403)
    d = db()
    f = request.form
    if f.get("do") == "remove":
        m = d.one("SELECT * FROM memberships WHERE id = ? AND org_id = ?", f.get("mid"), platform_org_id(d))
        if m and m["user_id"] != g.user["id"]:
            d.run("DELETE FROM memberships WHERE id = ?", m["id"])
            ok("Staff role removed.")
        return redirect(url_for("staff.console"))
    role = f.get("role")
    email = (f.get("email") or "").lower().strip()
    if role not in PLATFORM_ROLES or "@" not in email:
        err("Enter an email and pick a role.")
        return redirect(url_for("staff.console"))
    u = d.one("SELECT * FROM users WHERE email = ?", email)
    temp = None
    if not u:
        temp = secrets.token_urlsafe(9)
        uid = auth.create_user(d, f.get("name") or email.split("@")[0], email, temp, must_change=True)
    else:
        uid = u["id"]
    auth.add_membership(d, uid, role, org_id=platform_org_id(d))
    log(d, "staff.grant", f"{email} -> {role}", org_id=platform_org_id(d))
    ok(f"{email} is now {PLATFORM_ROLES[role]}." + (f" Temporary password (shown once): {temp}" if temp else ""))
    return redirect(url_for("staff.console"))


@bp.route("/school/<sid>")
def school(sid):
    """Support view of one school: devices and alerts only, and only while the school has granted access."""
    d = db()
    s = d.one("SELECT * FROM schools WHERE id = ?", sid)
    if not s:
        abort(404)
    granted = d.one("SELECT * FROM support_access WHERE school_id = ? AND expires_at > ?", sid, now())
    if not (sp("platform.clients") or ((sp("platform.support") or sp("device.health")) and granted)):
        abort(403)
    devs = d.q("SELECT * FROM devices WHERE school_id = ? ORDER BY kind, serial", sid)
    alerts = d.q("SELECT * FROM alerts WHERE school_id = ? ORDER BY created_at DESC LIMIT 30", sid)
    log(d, "support.view", s["name"], school_id=sid)
    return render_template("staff/school.html", s=s, devices=devs, alerts=alerts, granted=granted)
