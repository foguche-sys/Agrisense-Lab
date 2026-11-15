import re

from conftest import device_key
from agrisense.db import ahead


def _trainer(db):
    return db.one("SELECT * FROM devices WHERE kind = 'trainer' AND team_id IS NOT NULL LIMIT 1")


def _key(app, dev):
    return device_key(app, dev["serial"])


def test_trainer_learns_the_teacher_unlock(app, client, db):
    dev = _trainer(db)
    key = _key(app, dev)
    r = client.get("/api/v1/commands", headers={"X-Device-Key": key}).get_json()
    assert r["student"]["unlocked_s"] == 0                                   # locked by default
    cls_id = db.val("SELECT class_id FROM teams WHERE id = ?", dev["team_id"])
    db.run("UPDATE classes SET controls_unlocked_until = ? WHERE id = ?", ahead(minutes=10), cls_id); db.commit()
    r = client.post("/api/v1/ingest", json={"feeds": {"moisture": 21}}, headers={"X-Device-Key": key}).get_json()
    assert 590 <= r["student"]["unlocked_s"] <= 600


def test_student_events_are_logged_for_the_teacher(app, client, db):
    dev = _trainer(db)
    key = _key(app, dev)
    client.post("/api/v1/ingest", json={"feeds": {}, "student_event": "pump_ok:10"}, headers={"X-Device-Key": key})
    client.post("/api/v1/ingest", json={"feeds": {}, "student_event": "refused:11"}, headers={"X-Device-Key": key})
    client.post("/api/v1/ingest", json={"feeds": {}, "student_event": "nonsense"}, headers={"X-Device-Key": key})
    logs = [r["detail"] for r in db.q("SELECT detail FROM audit_log WHERE action LIKE 'student.%' ORDER BY created_at")]
    assert any("ran the pump for 10 s" in l for l in logs) and any("too long" in l for l in logs)
    slug = db.val("SELECT slug FROM teams WHERE id = ?", dev["team_id"])
    assert db.val("SELECT last_value FROM feeds WHERE key = ?", f"{slug}.pump") == "ON"


def test_deck_posts_over_wifi_without_a_gateway(app, client, db):
    deck = db.one("SELECT * FROM devices WHERE kind = 'deck' LIMIT 1")
    if not deck:
        return
    m = re.search(rf"{deck['serial']}: (\S+)", app.config["DEMO_OUT"])
    if not m or not deck["tray_id"]:
        return
    r = client.post("/api/v1/ingest", json={"firmware": "deck-1.0.0", "moisture": 27.5, "temp": 18, "ec": 300, "ph": 6.6},
                    headers={"X-Device-Key": m.group(1)}).get_json()
    assert r["ok"] and r["stored"] >= 4


def test_library_download_is_served(client):
    r = client.get("/static/downloads/AgriSenseStudent.zip")
    assert r.status_code == 200 and r.data[:2] == b"PK"
