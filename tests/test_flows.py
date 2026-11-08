"""End-to-end flows: hardware in, decisions out, safety limits, data out."""
import io
import json

from openpyxl import load_workbook

from conftest import csrf, device_key, login, login_student


def ids(db):
    return {
        "cls": db.val("SELECT id FROM classes WHERE code = 'AGRI03'"),
        "sim": db.val("SELECT id FROM classes WHERE code = 'AGRI05'"),
        "t1": db.val("SELECT id FROM teams WHERE slug = 'agri03-team-1'"),
        "t2": db.val("SELECT id FROM teams WHERE slug = 'agri03-team-2'"),
        "school": db.val("SELECT id FROM schools WHERE name = 'Columbia Demo High School'"),
    }


# ---------- device API ----------

def test_gateway_ingest_writes_tray_feeds(client, app, db):
    key = device_key(app, "GW-DEMO")
    body = {"firmware": "1.0.1", "readings": [{"node": "ND-DEMB", "moisture": 21.5, "temp": 19.2, "ec": 410, "ph": 6.5, "n": 37, "p": 12, "k": 94, "rssi": -81}]}
    r = client.post("/api/v1/ingest", json=body, headers={"X-Device-Key": key})
    assert r.status_code == 200 and r.json["stored"] == 7
    db.con.commit()
    v = db.val("SELECT last_value FROM feeds WHERE key LIKE '%.tray-b.moisture'")
    assert v == "21.5"
    assert db.val("SELECT rssi FROM devices WHERE serial = 'ND-DEMB'") == -81


def test_dry_soil_skips_ec_and_raises_alert(client, app, db):
    key = device_key(app, "ND-DEMA")
    r = client.post("/api/v1/ingest", json={"moisture": 6.0, "temp": 20, "ec": 55, "ph": 6.8}, headers={"X-Device-Key": key})
    assert r.json["stored"] == 3          # moisture, temp, ph; EC dropped
    assert db.val("SELECT COUNT(*) AS n FROM alerts WHERE kind = 'too_dry' AND resolved_at IS NULL") == 1


def test_bad_key_and_unclaimed(client):
    assert client.post("/api/v1/ingest", json={}, headers={"X-Device-Key": "nope"}).status_code == 401
    assert client.post("/api/v1/ingest", json={}).status_code == 401


def test_sensor_fault(client, app, db):
    r = client.post("/api/v1/ingest", json={"fault": True}, headers={"X-Device-Key": device_key(app, "ND-DEMC")})
    assert r.status_code == 200
    assert db.val("SELECT COUNT(*) AS n FROM alerts WHERE kind = 'sensor_fault'") == 1


# ---------- bench pump: request -> approve -> command ----------

def test_pump_request_approve_command(client, app, db):
    i = ids(db)
    tok = login_student(client, db, "Sofia R.")      # team 2 already has a pending request in the demo
    r = client.post("/me/tray", data={"_csrf": tok, "do": "water", "seconds": "30", "reason": "dry"}, follow_redirects=True)
    assert "already has a request waiting" in r.get_data(as_text=True)
    client.post("/logout", data={"_csrf": tok})
    tok = login_student(client, db, "Maya L.")
    r = client.post("/me/tray", data={"_csrf": tok, "do": "water", "seconds": "999", "reason": "x"}, follow_redirects=True)
    assert "Pick between 1 and 300 seconds" in r.get_data(as_text=True)
    client.post("/me/tray", data={"_csrf": tok, "do": "water", "seconds": "45", "reason": "12 %"})
    client.post("/logout", data={"_csrf": tok})

    tok = login(client, "teacher")
    reqs = db.q("SELECT * FROM pump_requests WHERE class_id = ? AND status = 'pending' ORDER BY created_at", i["cls"])
    assert len(reqs) == 2
    client.post(f"/teach/{i['cls']}/pump/{reqs[0]['id']}", data={"_csrf": tok, "do": "approve"})
    r = client.post(f"/teach/{i['cls']}/pump/{reqs[1]['id']}", data={"_csrf": tok, "do": "approve"}, follow_redirects=True)
    assert "Another tray is being watered" in r.get_data(as_text=True)      # one tray at a time
    pump = device_key(app, "PM-DEMO")
    cmds = client.get("/api/v1/commands", headers={"X-Device-Key": pump}).json["commands"]
    assert cmds == ["RUN,40,B"]
    assert client.get("/api/v1/commands", headers={"X-Device-Key": pump}).json["commands"] == []    # delivered once
    client.post(f"/teach/{i['cls']}/stop", data={"_csrf": tok})
    assert client.get("/api/v1/commands", headers={"X-Device-Key": pump}).json["commands"] == ["STOP"]
    assert db.val("SELECT status FROM pump_requests WHERE id = ?", reqs[0]["id"]) == "stopped"


