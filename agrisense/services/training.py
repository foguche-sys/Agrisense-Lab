"""Teacher training (professional learning) in three levels, with certificates of hours.

Level 1  Get started             self-paced on this website, about 3 h: tick every step of the 6 modules
Level 2  Hands-on workshop        about 6 h, in person or live online: AgriSense Hub staff record attendance
Level 3  Certified AgriSense teacher   about 12 h: Level 2 + a classroom project write-up, reviewed by staff

Certificates state hours of professional learning. Whether the hours count toward a license or
re-certification is decided by the teacher's district or state, and the certificate says so.
"""
import secrets

from ..db import new_id, now

LEVELS = {
    1: {"title": "Get started", "hours": 3, "format": "Self-paced on this website",
        "outcome": "Unbox the kit, power the Trainer safely, set up your class and run lessons 1.1–1.3."},
    2: {"title": "Hands-on workshop", "hours": 6, "format": "One day, in person or live online",
        "outcome": "Wire sensors, set up field nodes and the gateway, run the irrigation and AI lessons."},
    3: {"title": "Certified AgriSense teacher", "hours": 12, "format": "Workshop + a classroom project + a short write-up",
        "outcome": "Lead the full course and mentor other teachers."},
}

# Level 1 modules: (key, title, minutes, [(step key, step)])
MODULES = [
    ("m1", "Unbox and check the kit", 30, [
        ("box", "Check every part against the packing list in the lid"),
        ("fit", "Print or check the fit-test coupon: a 4 mm and a 2 mm jack drop in by hand"),
        ("label", "Label the 12 V adapter and keep the water station tray off the board"),
    ]),
    ("m2", "Power the Trainer and run the safety checks", 30, [
        ("power", "Plug in 12 V: the power LED and the controller screen light up"),
        ("rails", "Measure TP1 12 V, TP2 5 V and TP3 3.3 V with a meter"),
        ("stop", "Press STOP on the Teach page and see every output switch off"),
    ]),
    ("m3", "Set up your class on the website", 30, [
        ("class", "Create the class and teams, and give each team a tray"),
        ("cards", "Print the picture sign-in cards and sign in as a test student"),
        ("roles", "Add a co-teacher or substitute if you have one"),
    ]),
    ("m4", "Teach lessons 1.1–1.3", 45, [
        ("assign", "Assign lessons 1.1 to 1.3 from the Lessons tab"),
        ("sim", "Try simulation mode so you can rehearse without real soil"),
        ("journal", "Open a team journal and grade one claim–evidence–reasoning answer"),
    ]),
    ("m5", "Watering safely: approvals, STOP and rules", 30, [
        ("approve", "Approve one pump request and watch the decision log fill in"),
        ("rule", "Add the 'Water at the refill point' rule and approve it"),
        ("lock", "Lock and unlock the Field Studio controls"),
    ]),
    ("m6", "Troubleshooting cards", 15, [
        ("offline", "Know what to do when a node shows 'offline' (power, Wi-Fi, gateway)"),
        ("probe", "Know what a probe reading of 0 % means (probe out of the soil)"),
        ("help", "Know where to get help: the support email at the bottom of every page"),
    ]),
]
STEP_KEYS = {f"{m}.{s}" for m, _, _, steps in MODULES for s, _ in steps}
TEACHERISH = {"teacher", "co_teacher", "substitute", "school_admin", "client_admin"}


def is_teacherish(memberships):
    return any(m["role"] in TEACHERISH for m in memberships)


def done_steps(db, user_id):
    return {r["item"] for r in db.q("SELECT item FROM pd_progress WHERE user_id = ?", user_id)}


def toggle(db, user_id, item, on):
    if item not in STEP_KEYS:
        return
    have = db.one("SELECT id FROM pd_progress WHERE user_id = ? AND item = ?", user_id, item)
    if on and not have:
        db.insert("pd_progress", id=new_id("pp"), user_id=user_id, item=item, done_at=now())
    elif not on and have:
        db.run("DELETE FROM pd_progress WHERE id = ?", have["id"])


def awards(db, user_id):
    return {r["level"]: r for r in db.q("SELECT * FROM pd_awards WHERE user_id = ? ORDER BY level", user_id)}


def _code(db):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        c = "AS-" + "".join(secrets.choice(alphabet) for _ in range(8))
        if not db.val("SELECT id FROM pd_awards WHERE code = ?", c):
            return c


def award(db, user_id, level, by=None, note=""):
    have = db.one("SELECT * FROM pd_awards WHERE user_id = ? AND level = ?", user_id, level)
    if have:
        return have
    db.insert("pd_awards", id=new_id("pa"), user_id=user_id, level=level, hours=LEVELS[level]["hours"], code=_code(db),
              awarded_at=now(), awarded_by=by, note=(note or "")[:200])
    return db.one("SELECT * FROM pd_awards WHERE user_id = ? AND level = ?", user_id, level)


def check_level1(db, user_id):
    """Level 1 is awarded automatically once every step of every module is ticked."""
    if STEP_KEYS <= done_steps(db, user_id):
        return award(db, user_id, 1, note="All Level 1 modules completed")
    return None


def progress(db, user_id):
    done = done_steps(db, user_id)
    mods = []
    for key, title, mins, steps in MODULES:
        st = [{"key": f"{key}.{s}", "text": t, "done": f"{key}.{s}" in done} for s, t in steps]
        mods.append({"key": key, "title": title, "minutes": mins, "steps": st, "complete": all(s["done"] for s in st)})
    n_done = sum(1 for k in STEP_KEYS if k in done)
    return {"modules": mods, "done": n_done, "total": len(STEP_KEYS), "pct": round(100 * n_done / len(STEP_KEYS))}


def project(db, user_id):
    return db.one("SELECT * FROM pd_projects WHERE user_id = ? ORDER BY submitted_at DESC LIMIT 1", user_id)


def submit_project(db, user_id, title, summary, link):
    p = project(db, user_id)
    if p and p["status"] in ("submitted", "approved"):
        return p
    db.insert("pd_projects", id=new_id("pj"), user_id=user_id, title=title[:120], summary=summary[:4000], link=(link or "")[:300],
              status="submitted", submitted_at=now())
    return project(db, user_id)


def review_project(db, pid, reviewer_id, approve, feedback=""):
    p = db.one("SELECT * FROM pd_projects WHERE id = ?", pid)
    if not p or p["status"] != "submitted":
        return None
    db.run("UPDATE pd_projects SET status = ?, reviewed_by = ?, reviewed_at = ?, feedback = ? WHERE id = ?",
           "approved" if approve else "returned", reviewer_id, now(), (feedback or "")[:1000], pid)
    if approve and awards(db, p["user_id"]).get(2):
        award(db, p["user_id"], 3, by=reviewer_id, note="Classroom project approved")
    return True
