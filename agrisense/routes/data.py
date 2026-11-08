"""Data explorer: pick trays/feeds and a time range, see the chart, download CSV / Excel / JSON."""
from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for

from .. import auth
from ..db import ago, now
from ..rbac import classes_for, schools_for
from ..services import exports
from ..services.audit import log
from .util import db, student_team

bp = Blueprint("data", __name__, url_prefix="/data")

RANGES = {"1h": 1, "24h": 24, "48h": 48, "7d": 168, "30d": 720, "all": None}


@bp.before_request
def _signed_in():
    if not g.user:
        return redirect(url_for("public.login", next=request.path))


def visible_feeds():
    """Feeds this user may see, with how they may export them: 'named', 'deid' or 'team'."""
    d = db()
    cls, team = student_team()
    if team:
        rows = d.q("SELECT * FROM feeds WHERE team_id = ? OR (tray_id IS NOT NULL AND tray_id IN "
                   "(SELECT tr.id FROM trays tr JOIN classes c ON c.kit_id = tr.kit_id WHERE c.id = ?)) ORDER BY key",
                   team["id"], cls["id"])
        return rows, "team"
    sids = schools_for(d, g.memberships)
    rows, mode = [], None
    for sid in sids:
        if auth.allowed("export.named", school_id=sid):
            mode = "named"
        elif auth.allowed("export.deid", school_id=sid) and mode is None:
            mode = "deid"
    for cid in classes_for(d, g.memberships):
        if auth.allowed("export.named", class_id=cid):
            mode = "named"
        elif auth.allowed("export.deid", class_id=cid) and mode is None:
            mode = "deid"
    if mode is None:
        abort(403)
    if sids:
        ph = ",".join("?" for _ in sids)
        rows = d.q(f"""SELECT f.* FROM feeds f LEFT JOIN kits k ON k.id = f.kit_id LEFT JOIN teams t ON t.id = f.team_id
                       LEFT JOIN classes c ON c.id = t.class_id
                       WHERE COALESCE(f.school_id, k.school_id, c.school_id) IN ({ph}) ORDER BY f.key""", *sids)
    return rows, mode


@bp.route("/")
def explorer():
    feeds, mode = visible_feeds()
    chosen = [k for k in request.args.getlist("feed") if any(f["key"] == k for f in feeds)]
    if not chosen:
        chosen = [f["key"] for f in feeds if f["key"].endswith(".moisture")][:5]
    rng = request.args.get("range", "48h")
    groups = {}
    for f in feeds:
        groups.setdefault(f["key"].rsplit(".", 1)[0], []).append(f)
    return render_template("data/explorer.html", groups=groups, chosen=chosen, rng=rng, ranges=RANGES, mode=mode)


@bp.route("/download")
def download():
    feeds, mode = visible_feeds()
    keys = request.args.getlist("feed")
    ids = [f["id"] for f in feeds if f["key"] in keys]
    if not ids:
        abort(400, "Choose at least one feed to download.")
    rng = request.args.get("range", "48h")
    hours = RANGES.get(rng, 48)
    since = ago(hours=hours) if hours else None
    named = mode == "named" and request.args.get("named") == "1"
    rows = exports.rows_for(db(), ids, since=since, named=named)
    fmt = request.args.get("fmt", "csv") if request.args.get("fmt") in ("csv", "xlsx", "json") else "csv"
    body, ctype = exports.render(rows, fmt, {"range": rng, "feeds": ", ".join(keys), "names": "included" if named else "removed"})
    log(db(), "data.export", f"{fmt} {len(rows)} rows {'named' if named else 'de-identified'}")
    stamp = now()[:10]
    return Response(body, mimetype=ctype, headers={"Content-Disposition": f'attachment; filename="agrisense-data-{stamp}.{fmt}"'})


@bp.route("/series")
def series():
    from flask import jsonify
    from ..services import feeds as F
    feeds, _ = visible_feeds()
    f = next((x for x in feeds if x["key"] == request.args.get("feed")), None)
    if not f:
        abort(404)
    hours = RANGES.get(request.args.get("range", "48h"), 48)
    pts = F.history(db(), f["id"], since=ago(hours=hours) if hours else None, limit=3000)
    return jsonify({"ok": True, "points": [{"t": p["created_at"], "v": p["num"]} for p in pts]})
