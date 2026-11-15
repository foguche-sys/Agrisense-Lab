from conftest import csrf, login


def _post(client, **data):
    tok = csrf(client, "/pilot")
    base = {"_csrf": tok, "name": "Jo Teacher", "email": "jo@school.k12.mo.us", "school": "Boone County High"}
    base.update(data)
    return client.post("/pilot", data=base)


def test_pilot_page_and_landing_link(client):
    assert "Pilot AgriSense Lab" in client.get("/pilot").get_data(as_text=True)
    assert "/pilot" in client.get("/").get_data(as_text=True)


def test_pilot_signup_saved(client, db):
    r = _post(client, county="Boone", role="Agriculture teacher", interest="Starter", start_term="Fall 2027", students="72", site="Greenhouse")
    assert r.status_code == 200 and "on the list" in r.get_data(as_text=True)
    row = db.one("SELECT * FROM pilot_signups WHERE email = ?", "jo@school.k12.mo.us")
    assert row["school"] == "Boone County High" and row["students"] == 72 and row["interest"] == "Starter"


def test_pilot_signup_needs_email_and_rejects_odd_choices(client, db):
    assert _post(client, email="nope").status_code == 400
    _post(client, email="a@b.org", interest="Free kit please", role="<script>")
    row = db.one("SELECT * FROM pilot_signups WHERE email = ?", "a@b.org")
    assert row["interest"] is None and row["role"] is None


def test_pilot_honeypot_saves_nothing(client, db):
    _post(client, email="bot@spam.com", website="http://spam")
    assert db.one("SELECT * FROM pilot_signups WHERE email = ?", "bot@spam.com") is None


def test_staff_sees_signups_and_csv(client, db):
    _post(client, email="lead@school.org", notes="=HYPERLINK(1)")
    login(client, "owner")
    assert "lead@school.org" in client.get("/staff/").get_data(as_text=True)
    r = client.get("/staff/pilots.csv")
    assert r.status_code == 200 and "lead@school.org" in r.get_data(as_text=True)
    assert "'=HYPERLINK" in r.get_data(as_text=True)


def test_teacher_cannot_download_signups(client):
    login(client, "teacher")
    assert client.get("/staff/pilots.csv").status_code in (302, 403)
