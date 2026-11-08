"""Demo data: `flask --app agrisense seed-demo`. Never run against a real school's database."""
import math
import os
import random
from datetime import datetime, timedelta, timezone

from . import auth
from .db import jdump, new_id, now
from .services import feeds as F
from .services.catalog import seed_catalog
from .services.simulate import SOILS

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "agrisense-demo-2026")
STUDENT_PICS = ["Corn", "Sun"]


def ensure_platform_org(db):
    oid = db.val("SELECT id FROM orgs WHERE kind = 'platform'")
    if oid:
        return oid
    oid = new_id("org")
    db.insert("orgs", id=oid, name="AgriSense Hub", kind="platform", created_at=now())
    return oid


def _user(db, name, email, role, **scope):
    uid = auth.create_user(db, name, email, DEMO_PASSWORD)
    auth.add_membership(db, uid, role, **scope)
    return uid


def run(db):
    if db.val("SELECT id FROM schools WHERE name = 'Columbia Demo High School'"):
        return "Demo data is already loaded."
    seed_catalog(db)
    rnd = random.Random(7)
    plat = ensure_platform_org(db)
    _user(db, "Ava Owner", "owner@demo.agrisensehub.com", "owner", org_id=plat)
    _user(db, "Sam Support", "support@demo.agrisensehub.com", "support", org_id=plat)
    _user(db, "Fran Finance", "finance@demo.agrisensehub.com", "finance", org_id=plat)
    _user(db, "Oscar Ops", "ops@demo.agrisensehub.com", "ops", org_id=plat)

    org = new_id("org")
    db.insert("orgs", id=org, name="Boone County Schools (demo)", kind="client", client_type="district", state="MO", created_at=now())
    sch = new_id("sch")
    db.insert("schools", id=sch, org_id=org, name="Columbia Demo High School", city="Columbia", state="MO",
              timezone="America/Chicago", settings=jdump({"pump_max_seconds": 300, "class_hours_only": False, "parents_enabled": True}), created_at=now())
    _user(db, "Dana District", "district@demo.agrisensehub.com", "client_admin", org_id=org)
    _user(db, "Priya Privacy", "privacy@demo.agrisensehub.com", "privacy", org_id=org)
    _user(db, "Alex Admin", "admin@demo.agrisensehub.com", "school_admin", school_id=sch)
    _user(db, "Ivan IT", "it@demo.agrisensehub.com", "it", school_id=sch)
    plan = db.val("SELECT id FROM plans WHERE code = 'school'")
    db.insert("subscriptions", id=new_id("sub"), org_id=org, plan_id=plan, licences=1, status="active", renews_on="2027-07-31", created_at=now())
    db.insert("privacy_agreements", id=new_id("dpa"), org_id=org, version="2026.1", status="signed", signed_by="Priya Privacy", signed_at=now())
    db.insert("invoices", id=new_id("in"), org_id=org, number="INV-1001", kind="invoice",
              lines=jdump([{"desc": "AgriSense Lab kit (soil bench + 5 Trainer Boards)", "qty": 1, "unit_cents": 340000},
                           {"desc": "School plan licence, 2026-27", "qty": 1, "unit_cents": 120000}]),
              amount_cents=460000, status="sent", due_on="2026-12-15", created_at=now())

    kit = new_id("kit")
    db.insert("kits", id=kit, school_id=sch, name="Soil bench 1", created_at=now())
    trays = []
    for letter, soil, label, crop in [("A", "sandy", "Sandy", "lettuce"), ("B", "loam", "Loam", "corn"), ("C", "clay", "Clay", "soybean"),
                                      ("D", "fertilized", "Fertilized loam", "tomato"), ("E", "salty", "Salty loam", "none")]:
        tid = new_id("tr")
        db.insert("trays", id=tid, kit_id=kit, letter=letter, soil=soil, label=label, crop=crop)
        trays.append({"id": tid, "letter": letter, "soil": soil, "label": label, "kit_id": kit, "crop": crop})

    keys = {}

    def device(kind, serial, **cols):
        key = auth.new_key("dev")
        keys[serial] = key
        did = new_id("dv")
        db.insert("devices", id=did, serial=serial, kind=kind, claim_code="DEMO-0000", key_hash=auth.hash_key(key), school_id=sch,
                  status="online", firmware="1.0.0", rssi=-70 - rnd.randint(0, 25), supply_v=12.1, last_seen=now(), claimed_at=now(),
                  config=jdump(cols.pop("config", {})), created_at=now(), **cols)
        return did

    device("gateway", "GW-DEMO", kit_id=kit)
    for t in trays:
        device("deck" if t["letter"] == "E" else "node", f"ND-DEM{t['letter']}", kit_id=kit, tray_id=t["id"])
    device("pump", "PM-DEMO", kit_id=kit)
    for i in range(5):
        device("trainer", f"TR-DEM{i + 1}", kit_id=kit)
    db.insert("devices", id=new_id("dv"), serial="ND-NEW1", kind="node", claim_code="TEST-CLAIM", key_hash=auth.hash_key("unused"),
              status="inventory", config="{}", created_at=now())

    cls = new_id("cls")
    db.insert("classes", id=cls, school_id=sch, name="Period 3 Ag Science", code="AGRI03", kit_id=kit, sim_enabled=0,
              sim_started_at=now(), sim_speed=60, pump_requests_allowed=1, created_at=now())
    sim_cls = new_id("cls")
    db.insert("classes", id=sim_cls, school_id=sch, name="Period 5 Environmental Science", code="AGRI05", kit_id=kit, sim_enabled=1,
              sim_event="dry_spell", sim_started_at=now(), sim_speed=60, pump_requests_allowed=1, created_at=now())
    _user(db, "Taylor Teacher", "teacher@demo.agrisensehub.com", "teacher", class_id=cls)
    t_uid = db.val("SELECT id FROM users WHERE email = 'teacher@demo.agrisensehub.com'")
    auth.add_membership(db, t_uid, "teacher", class_id=sim_cls)
    _user(db, "Casey Co-teacher", "coteacher@demo.agrisensehub.com", "co_teacher", class_id=cls)
    _user(db, "Riley Researcher", "observer@demo.agrisensehub.com", "observer", class_id=cls)

    names = ["Maya L.", "Jordan K.", "Sofia R.", "Liam T.", "Ava M.", "Noah P.", "Emma W.", "Ethan B.", "Mia C.", "Lucas D."]
    first_student = None
    for cid, prefix in ((cls, "agri03"), (sim_cls, "agri05")):
        for i in range(5):
            team = new_id("tm")
            db.insert("teams", id=team, class_id=cid, name=f"Team {i + 1}", slug=f"{prefix}-team-{i + 1}", tray_id=trays[i]["id"])
            if cid == cls:
                tr_id = db.val("SELECT id FROM devices WHERE serial = ?", f"TR-DEM{i + 1}")
                db.update("devices", tr_id, team_id=team, config=jdump({"components": F.DEFAULT_TRAINER}))
                trow = db.one("SELECT * FROM teams WHERE id = ?", team)
                F.ensure_team_feeds(db, trow, F.DEFAULT_TRAINER)
            for j in range(2):
                nm = names[i * 2 + j] if cid == cls else names[(i * 2 + j + 3) % len(names)]
                uid = auth.create_user(db, nm)
                db.update("users", uid, picture_hash=auth.picture_hash(STUDENT_PICS, uid))
                auth.add_membership(db, uid, "student", class_id=cid, team_id=team)
                if first_student is None:
                    first_student = uid
    parent = auth.create_user(db, "Pat Parent", "parent@demo.agrisensehub.com", DEMO_PASSWORD)
    auth.add_membership(db, parent, "parent", child_user_id=first_student)

    # 48 h of bench readings every 10 minutes, with one watering of tray B 20 h ago
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    kit_row = db.one("SELECT * FROM kits WHERE id = ?", kit)
    for t in trays:
        fc, wp, dry, ec0, ph, toff = SOILS[t["soil"]]
        feeds = F.ensure_tray_feeds(db, kit_row, t)
        m = fc - 1
        for k in range(288, -1, -1):
            at = end - timedelta(minutes=10 * k)
            hour = at.hour + at.minute / 60
            m = max(4.0, m - dry / 6 * (1.25 if 11 <= (hour - 6) % 24 <= 17 else 0.8))
            if t["letter"] == "B" and k == 120:
                m = min(fc + 1, m + 9)
            if t["letter"] == "A" and k == 60:
                m = min(fc, m + 12)
            temp = 18 + toff + 2.4 * math.sin((hour - 15) / 24 * 2 * math.pi) + rnd.uniform(-.15, .15)
            vals = {"moisture": round(m + rnd.uniform(-.2, .2), 1), "temp": round(temp, 1), "ph": round(ph + rnd.uniform(-.04, .04), 2)}
            if m >= 10:
                ec = ec0 * (m / fc) ** 0.35
                vals.update(ec=round(ec), n=round(ec * .09), p=round(ec * .03), k=round(ec * .23))
            ts = now(at)
            for metric, v in vals.items():
                F.write(db, feeds[metric], float(v), source="device", at=ts, run_actions=False)

    # Trainer feeds for team 1 + a starter dashboard
    t1 = db.one("SELECT * FROM teams WHERE slug = 'agri03-team-1'")
    for k in range(60, -1, -1):
        ts = now(end - timedelta(minutes=k))
        for comp, v in (("moisture", 22 + 3 * math.sin(k / 9)), ("air-temp", 23.5 + math.sin(k / 15)), ("pressure", 0.0 if k % 20 else 46.0)):
            f = db.one("SELECT * FROM feeds WHERE key = ?", f"{t1['slug']}.{comp}")
            F.write(db, f, round(v, 1), source="device", at=ts, run_actions=False)
    for comp, v in (("pump", "OFF"), ("fan", "OFF"), ("tank", "OK"), ("vent", "45")):
        F.write(db, db.one("SELECT * FROM feeds WHERE key = ?", f"{t1['slug']}.{comp}"), v, source="device", run_actions=False)
    s = t1["slug"]
    db.insert("dashboards", id=new_id("db"), team_id=t1["id"], name="Irrigation control", created_at=now(), blocks=jdump([
        {"id": new_id("b"), "type": "toggle", "feed": f"{s}.pump", "title": "Pump"},
        {"id": new_id("b"), "type": "toggle", "feed": f"{s}.fan", "title": "Fan"},
        {"id": new_id("b"), "type": "soilwater", "feed": f"{s}.moisture", "title": "Soil water"},
        {"id": new_id("b"), "type": "indicator", "feed": f"{s}.tank", "title": "Tank", "on": "OK"},
        {"id": new_id("b"), "type": "chart", "feed": f"{s}.pressure", "title": "Pressure (kPa)", "hours": 1},
        {"id": new_id("b"), "type": "slider", "feed": f"{s}.vent", "title": "Vent servo", "min": 0, "max": 180},
        {"id": new_id("b"), "type": "chart", "feed": F.tray_feed_key(kit, "A", "moisture"), "title": "Tray A moisture (bench)", "hours": 48},
    ]))
    db.insert("actions", id=new_id("ac"), team_id=t1["id"], name="Water when dry", feed_key=f"{s}.moisture", op="lt", threshold="15",
              effect="on", target_feed=f"{s}.pump", seconds=20, rest_seconds=120, start_hhmm="08:00", end_hhmm="15:30", enabled=1, created_at=now())
    db.insert("actions", id=new_id("ac"), team_id=t1["id"], name="Fan on when hot", feed_key=f"{s}.air-temp", op="gt", threshold="30",
              effect="on", target_feed=f"{s}.fan", seconds=30, rest_seconds=120, start_hhmm="00:00", end_hhmm="23:59", enabled=1, created_at=now())

    lesson = db.one("SELECT * FROM lessons WHERE code = '1.3'")
    for c in (cls, sim_cls):
        db.insert("assignments", id=new_id("as"), class_id=c, lesson_id=lesson["id"], data_source="live", allow_pump=1, points=20,
                  created_by=t_uid, created_at=now())
    tray_b = trays[1]["id"]
    s1 = db.val("SELECT user_id FROM memberships WHERE team_id = ? AND role = 'student'", db.val("SELECT id FROM teams WHERE slug = 'agri03-team-2'"))
    db.insert("pump_requests", id=new_id("pr"), class_id=cls, team_id=db.val("SELECT id FROM teams WHERE slug = 'agri03-team-2'"), tray_id=tray_b,
              requested_by=s1, seconds=40, reason="Moisture 14 %, under our 18 % target", moisture_before=14.0, prediction=18.0, status="pending", simulated=0, created_at=now())

    lines = ["Demo loaded. Password for every adult account: " + DEMO_PASSWORD,
             "  owner@ support@ finance@ ops@ district@ privacy@ admin@ it@ teacher@ coteacher@ observer@ parent@  (all @demo.agrisensehub.com)",
             f"Students: class code AGRI03 (live) or AGRI05 (simulated) → pick a name → pictures {STUDENT_PICS[0]} + {STUDENT_PICS[1]}",
             "Register test: serial ND-NEW1, claim code TEST-CLAIM", "Device keys (put in firmware secrets.h to test the API):"]
    lines += [f"  {s_}: {k}" for s_, k in keys.items()]
    return "\n".join(lines)
