"""Privacy policy, agreement terms, minimal-data mode, deleting a class's student data, standards map."""
from conftest import csrf, login
from test_flows import ids

from agrisense.services import standards as S
from agrisense.services.catalog import LESSONS


def test_public_privacy_agreement_and_standards_pages(client):
    p = client.get("/privacy").get_data(as_text=True)
    assert "school official" in p and "never" in p and "retention" in p and "Render Services" in p
    a = client.get("/privacy/agreement").get_data(as_text=True)
    assert "NDPA" in a and "72 hours" in a and "Exhibit B" in a
    s = client.get("/standards").get_data(as_text=True)
    assert "HS-ETS1-2" in s and "3A-DA-11" in s and "PST.05.01" in s and "Meet the soil bench" in s


def test_every_lesson_is_mapped_to_known_codes():
    assert {code for code, *_ in LESSONS} == set(S.MAP)
    for lesson, m in S.MAP.items():
        assert m["ngss"] and m["csta"], lesson
        assert all(c in S.NGSS for c, _ in m["ngss"]), lesson
        assert all(c in S.CSTA for c in m["csta"]), lesson
        assert all(c in S.AFNR for c in m["afnr"]), lesson
        assert all(s in S.SEP for s in m["sep"]) and all(c in S.CCC for c in m["ccc"]), lesson
    assert any(c.startswith("PST.") for m in S.MAP.values() for c in m["afnr"])


def test_lesson_rows_carry_the_mapped_standards(db):
    assert db.val("SELECT standards FROM lessons WHERE code = '1.6'") == S.short_codes("1.6")


def test_code_names_mode(client, db):
    i = ids(db)
    tok = login(client, "admin")
    client.post(f"/admin/settings?school={i['school']}", data={"_csrf": tok, "pump_max_seconds": "300", "retention_days": "365",
                                                              "student_names": "code"})
    client.post(f"/admin/classes?school={i['school']}", data={"_csrf": tok, "name": "Period 8", "teams": "2"})
    cid = db.val("SELECT id FROM classes WHERE name = 'Period 8'")
    html = client.post(f"/admin/students?school={i['school']}", data={"_csrf": tok, "class_id": cid, "names": "Grace Hopper\nAlan Turing\n"}).get_data(as_text=True)
    assert "Student 01" in html and "Student 02" in html and "Grace" not in html
    assert db.val("SELECT COUNT(*) AS n FROM users WHERE name LIKE 'Grace%'") == 0


def test_replace_existing_names_with_codes(client, db):
    i = ids(db)
    tok = login(client, "admin")
    client.post(f"/admin/privacy?school={i['school']}", data={"_csrf": tok, "do": "codes"})
    assert db.val("SELECT COUNT(*) AS n FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.class_id = ? AND m.role = 'student' "
                  "AND u.name NOT LIKE 'Student %'", i["cls"]) == 0


def test_delete_class_student_data(client, db):
    i = ids(db)
    tok = login(client, "admin")
    name = db.val("SELECT name FROM classes WHERE id = ?", i["cls"])
    readings = db.val("SELECT COUNT(*) AS n FROM datapoints")
    r = client.post(f"/admin/privacy?school={i['school']}", data={"_csrf": tok, "do": "delete_class", "class_id": i["cls"], "confirm": "wrong"},
                    follow_redirects=True)
    assert "Nothing was deleted" in r.get_data(as_text=True)
    assert db.val("SELECT COUNT(*) AS n FROM memberships WHERE class_id = ? AND role = 'student'", i["cls"]) > 0
    client.post(f"/admin/privacy?school={i['school']}", data={"_csrf": tok, "do": "delete_class", "class_id": i["cls"], "confirm": name})
    assert db.val("SELECT COUNT(*) AS n FROM memberships WHERE class_id = ? AND role = 'student'", i["cls"]) == 0
    assert db.val("SELECT COUNT(*) AS n FROM users WHERE name = 'Deleted student'") > 0
    assert db.val("SELECT COUNT(*) AS n FROM journals WHERE team_id = ?", i["t1"]) == 0
    assert db.val("SELECT COUNT(*) AS n FROM datapoints") == readings              # sensor data kept
    assert db.val("SELECT COUNT(*) AS n FROM audit_log WHERE action = 'privacy.delete_class'") == 1


def test_teacher_cannot_delete_class_data(client, db):
    i = ids(db)
    tok = login(client, "teacher")
    r = client.post(f"/admin/privacy?school={i['school']}", data={"_csrf": tok, "do": "delete_class", "class_id": i["cls"], "confirm": "x"})
    assert r.status_code == 403
