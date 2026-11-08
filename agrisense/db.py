"""Database access for SQLite (local / tests) and PostgreSQL (production).

All SQL in the app is written with "?" placeholders and portable types; this module
converts placeholders for PostgreSQL. Rows come back as plain dicts.
"""
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import current_app, g

_SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")
_trace_lock = threading.Lock()


def now(dt=None):
    """UTC timestamp string used everywhere, e.g. 2026-11-08T06:20:00Z."""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def ago(seconds=0, minutes=0, hours=0, days=0):
    return now(datetime.now(timezone.utc) - timedelta(seconds=seconds, minutes=minutes, hours=hours, days=days))


def ahead(seconds=0, minutes=0, hours=0, days=0):
    return now(datetime.now(timezone.utc) + timedelta(seconds=seconds, minutes=minutes, hours=hours, days=days))


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Database:
    def __init__(self, url):
        self.url = url
        self.pg = url.startswith("postgres")

    def connect(self):
        if self.pg:
            import psycopg  # installed in production (requirements.txt)
            from psycopg.rows import dict_row
            return psycopg.connect(self.url, row_factory=dict_row, autocommit=False)
        path = self.url.replace("sqlite:///", "", 1)
        con = sqlite3.connect(path, check_same_thread=False, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def schema_sql(self):
        sql = open(_SCHEMA).read()
        return sql.replace("{AUTOID}", "BIGSERIAL PRIMARY KEY" if self.pg else "INTEGER PRIMARY KEY AUTOINCREMENT")

    # Columns added after the first release. New databases get them from schema.sql;
    # existing ones get them here, so redeploying never loses data.
    MIGRATIONS = [
        ("trays", "crop", "TEXT"),
        ("pump_requests", "prediction", "REAL"),
        ("pump_requests", "moisture_after", "REAL"),
        ("pump_requests", "checked_at", "TEXT"),
    ]

    def init_schema(self):
        con = self.connect()
        try:
            if self.pg:
                with con.cursor() as cur:
                    cur.execute(self.schema_sql())
                    for table, col, typ in self.MIGRATIONS:
                        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {typ}")
            else:
                con.executescript(self.schema_sql())
                for table, col, typ in self.MIGRATIONS:
                    if col not in [r[1] for r in con.execute(f"PRAGMA table_info({table})")]:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            con.commit()
        finally:
            con.close()


_PH = re.compile(r"\?")


def pg_sql(sql):
    """Turn our "?" SQL into psycopg's format. A literal % (as in LIKE '%.pump') must be doubled,
    or psycopg reads it as the start of a placeholder and the query fails."""
    return _PH.sub("%s", sql.replace("%", "%%"))


class Conn:
    """Thin wrapper used through get_db(): q(), one(), run(), commit()."""

    def __init__(self, database, trace=None):
        self.database = database
        self.con = database.connect()
        self.trace = trace

    def _sql(self, sql):
        return pg_sql(sql) if self.database.pg else sql

    def _exec(self, sql, params=()):
        if self.trace is not None:
            with _trace_lock:
                self.trace.append((sql, tuple(params)))
        if self.database.pg:
            cur = self.con.cursor()
            cur.execute(self._sql(sql), params)
            return cur
        return self.con.execute(sql, params)

    def q(self, sql, *params):
        cur = self._exec(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def one(self, sql, *params):
        cur = self._exec(sql, params)
        r = cur.fetchone()
        return dict(r) if r else None

    def val(self, sql, *params):
        r = self.one(sql, *params)
        return next(iter(r.values())) if r else None

    def run(self, sql, *params):
        self._exec(sql, params)

    def insert(self, table, **cols):
        keys = list(cols)
        sql = f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})"
        self.run(sql, *[cols[k] for k in keys])
        return cols.get("id")

    def update(self, table, id_, **cols):
        keys = list(cols)
        sql = f"UPDATE {table} SET {', '.join(k + ' = ?' for k in keys)} WHERE id = ?"
        self.run(sql, *[cols[k] for k in keys], id_)

    def commit(self):
        self.con.commit()

    def rollback(self):
        self.con.rollback()

    def close(self):
        self.con.close()


def get_db():
    if "db" not in g:
        g.db = Conn(current_app.extensions["agrisense_db"], current_app.config.get("SQL_TRACE"))
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        if exc is None:
            db.commit()
        else:
            db.rollback()
        db.close()


def jload(s, default=None):
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def jdump(o):
    return json.dumps(o, separators=(",", ":"))
