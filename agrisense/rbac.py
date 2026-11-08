"""Roles and permissions: the "Access levels and roles" board, as code.

A membership gives a user one role inside one scope:
  platform staff  -> org_id = the AgriSense Hub platform org
  client roles    -> org_id = the client (district / org)
  school roles    -> school_id
  class roles     -> class_id (teacher, co-teacher, substitute, observer)
  student         -> class_id + team_id
  parent          -> child_user_id

can(user_ctx, perm, **scope) answers "may this user do <perm> on this thing?".
Scope is resolved upward: team -> class -> school -> org.
"""
from .db import now

PLATFORM_ROLES = {
    "owner": "Owner / super admin",
    "ops": "Operations",
    "support": "Support agent",
    "finance": "Finance",
    "content": "Content editor",
    "sales": "Sales",
}
CLIENT_ROLES = {
    "client_admin": "Client admin",
    "billing": "Billing contact",
    "privacy": "Privacy officer",
}
SCHOOL_ROLES = {
    "school_admin": "School admin",
    "it": "IT / device manager",
}
CLASS_ROLES = {
    "teacher": "Teacher",
    "co_teacher": "Co-teacher / aide",
    "substitute": "Substitute",
    "observer": "Researcher / observer",
    "student": "Student",
}
OTHER_ROLES = {"parent": "Parent / guardian"}
ROLES = {**PLATFORM_ROLES, **CLIENT_ROLES, **SCHOOL_ROLES, **CLASS_ROLES, **OTHER_ROLES}

# Permissions each role has within its own scope.
# Names: area.action. "names.view" = may see student names; "*.deid" = de-identified only.
PERMS = {
    # AgriSense Hub staff
    "owner": {"platform.clients", "platform.billing", "platform.fleet", "platform.content", "platform.staff",
              "platform.status", "platform.support", "platform.quotes", "live.view", "export.deid"},
    "ops": {"platform.clients.view", "platform.fleet", "platform.status", "device.health"},
    "support": {"platform.clients.view", "platform.support", "device.health", "device.restart"},
    "finance": {"platform.clients.view", "platform.billing", "platform.quotes"},
    "content": {"platform.content"},
    "sales": {"platform.clients.leads", "platform.quotes"},
    # client
    "client_admin": {"live.view", "names.view", "people.manage", "roles.assign", "roles.assign.client", "devices.manage",
                     "firmware.manage", "export.named", "export.deid", "billing.manage", "billing.view",
                     "privacy.manage", "audit.view", "school.settings", "sim.control"},
    "billing": {"billing.manage", "billing.view"},
    "privacy": {"live.view", "names.view", "export.named", "export.deid", "privacy.manage", "audit.view"},
    # school
    "school_admin": {"live.view", "names.view", "pump.stop", "classes.manage", "grade", "people.manage", "roles.assign",
                     "devices.manage", "devices.assign_tray", "firmware.manage", "export.named", "export.deid",
                     "billing.view", "privacy.request", "audit.view", "sim.control", "school.settings"},
    "it": {"live.readings", "device.health", "devices.manage", "firmware.manage", "pump.stop", "export.deid", "audit.devices"},
    # class
    "teacher": {"live.view", "names.view", "pump.request", "pump.approve", "pump.stop", "classes.manage", "grade",
                "people.manage", "roles.assign.class", "devices.assign_tray", "export.named", "export.deid",
                "sim.control", "studio.lock", "studio.view", "actions.approve", "journal.view"},
    "co_teacher": {"live.view", "names.view", "pump.request", "pump.approve", "pump.stop", "grade.assist",
                   "export.named", "export.deid", "sim.control", "studio.lock", "studio.view", "journal.view"},
    "substitute": {"live.view", "names.first", "pump.stop", "sim.control", "studio.view"},
    "observer": {"live.deid", "export.deid"},
    "student": {"live.view", "names.team", "pump.request", "export.team", "export.deid", "studio.use", "journal.write"},
    "parent": {"child.view"},
}

# Roles a teacher may hand out inside their class; school admins inside their school.
ASSIGNABLE_BY = {
    "teacher": {"co_teacher", "substitute", "student"},
    "school_admin": {"teacher", "co_teacher", "substitute", "student", "it", "observer", "parent"},
    "client_admin": set(ROLES) - set(PLATFORM_ROLES),
    "owner": set(ROLES),
}

# Adults who may press STOP on any pump they can see (safety rule on the board)
STOP_ROLES = {"teacher", "co_teacher", "substitute", "school_admin", "it"}


