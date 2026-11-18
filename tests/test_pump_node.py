"""The pump node's events, as the gateway relays them (firmware/pump_node)."""
from conftest import device_key


def _pump(app, db):
    dev = db.one("SELECT * FROM devices WHERE kind = 'pump' AND serial = 'PM-DEMO'")
    return dev, {"X-Device-Key": device_key(app, dev["serial"])}


def _open_alerts(db, dev, kind):
    return db.val("SELECT COUNT(*) FROM alerts WHERE device_id = ? AND kind = ? AND resolved_at IS NULL", dev["id"], kind)


def test_pressure_fault_raises_one_alert_and_a_good_run_clears_it(app, client, db):
    dev, h = _pump(app, db)
    for _ in range(2):                                        # the node sends each event twice
        r = client.post("/api/v1/ingest", json={"firmware": "gateway-1.0.0", "event": "pressure_fault"}, headers=h)
        assert r.status_code == 200
    assert _open_alerts(db, dev, "pressure_fault") == 1
    msg = db.val("SELECT message FROM alerts WHERE device_id = ? AND kind = 'pressure_fault'", dev["id"])
    assert "pressure sensor" in msg
    client.post("/api/v1/ingest", json={"event": "done"}, headers=h)
    assert _open_alerts(db, dev, "pressure_fault") == 0


def test_no_flow_and_blocked_still_alert(app, client, db):
    dev, h = _pump(app, db)
    for ev in ("no_flow", "blocked"):
        client.post("/api/v1/ingest", json={"event": ev}, headers=h)
        assert _open_alerts(db, dev, ev) == 1


def test_unknown_event_is_ignored(app, client, db):
    dev, h = _pump(app, db)
    r = client.post("/api/v1/ingest", json={"event": "nonsense"}, headers=h)
    assert r.status_code == 200
    assert db.val("SELECT COUNT(*) FROM alerts WHERE device_id = ?", dev["id"]) == 0
