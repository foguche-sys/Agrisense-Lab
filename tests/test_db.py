from agrisense.db import pg_sql


def test_pg_sql_escapes_literal_percent():
    assert pg_sql("SELECT * FROM feeds WHERE key LIKE '%.pump' AND id = ?") == "SELECT * FROM feeds WHERE key LIKE '%%.pump' AND id = %s"
    assert pg_sql("SELECT 1") == "SELECT 1"
