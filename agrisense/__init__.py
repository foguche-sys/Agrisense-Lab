"""AgriSense Lab platform: schools, classes, live soil benches, IoT Studio, data and billing."""
import os
from datetime import timedelta

import click
from flask import Flask, g, render_template, request

from . import auth
from .db import Database, close_db, get_db, jload, parse_ts


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE_URL=os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(app.instance_path, "agrisense.db")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=10),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        SITE_NAME="AgriSense Lab",
        SUPPORT_EMAIL=os.environ.get("SUPPORT_EMAIL", "support@agrisensehub.com"),
        SQL_TRACE=None,
    )
    if test_config:
        app.config.update(test_config)
    if app.config["SECRET_KEY"] == "dev-only-change-me" and os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("Set SECRET_KEY in production.")

    database = Database(app.config["DATABASE_URL"])
    app.extensions["agrisense_db"] = database

    @app.before_request
    def _before():
        auth.load_user()
        auth.check_csrf()

    app.teardown_appcontext(close_db)

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'")
        return resp

    @app.context_processor
    def _globals():
        from .rbac import ROLES, roles_of
        mine = roles_of(getattr(g, "memberships", []) or [])
        return {"csrf_token": auth.csrf_token, "any_role": lambda *r: bool(mine & set(r)), "allowed": auth.allowed, "ROLES": ROLES,
                "my_roles": mine, "site": app.config["SITE_NAME"]}

    @app.template_filter("ago")
    def _ago(ts):
        from .db import now
        if not ts:
            return "never"
        s = int((parse_ts(now()) - parse_ts(ts)).total_seconds())
        if s < 60:
            return f"{max(s, 0)} s ago"
        if s < 3600:
            return f"{s // 60} min ago"
        if s < 86400:
            return f"{s // 3600} h ago"
        return f"{s // 86400} d ago"

    @app.template_filter("money")
    def _money(cents):
        return "Quote" if cents is None else f"${cents / 100:,.2f}"

    @app.template_filter("jload")
    def _jload(s):
        return jload(s, [])

    from .routes import admin, api, data, public, staff, student, studio, teacher
    for bp in (public.bp, admin.bp, teacher.bp, student.bp, studio.bp, data.bp, staff.bp, api.bp):
        app.register_blueprint(bp)

    for code, title, text in [(401, "Please sign in", "Your session ended. Sign in again."), (400, "Something went wrong", None), (403, "You don't have access to this page",
                               "Ask your teacher or school admin if you think you should."),
                              (404, "Page not found", "Check the link, or go back to your home page.")]:
        def handler(e, code=code, title=title, text=text):
            if request.path.startswith("/api/"):
                return {"ok": False, "error": getattr(e, "description", title)}, code
            return render_template("error.html", code=code, title=title,
                                   text=text or getattr(e, "description", "")), code
        app.register_error_handler(code, handler)

    @app.cli.command("init-db")
    def init_db():
        """Create tables and load lessons and plans."""
        database.init_schema()
        with app.app_context():
            from .services.catalog import seed_catalog
            seed_catalog(get_db())
        click.echo("Database ready.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Load a demo school with classes, teams, devices and two days of readings."""
        from .seed import run
        with app.app_context():
            click.echo(run(get_db()))

    @app.cli.command("housekeeping")
    def housekeeping():
        """Run every few minutes (cron): mark silent devices offline, add offline alerts, apply data retention."""
        from .db import ago, new_id, now
        from .services.safety import auto_off_due, school_settings
        with app.app_context():
            db = get_db()
            auto_off_due(db)
            stale = db.q("SELECT * FROM devices WHERE status = 'online' AND last_seen < ?", ago(minutes=15))
            for d in stale:
                db.update("devices", d["id"], status="offline")
                db.insert("alerts", id=new_id("al"), school_id=d["school_id"], device_id=d["id"], kind="offline",
                          message=f"{d['serial']} hasn't reported for 15 minutes. Check power and Wi-Fi.", created_at=now())
            pruned = 0
            for s in db.q("SELECT id FROM schools"):
                days = school_settings(db, s["id"]).get("retention_days", 365)
                cutoff = ago(days=days)
                ids = [r["id"] for r in db.q("SELECT f.id FROM feeds f LEFT JOIN kits k ON k.id = f.kit_id LEFT JOIN teams t ON t.id = f.team_id "
                                             "LEFT JOIN classes c ON c.id = t.class_id WHERE COALESCE(f.school_id, k.school_id, c.school_id) = ?", s["id"])]
                for fid in ids:
                    pruned += db.val("SELECT COUNT(*) AS n FROM datapoints WHERE feed_id = ? AND created_at < ?", fid, cutoff) or 0
                    db.run("DELETE FROM datapoints WHERE feed_id = ? AND created_at < ?", fid, cutoff)
            db.run("DELETE FROM commands WHERE expires_at < ?", ago(days=2))
        click.echo(f"{len(stale)} devices marked offline, {pruned} old readings removed.")

    @app.cli.command("create-owner")
    @click.argument("email")
    @click.argument("name")
    def create_owner(email, name):
        """Create the first AgriSense Hub owner account (asks for a password)."""
        from .seed import ensure_platform_org
        pw = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        with app.app_context():
            db = get_db()
            org = ensure_platform_org(db)
            uid = auth.create_user(db, name, email, pw)
            auth.add_membership(db, uid, "owner", org_id=org)
        click.echo("Owner created.")

    return app
