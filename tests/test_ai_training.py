"""AI Lab (lessons 2.1-2.5) and teacher training (levels, certificates)."""
from datetime import datetime, timedelta, timezone

from conftest import csrf, login, login_student
from test_flows import ids

from agrisense.services import ai
from agrisense.services import training as T


# ---------------- maths
def test_fit_line_recovers_slope():
    xs = [0, 1, 2, 3, 4]
    ys = [30, 28, 26, 24, 22]
    a, b, r2 = ai.fit_line(xs, ys)
    assert round(a, 6) == 30 and round(b, 6) == -2 and r2 == 1.0


def test_kmeans_separates_two_groups():
    rows = [[0, 0], [0.1, 0.2], [5, 5], [5.2, 4.9]]
    labels = ai.kmeans(rows, 2)
    assert labels[0] == labels[1] and labels[2] == labels[3] and labels[0] != labels[2]


def test_sensor_check_rules_and_learned_band():
    t = lambda i: f"2026-11-01T{i // 60:02d}:{i % 60:02d}:00Z"
    pts = [(t(i), 30.0 - 0.1 * i) for i in range(20)] + [(t(20), 0.5)] + [(t(21 + i), 27.0) for i in range(7)]
    res = ai.sensor_check(pts, "moisture")
    flagged = {r["t"]: r for r in res["rows"]}
    assert any("probe out" in x for x in flagged[t(20)]["rules"]) and flagged[t(20)]["learned"]
    assert any("frozen" in x for r in res["rows"] for x in r["rules"])           # 27.0 seven times in a row


def test_leaf_score():
    s = ai.leaf_score([[9, 1, 0], [2, 7, 1], [0, 0, 10]])
    assert s["total"] == 30 and s["right"] == 26 and s["accuracy"] == 87 and s["recall"] == [90, 70, 100]
    assert s["confusion"] == (1, 0, 2)


# ---------------- AI Lab pages
def _drying_curve(db, cls_id, letter="A", start=34.0, rate=0.8, n=12):
    """Write a clean drying curve for one real tray: `rate` % per hour over the last n half-hours."""
    from agrisense.services import feeds as F
    kit = db.val("SELECT kit_id FROM classes WHERE id = ?", cls_id)
    f = db.one("SELECT * FROM feeds WHERE key = ?", F.tray_feed_key(kit, letter, "moisture"))
    db.run("DELETE FROM datapoints WHERE feed_id = ?", f["id"])
    end = datetime.now(timezone.utc)
    for i in range(n):
        at = end - timedelta(minutes=30 * (n - 1 - i))
        F.write(db, f, round(start - rate * 0.5 * i, 2), at=at.strftime("%Y-%m-%dT%H:%M:%SZ"), run_actions=False)
    db.commit()
    return f


def test_student_predicts_and_line_is_checked(client, app, db):
    i = ids(db)
    tray = db.one("SELECT tr.* FROM teams t JOIN trays tr ON tr.id = t.tray_id WHERE t.id = ?", i["t1"])
    _drying_curve(db, i["cls"], tray["letter"])
    tok = login_student(client, db)
    page = client.get("/ai/predict").get_data(as_text=True)
    assert "hours</b> until tray" in page and "-0.800 % per hour" in page
    # a student must guess first
    r = client.post("/ai/predict", data={"_csrf": tok}, follow_redirects=True)
    assert "Write your own guess first" in r.get_data(as_text=True)
    client.post("/ai/predict", data={"_csrf": tok, "student_hours": "5", "note": "sunny"})
    row = db.one("SELECT * FROM ai_predictions WHERE team_id = ?", i["t1"])
    assert row and row["student_hours"] == 5.0 and abs(row["rate"] - 0.8) < 0.01 and row["status"] == "open"
    # the tray dries past the refill point -> the prediction gets checked
    from agrisense.services import feeds as F
    f = db.one("SELECT * FROM feeds WHERE key = ?", F.tray_feed_key(db.val("SELECT kit_id FROM classes WHERE id = ?", i["cls"]), tray["letter"], "moisture"))
    F.write(db, f, row["refill"] - 1, run_actions=False)
    db.commit()
    client.get("/ai/predict")
    row = db.one("SELECT * FROM ai_predictions WHERE id = ?", row["id"])
    assert row["status"] == "checked" and row["actual_at"] and row["error_hours"] is not None
    assert "drying-curve" in client.get("/ai/predict.csv").headers["Content-Disposition"]


def test_teacher_sees_every_ai_page(client, db):
    i = ids(db)
    login(client, "teacher")
    for path in ("/ai/", "/ai/predict", "/ai/sensor", "/ai/sensor?metric=ec&hours=168", "/ai/zones", "/ai/zones?k=3", "/ai/leaf", "/ai/decide"):
        r = client.get(path + ("&" if "?" in path else "?") + f"class={i['cls']}")
        assert r.status_code == 200, path
    assert "Zone 1" in client.get(f"/ai/zones?class={i['cls']}").get_data(as_text=True)
    sim = client.get(f"/ai/predict?class={i['sim']}")
    assert sim.status_code in (200, 403)


def test_leaf_result_saved_for_team(client, db):
    i = ids(db)
    tok = login_student(client, db)
    form = {"_csrf": tok, **{f"m{a}{b}": (8 if a == b else 1) for a in range(3) for b in range(3)}, "train0": 30, "train1": 30, "train2": 25}
    r = client.post("/ai/leaf", data=form, follow_redirects=True)
    assert "24 of 30 test photos right (80 %)" in r.get_data(as_text=True)
    assert db.val("SELECT COUNT(*) AS n FROM ai_results WHERE team_id = ? AND kind = 'leaf'", i["t1"]) == 1


