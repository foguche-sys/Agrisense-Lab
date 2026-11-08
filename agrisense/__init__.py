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
        if not app.config.get("TESTING") and os.environ.get("AUTO_HOUSEKEEPING", "1") == "1":
            from .services.housekeeping import maybe_run
            maybe_run(database)
        auth.load_user()
        auth.check_csrf()
        u = g.user
        if u and u["must_change_password"] and u["email"] and request.endpoint not in ("public.account", "public.logout", "static"):
            from flask import redirect, url_for
            return redirect(url_for("public.account"))

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

    @app.errorhandler(500)
    def _server_error(e):
        if request.path.startswith("/api/"):
            return {"ok": False, "error": "Server error. It has been logged; try again in a minute."}, 500
        return render_template("error.html", code=500, title="Something went wrong on our side",
                               text="It has been logged. Try again in a minute; if it keeps happening, email " + app.config["SUPPORT_EMAIL"] + "."), 500

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
        """Create tables and load lessons and plans. Safe to run on every start.

        On a first deploy it also creates the AgriSense owner account from OWNER_EMAIL / OWNER_PASSWORD,
        and loads the demo school when SEED_DEMO=1."""
        database.init_schema()
        with app.app_context():
            from .services.catalog import seed_catalog
            db = get_db()
            seed_catalog(db)
            email = (os.environ.get("OWNER_EMAIL") or "").strip().lower()
            pw = os.environ.get("OWNER_PASSWORD") or ""
            if email and pw and not db.val("SELECT id FROM users WHERE email = ?", email):
                if len(pw) < 10:
                    click.echo("OWNER_PASSWORD must be at least 10 characters; owner not created.")
                else:
                    from .seed import ensure_platform_org
                    org = ensure_platform_org(db)
                    uid = auth.create_user(db, os.environ.get("OWNER_NAME") or "AgriSense owner", email, pw)
                    auth.add_membership(db, uid, "owner", org_id=org)
                    click.echo(f"Owner account created for {email}.")
            if os.environ.get("SEED_DEMO") == "1":
                from .seed import run
                click.echo(run(db).splitlines()[0])
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
        from .services.housekeeping import run as hk
        with app.app_context():
            stale, pruned = hk(get_db())
        click.echo(f"{stale} devices marked offline, {pruned} old readings removed.")

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