def test_student_cannot_approve(client, db):
    i = ids(db)
    tok = login_student(client, db)
    rid = db.val("SELECT id FROM pump_requests WHERE status = 'pending'")
    r = client.post(f"/teach/{i['cls']}/pump/{rid}", data={"_csrf": tok, "do": "approve"})
    assert r.status_code in (302, 403)
    assert db.val("SELECT status FROM pump_requests WHERE id = ?", rid) == "pending"


def test_simulated_class_waters_simulation(client, db):
    i = ids(db)
    tok = login_student(client, db, "Liam T.", code="AGRI05")
    client.post("/me/tray", data={"_csrf": tok, "do": "water", "seconds": "60", "reason": "dry spell"})
    client.post("/logout", data={"_csrf": tok})
    tok = login(client, "teacher")
    before = client.get(f"/api/class/{i['sim']}/live").json
    rid = db.val("SELECT id FROM pump_requests WHERE class_id = ? AND status = 'pending'", i["sim"])
    client.post(f"/teach/{i['sim']}/pump/{rid}", data={"_csrf": tok, "do": "approve"})
    assert db.val("SELECT simulated FROM pump_requests WHERE id = ?", rid) == 1
    assert db.val("SELECT COUNT(*) AS n FROM commands") == 0          # no real pump command
    after = client.get(f"/api/class/{i['sim']}/live").json
    tray = db.val("SELECT tray_id FROM pump_requests WHERE id = ?", rid)
    b = next(t for t in before["trays"] if t["id"] == tray)["moisture"]
    a = next(t for t in after["trays"] if t["id"] == tray)["moisture"]
    assert after["simulated"] and a > b


# ---------- IoT Studio: switches, safety, actions, team key ----------

def test_studio_toggle_locked_then_unlocked(client, app, db):
    i = ids(db)
    tok = login_student(client, db)
    r = client.post(f"/api/studio/{i['t1']}/set", json={"feed": "agri03-team-1.fan", "value": "ON"}, headers={"X-CSRF": tok})
    assert r.status_code == 409 and "locked" in r.json["error"]
    assert client.post(f"/api/studio/{i['t1']}/set", json={"feed": "agri03-team-1.fan", "value": "OFF"}, headers={"X-CSRF": tok}).json["ok"]
    client.post("/logout", data={"_csrf": tok})
    tok = login(client, "teacher")
    client.post(f"/teach/{i['cls']}/settings", data={"_csrf": tok, "do": "unlock", "minutes": "40"})
    client.post("/logout", data={"_csrf": tok})
    tok = login_student(client, db)
    r = client.post(f"/api/studio/{i['t1']}/set", json={"feed": "agri03-team-1.fan", "value": "ON"}, headers={"X-CSRF": tok})
    assert r.json["ok"] and r.json["value"] == "ON"
    trainer = device_key(app, "TR-DEM1")
    cmds = client.get("/api/v1/commands", headers={"X-Device-Key": trainer}).json
    assert "SET,fan,ON" in cmds["commands"] and "pump" in cmds["config"]["components"]
    # other team's outputs are off limits
    r = client.post(f"/api/studio/{i['t2']}/set", json={"feed": "agri03-team-2.fan", "value": "ON"}, headers={"X-CSRF": tok})
    assert r.status_code == 403
    # sensors can't be switched
    r = client.post(f"/api/studio/{i['t1']}/set", json={"feed": "agri03-team-1.moisture", "value": "ON"}, headers={"X-CSRF": tok})
    assert r.status_code == 409