def test_ai_lessons_seeded_and_added_to_old_databases(db):
    assert db.val("SELECT COUNT(*) AS n FROM lessons WHERE code LIKE '2.%'") == 5
    from agrisense.services.catalog import seed_catalog
    db.run("DELETE FROM lessons WHERE code = '2.3'")
    seed_catalog(db)
    assert db.val("SELECT equipment FROM lessons WHERE code = '2.3'") == "ai"


def test_students_cannot_open_training(client, db):
    login_student(client, db)
    assert client.get("/training/").status_code == 403


# ---------------- teacher training
def test_training_levels_and_certificate(client, db):
    tok = login(client, "teacher")
    uid = db.val("SELECT id FROM users WHERE email = 'teacher@demo.agrisensehub.com'")
    assert "Level 1" in client.get("/training/").get_data(as_text=True)
    for k in sorted(T.STEP_KEYS):
        client.post("/training/", data={"_csrf": tok, "do": "step", "item": k, "on": "1", "quiet": "1"})
    a1 = db.one("SELECT * FROM pd_awards WHERE user_id = ? AND level = 1", uid)
    assert a1 and a1["hours"] == 3
    cert = client.get(f"/training/certificate/{a1['code']}").get_data(as_text=True)
    assert "Taylor Teacher" in cert and "3 <span" in cert
    # Level 3 is locked until the workshop
    r = client.post("/training/", data={"_csrf": tok, "do": "project", "title": "x", "summary": "y" * 250}, follow_redirects=True)
    assert "Finish the Level 2 workshop" in r.get_data(as_text=True)
    client.post("/logout", data={"_csrf": tok})
    # staff record the workshop
    tok = login(client, "owner")
    client.post("/training/admin", data={"_csrf": tok, "do": "workshop", "user_id": uid, "date": "2026-11-20", "place": "Columbia"})
    assert db.val("SELECT hours FROM pd_awards WHERE user_id = ? AND level = 2", uid) == 6
    client.post("/logout", data={"_csrf": tok})
    tok = login(client, "teacher")
    client.post("/training/", data={"_csrf": tok, "do": "project", "title": "Irrigation unit", "summary": "We ran lessons 2.1-2.5. " * 12})
    pid = db.val("SELECT id FROM pd_projects WHERE user_id = ?", uid)
    client.post("/logout", data={"_csrf": tok})
    tok = login(client, "owner")
    client.post("/training/admin", data={"_csrf": tok, "do": "review", "project_id": pid, "approve": "1"})
    a3 = db.one("SELECT * FROM pd_awards WHERE user_id = ? AND level = 3", uid)
    assert a3 and a3["hours"] == 12
    client.post("/logout", data={"_csrf": tok})
    # anyone can check a code, signed in or not
    page = client.get(f"/training/verify/{a3['code']}").get_data(as_text=True)
    assert "Valid" in page and "Certified AgriSense teacher" in page
    assert "Not found" in client.get("/training/verify/AS-NOPE1234").get_data(as_text=True)


def test_teacher_cannot_see_others_certificates_or_admin(client, db):
    other = db.val("SELECT id FROM users WHERE email = 'coteacher@demo.agrisensehub.com'")
    a = T.award(db, other, 1)
    db.commit()
    login(client, "teacher")
    assert client.get(f"/training/certificate/{a['code']}").status_code == 404
    assert client.get("/training/admin").status_code == 403


# ---------------- lab instructions, lab sheets, course guides
def test_every_lesson_has_lab_content_and_pages(client, db):
    from agrisense.services.lab_content import LABS
    codes = [r["code"] for r in db.q("SELECT code FROM lessons ORDER BY code")]
    assert sorted(codes) == sorted(LABS)
    login(client, "teacher")
    for code in codes:
        page = client.get(f"/labs/{code}").get_data(as_text=True)
        assert "You're done when" in page and LABS[code]["hook"][:30] in page.replace("&#39;", "'"), code
        sheet = client.get(f"/labs/{code}/sheet").get_data(as_text=True)
        assert "Claim, evidence, reasoning" in sheet and "Name" in sheet, code
    assert "Student instructions" in client.get(f"/teach/{ids(db)['cls']}/lessons").get_data(as_text=True)


def test_student_sees_instructions_and_journal_links(client, db):
    i = ids(db)
    lid = db.val("SELECT id FROM lessons WHERE code = '1.3'")
    if not db.val("SELECT id FROM assignments WHERE class_id = ? AND lesson_id = ?", i["cls"], lid):
        from agrisense.db import new_id, now
        db.insert("assignments", id=new_id("as"), class_id=i["cls"], lesson_id=lid, created_at=now())
        db.commit()
    login_student(client, db)
    home = client.get("/me/").get_data(as_text=True)
    assert "/labs/1.3" in home
    lab = client.get("/labs/1.3").get_data(as_text=True)
    assert "Open our journal" in lab and "Print lab sheet" in lab


def test_course_module_guides_and_workshop(client, db):
    from agrisense.services.training import MODULES
    from agrisense.services.training_content import GUIDES
    assert [m[0] for m in MODULES] == list(GUIDES)
    for key, _, _, steps in MODULES:
        assert {s for s, _ in steps} == set(GUIDES[key]["steps"]), key
    tok = login(client, "teacher")
    page = client.get("/training/module/m2").get_data(as_text=True)
    assert "Success looks like" in page and "If something goes wrong" in page
    r = client.post("/training/", data={"_csrf": tok, "do": "step", "item": "m2.power", "on": "1", "next": "/training/module/m2"})
    assert r.headers["Location"].endswith("/training/module/m2")
    assert "Wiring the Trainer" in client.get("/training/workshop").get_data(as_text=True)
    assert client.get("/training/module/nope").status_code == 404
