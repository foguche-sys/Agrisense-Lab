import re

import pytest

from agrisense import create_app
from agrisense.db import Conn

TRACE = []


@pytest.fixture()
def app(tmp_path):
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": f"sqlite:///{tmp_path}/t.db", "SQL_TRACE": TRACE})
    app.extensions["agrisense_db"].init_schema()
    with app.app_context():
        from agrisense.db import get_db
        from agrisense.seed import run
        db = get_db()
        app.config["DEMO_OUT"] = run(db)
        db.commit()
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    c = Conn(app.extensions["agrisense_db"])
    yield c
    c.close()


def csrf(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" content="([^"]+)"', html).group(1)


def login(client, who):
    tok = csrf(client)
    r = client.post("/login", data={"_csrf": tok, "email": f"{who}@demo.agrisensehub.com", "password": "agrisense-demo-2026"})
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    return csrf(client, "/home") if False else csrf(client, "/")


def login_student(client, db, name="Maya L.", code="AGRI03"):
    uid = db.val("SELECT u.id FROM users u JOIN memberships m ON m.user_id = u.id JOIN classes c ON c.id = m.class_id WHERE u.name = ? AND c.code = ?", name, code)
    tok = csrf(client, f"/login/class?code={code}&uid={uid}")
    r = client.post(f"/login/class?code={code}&uid={uid}", data={"_csrf": tok, "pics": "Sun,Corn"})
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    return csrf(client, "/")


def device_key(app, serial):
    m = re.search(rf"{serial}: (\S+)", app.config["DEMO_OUT"])
    return m.group(1)


def _literal(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


@pytest.fixture(autouse=True)
def _sql_trace(request):
    """With PG_TRACE_DIR set, write every SQL statement a test ran (params inlined) so
    tools/pg_replay.sh can replay it on PostgreSQL and prove the SQL is portable."""
    TRACE.clear()
    yield
    import os
    import re as _re
    from agrisense.db import pg_sql
    for sql, params in TRACE:      # what psycopg will see: only %s placeholders and %% literals
        assert not _re.search(r"%(?!s|%)", pg_sql(sql).replace("%%", "")), sql
    out = os.environ.get("PG_TRACE_DIR")
    if not out:
        return
    os.makedirs(out, exist_ok=True)
    name = request.node.nodeid.split("::")[-1].replace("/", "_").replace("[", "_").replace("]", "")
    with open(os.path.join(out, name + ".sql"), "w") as f:
        for sql, params in TRACE:
            parts = sql.split("?")
            assert len(parts) == len(params) + 1, sql
            f.write("".join(p + (_literal(params[i]) if i < len(params) else "") for i, p in enumerate(parts)).strip() + ";\n")
