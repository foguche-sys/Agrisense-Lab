"""Sign-in hardening: per-account lockout (staff and students), teacher unlock, real client address behind a proxy,
16 sign-in pictures."""
import pytest
from conftest import csrf, login
from test_flows import ids

from agrisense import auth, create_app


@pytest.fixture(autouse=True)
def _fresh_address_limits():
    auth._attempts.clear()
    yield
    auth._attempts.clear()


def _staff_try(client, pw, ip="10.0.0.1"):
    tok = csrf(client)
    return client.post("/login", data={"_csrf": tok, "email": "teacher@demo.agrisensehub.com", "password": pw},
                       environ_base={"REMOTE_ADDR": ip})


def test_staff_account_locks_after_10_wrong_tries(client, db):
    for k in range(10):
        assert _staff_try(client, "nope", ip=f"10.0.0.{k}").status_code == 401     # different addresses: the account lock still counts
    r = _staff_try(client, "agrisense-demo-2026", ip="10.0.1.1")
    assert r.status_code == 401 and "Too many wrong tries for this account" in r.get_data(as_text=True)
    assert db.val("SELECT COUNT(*) AS n FROM audit_log WHERE action = 'signin.locked'") == 1
    db.run("UPDATE users SET locked_until = '2000-01-01T00:00:00Z' WHERE email = 'teacher@demo.agrisensehub.com'")
    db.commit()
    assert _staff_try(client, "agrisense-demo-2026").status_code == 302          # lock expired


def test_a_correct_password_resets_the_count(client, db):
    for _ in range(9):
        _staff_try(client, "nope")
    assert _staff_try(client, "agrisense-demo-2026").status_code == 302
    assert db.val("SELECT failed_logins FROM users WHERE email = 'teacher@demo.agrisensehub.com'") == 0


def _student_try(client, uid, pics):
    tok = csrf(client, f"/login/class?code=AGRI03&uid={uid}")
    return client.post(f"/login/class?code=AGRI03&uid={uid}", data={"_csrf": tok, "pics": pics})


def test_student_locks_after_5_wrong_pictures_and_teacher_unlocks(client, db):
    i = ids(db)
    uid = db.val("SELECT u.id FROM users u JOIN memberships m ON m.user_id = u.id WHERE u.name = 'Maya L.' AND m.class_id = ?", i["cls"])
    for _ in range(5):
        _student_try(client, uid, "Cow,Bee")
    r = _student_try(client, uid, "Sun,Corn")                                     # right pictures, but locked
    assert r.status_code == 423 and "Ask your teacher to unlock you" in r.get_data(as_text=True)
    tok = login(client, "teacher")
    assert "Locked" in client.get(f"/teach/{i['cls']}/teams").get_data(as_text=True)
    client.post(f"/teach/{i['cls']}/teams", data={"_csrf": tok, "do": "unlock", "user_id": uid})
    client.post("/logout", data={"_csrf": tok})
    assert _student_try(client, uid, "Sun,Corn").status_code == 302


def test_sixteen_pictures_and_old_cards_still_work(client, db):
    assert len(auth.PICTURES) == 16 == len(set(auth.PICTURES))
    assert auth.PICTURES[:8] == ["Corn", "Bee", "Tractor", "Rain", "Sun", "Seed", "Cow", "Leaf"]
    i = ids(db)
    uid = db.val("SELECT u.id FROM users u JOIN memberships m ON m.user_id = u.id WHERE u.name = 'Maya L.' AND m.class_id = ?", i["cls"])
    page = client.get(f"/login/class?code=AGRI03&uid={uid}").get_data(as_text=True)
    assert page.count('class="pic"') == 16
    svgs = [page.split(f'data-pic="{p}"')[1].split("</svg>")[0] for p in auth.PICTURES]
    assert len(set(svgs)) == 16                                                    # every picture has its own drawing


def test_proxy_address_is_used_when_trusted(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE_URL": f"sqlite:///{tmp_path}/p.db", "TRUST_PROXY": True})
    seen = []

    @app.route("/_ip")
    def _ip():
        from flask import request
        seen.append(request.remote_addr)
        return "ok"
    app.test_client().get("/_ip", headers={"X-Forwarded-For": "203.0.113.7"}, environ_base={"REMOTE_ADDR": "10.1.1.1"})
    assert seen == ["203.0.113.7"]
    plain = create_app({"TESTING": True, "SECRET_KEY": "t", "DATABASE_URL": f"sqlite:///{tmp_path}/q.db", "TRUST_PROXY": False})
    assert type(plain.wsgi_app).__name__ != "ProxyFix"