def test_trainer_pump_rules(client, app, db):
    i = ids(db)
    tok = login(client, "teacher")      # teachers may switch without unlocking
    s = lambda v: client.post(f"/api/studio/{i['t1']}/set", json={"feed": "agri03-team-1.pump", "value": v}, headers={"X-CSRF": tok})
    # the demo pump went OFF moments ago -> resting
    assert "resting" in s("ON").json["error"]
    db.run("UPDATE datapoints SET created_at = '2020-01-01T00:00:00Z' WHERE value = 'OFF'")
    db.commit()
    assert s("ON").json["ok"]
    cmds = client.get("/api/v1/commands", headers={"X-Device-Key": device_key(app, "TR-DEM1")}).json["commands"]
    assert cmds == ["SET,pump,ON,30"]
    s("OFF")
    # tank low blocks the pump
    client.post("/api/v1/ingest", json={"feeds": {"tank": "LOW"}}, headers={"X-Device-Key": device_key(app, "TR-DEM1")})
    db.run("UPDATE datapoints SET created_at = '2020-01-01T00:00:00Z' WHERE value = 'OFF'")
    db.commit()
    assert "Tank level is LOW" in s("ON").json["error"]


def test_action_fires_fan_and_pump_needs_approval(client, app, db):
    i = ids(db)
    trainer = device_key(app, "TR-DEM1")
    db.run("UPDATE datapoints SET created_at = '2020-01-01T00:00:00Z' WHERE value = 'OFF'")
    db.run("UPDATE actions SET start_hhmm = '00:00', end_hhmm = '23:59'")
    db.commit()
    post = lambda feeds: client.post("/api/v1/ingest", json={"feeds": feeds}, headers={"X-Device-Key": trainer}).json["commands"]
    cmds = post({"air-temp": 33.0, "moisture": 9.0})      # queued commands come back in the same response
    assert "SET,fan,ON,30" in cmds and not any("pump" in c for c in cmds)       # pump rule not approved yet
    tok = login(client, "teacher")
    aid = db.val("SELECT id FROM actions WHERE name = 'Water when dry'")
    client.post(f"/teach/{i['cls']}/settings", data={"_csrf": tok, "do": "approve_action", "action_id": aid})
    assert "SET,pump,ON,20" in post({"moisture": 8.5})
    # cooldown: a second low reading straight away does nothing
    assert post({"moisture": 8.0}) == []


