"""Every page renders for the roles that should see it, and refuses the roles that shouldn't."""
import pytest

from conftest import login, login_student

PUBLIC = ["/", "/login", "/login/class", "/login/class?code=AGRI03", "/signup", "/quote", "/privacy"]


@pytest.mark.parametrize("path", PUBLIC)
def test_public_pages(client, path):
    assert client.get(path).status_code == 200


def test_private_pages_need_sign_in(client):
    for p in ["/admin/", "/teach/", "/studio/", "/data/", "/staff/"]:
        r = client.get(p)
        assert r.status_code == 302 and "/login" in r.headers["Location"], p
    assert client.get("/me/").status_code == 302


ROLE_PAGES = {
    "admin": ["/admin/", "/admin/people", "/admin/devices", "/admin/settings", "/admin/privacy", "/admin/billing", "/admin/audit", "/teach/", "/data/"],
    "district": ["/admin/", "/admin/people", "/admin/billing", "/admin/privacy", "/data/"],
    "it": ["/admin/", "/admin/devices", "/admin/audit"],
    "teacher": ["/teach/", "/studio/", "/studio/feeds", "/studio/devices", "/studio/actions", "/studio/code", "/data/"],
    "coteacher": ["/teach/", "/studio/", "/data/"],
    "owner": ["/staff/", "/staff/inventory"],
    "support": ["/staff/"],
    "finance": ["/staff/"],
    "parent": ["/me/parent"],
    "observer": ["/data/"],
}
FORBIDDEN = {
    "teacher": ["/admin/settings", "/admin/billing", "/staff/"],
    "it": ["/admin/people", "/admin/billing", "/admin/settings"],
    "support": ["/staff/inventory", "/admin/"],
    "owner": ["/admin/", "/data/"],   # staff need a school's support grant to see school data
    "parent": ["/teach/", "/studio/", "/admin/"],
    "observer": ["/studio/", "/admin/people"],
    "finance": ["/staff/inventory"],
}


@pytest.mark.parametrize("who", list(ROLE_PAGES))
def test_role_pages(client, who):
    login(client, who)
    for p in ROLE_PAGES[who]:
        r = client.get(p)
        assert r.status_code == 200, (who, p, r.status_code, r.get_data(as_text=True)[:300])
    for p in FORBIDDEN.get(who, []):
        r = client.get(p)
        assert r.status_code == 403, (who, p, r.status_code)


def test_teacher_pages_for_class(client, db):
    login(client, "teacher")
    cid = db.val("SELECT id FROM classes WHERE code = 'AGRI03'")
    for p in [f"/teach/?class={cid}", f"/teach/{cid}/lessons", f"/teach/{cid}/gradebook", f"/teach/{cid}/teams"]:
        assert client.get(p).status_code == 200, p
    sim = db.val("SELECT id FROM classes WHERE code = 'AGRI05'")
    html = client.get(f"/teach/?class={sim}").get_data(as_text=True)
    assert "SIMULATED DATA" in html
    team = db.val("SELECT id FROM teams WHERE slug = 'agri03-team-1'")
    did = db.val("SELECT id FROM dashboards WHERE team_id = ?", team)
    assert client.get(f"/studio/dash/{did}?team={team}").status_code == 200
    assert client.get(f"/studio/feeds/agri03-team-1.pump?team={team}").status_code == 200


def test_student_pages(client, db):
    login_student(client, db)
    for p in ["/me/", "/me/tray", "/studio/", "/studio/feeds", "/studio/devices", "/studio/actions", "/studio/code", "/data/"]:
        r = client.get(p)
        assert r.status_code == 200, (p, r.get_data(as_text=True)[:300])
    aid = db.val("SELECT a.id FROM assignments a JOIN classes c ON c.id = a.class_id WHERE c.code = 'AGRI03'")
    assert client.get(f"/me/journal/{aid}").status_code == 200
    for p in ["/admin/", "/teach/", "/staff/"]:
        assert client.get(p).status_code == 403, p


def test_student_cannot_open_other_team(client, db):
    login_student(client, db)
    other = db.val("SELECT id FROM teams WHERE slug = 'agri03-team-3'")
    did = db.val("SELECT id FROM dashboards LIMIT 1")
    # a student's own team always wins; another team's dashboard id is a 404 for them
    assert client.get(f"/studio/dash/{did}").status_code in (200, 404)
    assert client.get(f"/api/studio/{other}/state").status_code == 403


def test_wrong_pictures(client, db):
    uid = db.val("SELECT id FROM users WHERE name = 'Maya L.'")
    from conftest import csrf
    tok = csrf(client, f"/login/class?code=AGRI03&uid={uid}")
    r = client.post(f"/login/class?code=AGRI03&uid={uid}", data={"_csrf": tok, "pics": "Cow,Bee"})
    assert r.status_code == 200 and "your pictures" in r.get_data(as_text=True)


def test_csrf_required(client):
    r = client.post("/login", data={"email": "admin@demo.agrisensehub.com", "password": "agrisense-demo-2026"})
    assert r.status_code == 400