def _active(m):
    return not m.get("expires_at") or m["expires_at"] > now()


def load_memberships(db, user_id):
    return [m for m in db.q("SELECT * FROM memberships WHERE user_id = ?", user_id) if _active(m)]


def resolve_scope(db, team_id=None, class_id=None, school_id=None, org_id=None):
    """Fill in the parents of whatever scope we were given."""
    if team_id and not class_id:
        class_id = db.val("SELECT class_id FROM teams WHERE id = ?", team_id)
    if class_id and not school_id:
        school_id = db.val("SELECT school_id FROM classes WHERE id = ?", class_id)
    if school_id and not org_id:
        org_id = db.val("SELECT org_id FROM schools WHERE id = ?", school_id)
    return team_id, class_id, school_id, org_id


def platform_org_id(db):
    return db.val("SELECT id FROM orgs WHERE kind = 'platform'")


def can(db, memberships, perm, team_id=None, class_id=None, school_id=None, org_id=None):
    team_id, class_id, school_id, org_id = resolve_scope(db, team_id, class_id, school_id, org_id)
    plat = platform_org_id(db)
    for m in memberships:
        if perm not in PERMS.get(m["role"], ()):
            continue
        role = m["role"]
        if role in PLATFORM_ROLES and m["org_id"] == plat:
            # AgriSense staff reach inside a school only while that school has granted support access.
            if perm.startswith("platform.") or not (school_id or org_id):
                return True
            if school_id and db.val("SELECT id FROM support_access WHERE school_id = ? AND expires_at > ?", school_id, now()):
                return True
            continue
        if role in CLIENT_ROLES and m["org_id"] and (org_id == m["org_id"] or (not any([team_id, class_id, school_id, org_id]))):
            return True
        if role in SCHOOL_ROLES and m["school_id"] and (school_id == m["school_id"] or not any([team_id, class_id, school_id])):
            return True
        if role in ("teacher", "co_teacher", "substitute", "observer") and m["class_id"]:
            if class_id == m["class_id"] or (not class_id and not team_id and not school_id):
                return True
        if role == "student" and m["class_id"]:
            if team_id and team_id == m["team_id"]:
                return True
            if not team_id and class_id == m["class_id"]:
                return True
            if not any([team_id, class_id, school_id]):
                return True
    return False


def roles_of(memberships):
    return {m["role"] for m in memberships}


def home_for(memberships):
    """Where to send a user after sign-in, by their most powerful role."""
    r = roles_of(memberships)
    if r & set(PLATFORM_ROLES):
        return "staff.console"
    if r & {"client_admin", "school_admin", "it", "billing", "privacy"}:
        return "admin.overview"
    if r & {"teacher", "co_teacher", "substitute"}:
        return "teacher.home"
    if "student" in r:
        return "student.home"
    if "parent" in r:
        return "student.parent"
    if "observer" in r:
        return "data.explorer"
    return "public.landing"


def schools_for(db, memberships):
    """Schools this user can manage or see, used for admin pages."""
    ids = set()
    for m in memberships:
        if m["role"] in PLATFORM_ROLES:
            return [r["id"] for r in db.q("SELECT id FROM schools ORDER BY name")]
        if m["role"] in CLIENT_ROLES and m["org_id"]:
            ids.update(r["id"] for r in db.q("SELECT id FROM schools WHERE org_id = ?", m["org_id"]))
        if m["school_id"]:
            ids.add(m["school_id"])
        if m["class_id"]:
            sid = db.val("SELECT school_id FROM classes WHERE id = ?", m["class_id"])
            if sid:
                ids.add(sid)
    return sorted(ids)


def classes_for(db, memberships):
    """Classes a teacher-type user works in (school admins see every class in their school)."""
    ids = []
    for m in memberships:
        if m["role"] in ("teacher", "co_teacher", "substitute", "observer") and m["class_id"]:
            ids.append(m["class_id"])
        elif m["role"] in ("school_admin",) and m["school_id"]:
            ids += [r["id"] for r in db.q("SELECT id FROM classes WHERE school_id = ? ORDER BY name", m["school_id"])]
        elif m["role"] == "client_admin" and m["org_id"]:
            ids += [r["id"] for r in db.q("SELECT c.id FROM classes c JOIN schools s ON s.id = c.school_id WHERE s.org_id = ? ORDER BY c.name", m["org_id"])]
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def may_assign(memberships, role, scope_kind):
    for m in memberships:
        allowed = ASSIGNABLE_BY.get(m["role"], set())
        if role in allowed:
            return True
    return False