def test_student_creates_dashboard_block_feed_action_and_key(client, db):
    tok = login_student(client, db)
    r = client.post("/studio/new", data={"_csrf": tok, "name": "Mine", "starter": "1"})
    did = r.headers["Location"].rsplit("/", 1)[-1]
    client.post(f"/studio/dash/{did}", data={"_csrf": tok, "do": "add", "type": "value", "feed": "agri03-team-1.pressure", "title": "P"})
    blocks = json.loads(db.val("SELECT blocks FROM dashboards WHERE id = ?", did))
    assert len(blocks) == 8 and blocks[-1]["title"] == "P"
    client.post("/studio/feeds", data={"_csrf": tok, "name": "Plant height", "unit": "cm"})
    client.post("/studio/feeds/agri03-team-1.plant-height", data={"_csrf": tok, "value": "4.5"})
    assert db.val("SELECT last_value FROM feeds WHERE key = 'agri03-team-1.plant-height'") == "4.5"
    client.post("/studio/actions", data={"_csrf": tok, "do": "create", "name": "Beep", "feed_key": "agri03-team-1.pressure", "op": "gt",
                                         "threshold": "150", "effect": "beep", "rest_seconds": "10"})
    assert db.val("SELECT rest_seconds FROM actions WHERE name = 'Beep'") == 60          # minimum rest enforced
    html = client.post("/studio/code", data={"_csrf": tok, "do": "new"}).get_data(as_text=True)
    key = html.split('<pre id="key">')[1].split("<")[0]
    r = client.post("/api/v1/feeds/plant-height/data", json={"value": 5.1}, headers={"X-Team-Key": key})
    assert r.json["ok"]
    assert client.get("/api/v1/feeds/agri03-team-1.plant-height/data/last", headers={"X-Team-Key": key}).json["value"] == "5.1"
    r = client.post("/api/v1/feeds/fan/data", json={"value": "ON"}, headers={"X-Team-Key": key})
    assert r.status_code == 409          # controls still locked
    assert client.get("/api/v1/feeds/agri03-team-2.fan/data/last", headers={"X-Team-Key": key}).status_code == 404
    assert client.get("/api/v1/feeds", headers={"X-Team-Key": "bad"}).status_code == 401


# ---------- journal + grading ----------

def test_journal_submit_and_grade(client, db):
    i = ids(db)
    tok = login_student(client, db)
    aid = db.val("SELECT id FROM assignments WHERE class_id = ?", i["cls"])
    client.post(f"/me/journal/{aid}", data={"_csrf": tok, "do": "submit", "claim": "Sand dries fastest", "evidence": "A fell 12 % in 24 h",
                                           "reasoning": "Big pores", "row_time": ["Mon 9:00", ""], "row_value": ["21", ""], "row_note": ["", ""]})
    jid = db.val("SELECT id FROM journals WHERE assignment_id = ?", aid)
    assert db.val("SELECT status FROM journals WHERE id = ?", jid) == "submitted"
    client.post("/logout", data={"_csrf": tok})
    tok = login(client, "teacher")
    client.post(f"/teach/{i['cls']}/gradebook", data={"_csrf": tok, "journal_id": jid, "do": "grade", "score": "18", "feedback": "Good"})
    assert db.val("SELECT score FROM journals WHERE id = ?", jid) == 18
    client.post("/logout", data={"_csrf": tok})
    login(client, "parent")
    assert "18/20" in client.get("/me/parent").get_data(as_text=True)


# ---------- admin: claim, class, students, roles ----------

def test_claim_device_and_add_class_and_students(client, db):
    i = ids(db)
    tok = login(client, "admin")
    r = client.post(f"/admin/devices/claim?school={i['school']}", data={"_csrf": tok, "serial": "ND-NEW1", "claim_code": "WRONG"}, follow_redirects=True)
    assert "don't match" in r.get_data(as_text=True).replace("&#39;", "'")
    client.post(f"/admin/devices/claim?school={i['school']}", data={"_csrf": tok, "serial": "nd-new1", "claim_code": "test-claim"})
    assert db.val("SELECT school_id FROM devices WHERE serial = 'ND-NEW1'") == i["school"]
    client.post(f"/admin/classes?school={i['school']}", data={"_csrf": tok, "name": "Period 7", "teams": "3"})
    cid = db.val("SELECT id FROM classes WHERE name = 'Period 7'")
    assert db.val("SELECT COUNT(*) AS n FROM teams WHERE class_id = ?", cid) == 3
    html = client.post(f"/admin/students?school={i['school']}", data={"_csrf": tok, "class_id": cid, "names": "Grace Hopper\nAlan Turing\n"}).get_data(as_text=True)
    assert "Grace H." in html and "Alan T." in html
    assert db.val("SELECT COUNT(*) AS n FROM users WHERE name = 'Grace H.'") == 1     # surname never stored
    r = client.post(f"/admin/staff?school={i['school']}", data={"_csrf": tok, "name": "Sub", "email": "sub@x.org", "role": "substitute", "class_id": cid, "days": "2"})
    assert r.status_code == 302
    assert db.val("SELECT expires_at FROM memberships m JOIN users u ON u.id = m.user_id WHERE u.email = 'sub@x.org'") is not None
    r = client.post(f"/admin/staff?school={i['school']}", data={"_csrf": tok, "name": "X", "email": "x@x.org", "role": "owner"})
    assert r.status_code == 403        # school admins can't make AgriSense staff


