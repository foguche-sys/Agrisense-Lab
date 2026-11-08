def test_housekeeping_marks_offline(app, db):
    db.run("UPDATE devices SET last_seen = '2020-01-01T00:00:00Z' WHERE serial = 'GW-DEMO'")
    db.commit()
    out = app.test_cli_runner().invoke(args=["housekeeping"]).output
    assert "devices marked offline" in out
    assert db.val("SELECT status FROM devices WHERE serial = 'GW-DEMO'") == "offline"
    assert db.val("SELECT COUNT(*) AS n FROM alerts WHERE kind = 'offline'") >= 1


def test_init_db_is_idempotent(app):
    r = app.test_cli_runner()
    assert "Database ready" in r.invoke(args=["init-db"]).output
    assert "already loaded" in r.invoke(args=["seed-demo"]).output