def test_teacher_cannot_change_school_settings(client, db):
    i = ids(db)
    tok = login(client, "teacher")
    r = client.post(f"/admin/settings?school={i['school']}", data={"_csrf": tok, "pump_max_seconds": "300"})
    assert r.status_code == 403


def test_support_needs_grant(client, db):
    i = ids(db)
    login(client, "support")
    assert client.get(f"/staff/school/{i['school']}").status_code == 403
    client.post("/logout", data={"_csrf": csrf(client, "/")})
    tok = login(client, "admin")
    client.post(f"/admin/privacy?school={i['school']}", data={"_csrf": tok, "do": "support", "ticket": "T-42", "hours": "4"})
    client.post("/logout", data={"_csrf": tok})
    login(client, "support")
    assert client.get(f"/staff/school/{i['school']}").status_code == 200
    assert db.val("SELECT COUNT(*) AS n FROM audit_log WHERE action = 'support.view'") == 1


def test_signup_creates_school(client, db):
    tok = csrf(client, "/signup")
    r = client.post("/signup", data={"_csrf": tok, "name": "New T", "email": "new@school.org", "password": "longpassword1",
                                     "school": "Rock Bridge HS", "state": "MO"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/")
    assert db.val("SELECT COUNT(*) AS n FROM schools WHERE name = 'Rock Bridge HS'") == 1


def test_inventory_and_invoice(client, db):
    tok = login(client, "owner")
    r = client.post("/staff/inventory", data={"_csrf": tok, "kind": "trainer", "count": "3", "fmt": "csv"})
    lines = r.get_data(as_text=True).strip().splitlines()
    assert lines[0] == "serial,kind,claim_code,device_key" and len(lines) == 4
    org = db.val("SELECT id FROM orgs WHERE kind = 'client'")
    client.post("/staff/invoices", data={"_csrf": tok, "do": "create", "org_id": org, "kind": "quote", "desc": ["Kit", "Licence"], "qty": ["2", "2"], "unit": ["3400", "1200"]})
    assert db.val("SELECT amount_cents FROM invoices WHERE kind = 'quote'") == 920000


# ---------- exports ----------

def test_exports(client, db):
    login(client, "teacher")
    keys = [r["key"] for r in db.q("SELECT key FROM feeds WHERE key LIKE '%.tray-a.moisture' OR key LIKE '%.tray-a.ec'")]
    q = "&".join(f"feed={k}" for k in keys)
    r = client.get(f"/data/download?{q}&range=48h&fmt=csv")
    text = r.get_data(as_text=True)
    assert r.status_code == 200 and text.lstrip("﻿").startswith("time_utc,school")
    assert text.count("\n") > 300
    r = client.get(f"/data/download?{q}&range=48h&fmt=xlsx")
    wb = load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == ["Readings", "About"] and wb["Readings"].max_row > 300
    r = client.get(f"/data/download?{q}&range=24h&fmt=json")
    assert r.json["rows"] and r.json["names"] == "removed"


def test_observer_gets_deidentified_only(client, db):
    login(client, "observer")
    html = client.get("/data/").get_data(as_text=True)
    assert "Include names" not in html
    key = db.val("SELECT key FROM feeds WHERE key LIKE '%.tray-a.moisture'")
    r = client.get(f"/data/download?feed={key}&fmt=json&named=1")
    assert r.json["names"] == "removed"
