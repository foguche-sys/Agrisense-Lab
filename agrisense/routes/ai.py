"""AI Lab: five lessons where students train small models on their own bench / field readings."""
import csv
import io

from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for

from .. import auth
from ..services import ai
from .util import db, err, ok, pick_class, student_team

bp = Blueprint("ai", __name__, url_prefix="/ai")


@bp.before_request
def _signed_in():
    if not g.user:
        return redirect(url_for("public.login", next=request.path))


def ctx():
    """(cls, team, trays, tray, is_student). Students work on their own team's tray; teachers pick one."""
    d = db()
    cls, team = student_team()
    if team:
        trays = d.q("SELECT * FROM trays WHERE kit_id = ? ORDER BY letter", cls["kit_id"]) if cls["kit_id"] else []
        tray = next((t for t in trays if t["id"] == team["tray_id"]), None)
        return cls, team, trays, tray, True
    cls, _ids = pick_class()
    if not cls or not auth.allowed("live.view", class_id=cls["id"]):
        abort(403)
    trays = d.q("SELECT * FROM trays WHERE kit_id = ? ORDER BY letter", cls["kit_id"]) if cls["kit_id"] else []
    tray = next((t for t in trays if t["id"] == request.values.get("tray")), trays[0] if trays else None)
    return cls, None, trays, tray, False


def _args(cls, tray=None, **kw):
    a = {"class": cls["id"]}
    if tray:
        a["tray"] = tray["id"]
    a.update(kw)
    return a


@bp.route("/")
def hub():
    cls, team, trays, tray, is_student = ctx()
    d = db()
    preds = ai.prediction_rows(d, cls, team_id=team["id"] if team else None, limit=8)
    leaf = ai.results(d, cls, "leaf", team_id=team["id"] if team else None, limit=6)
    return render_template("ai/hub.html", cls=cls, team=team, trays=trays, tray=tray, is_student=is_student, preds=preds, leaf=leaf,
                           q=_args(cls, tray))


# ---------------------------------------------------------------- 2.1 predict
@bp.route("/predict", methods=["GET", "POST"])
def predict():
    cls, team, trays, tray, is_student = ctx()
    if not tray:
        err("There is no tray to work with yet.")
        return redirect(url_for("ai.hub", **_args(cls)))
    d = db()
    ai.check_predictions(d, cls, tray)
    p = ai.predict_tray(d, cls, tray)
    if request.method == "POST":
        if not p["ok"]:
            err(p.get("why") or "No prediction to save yet.")
        else:
            guess = request.form.get("student_hours")
            try:
                guess = round(float(guess), 1) if guess not in (None, "") else None
            except ValueError:
                guess = None
            if is_student and guess is None:
                err("Write your own guess first, before you look at the line's answer.")
                return redirect(url_for("ai.predict", **_args(cls, tray)))
            ai.save_prediction(d, cls, tray, team["id"] if team else None, g.user["id"], p, guess, request.form.get("note"))
            ok("Prediction saved. The AI Lab checks it automatically when the tray reaches the refill point.")
        return redirect(url_for("ai.predict", **_args(cls, tray)))
    chart = ""
    if p.get("xs"):
        line = [(p["xs"][0], p["a"] + p["slope"] * p["xs"][0])]
        x_end = p["xs"][-1] + (p["hours"] if p["ok"] and p["hours"] > 0 else 0)
        line.append((x_end, p["a"] + p["slope"] * x_end))
        marks = [(x_end, p["refill"], "var(--warn)")] if p["ok"] and p["hours"] > 0 else []
        chart = ai.svg_chart([("Readings", "var(--brand)", list(zip(p["xs"], p["ys"])), "dots"),
                              ("Best-fit line", "var(--info)", line, "dash")],
                             hlines=[(p["refill"], f"refill point {p['refill']} %", "var(--warn)")],
                             y_label="Moisture %", marks=marks)
    rows = ai.prediction_rows(d, cls, tray=tray, team_id=team["id"] if team else None)
    return render_template("ai/predict.html", cls=cls, team=team, trays=trays, tray=tray, is_student=is_student, p=p, chart=chart,
                           rows=rows, q=_args(cls, tray))


@bp.route("/predict.csv")
def predict_csv():
    """The exact points the line was fitted to, for Google Sheets or Excel (Insert chart > trendline)."""
    cls, team, trays, tray, is_student = ctx()
    if not tray:
        abort(404)
    p = ai.predict_tray(db(), cls, tray)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time (UTC)", "hours since watering", "moisture %", "refill point %"])
    for (t, v), x in zip(p["points"], p.get("xs") or [None] * len(p["points"])):
        w.writerow([t, "" if x is None else round(x, 3), v, p["refill"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=tray-{tray['letter']}-drying-curve.csv"})


# ---------------------------------------------------------------- 2.3 is the sensor lying?
@bp.route("/sensor")
def sensor():
    cls, team, trays, tray, is_student = ctx()
    if not tray:
        return redirect(url_for("ai.hub", **_args(cls)))
    metric = request.args.get("metric", "moisture")
    if metric not in ai.LIMITS:
        abort(400)
    hours = max(6, min(720, int(request.args.get("hours", 48) or 48)))
    pts = ai.series(db(), cls, tray, metric, hours)
    res = ai.sensor_check(pts, metric)
    chart = ""
    if pts and res.get("band"):
        xy = ai.hours_axis(pts)
        flagged = {r["t"] for r in res["rows"]}
        lo, hi = res["band"]
        t0 = xy[0][0] if xy else 0
        marks = [(x, v, "var(--bad)") for (x, v), (t, _) in zip(xy, pts) if t in flagged]
        train_end = xy[res["train_n"] - 1][0] if len(xy) >= res["train_n"] else t0
        chart = ai.svg_chart([("Readings", "var(--brand)", xy, "line")],
                             hlines=[(lo, f"learned low {lo:g}", "var(--info)"), (hi, f"learned high {hi:g}", "var(--info)")],
                             y_label=f"{metric} {ai.UNITS[metric]}", marks=marks)
        res["train_until_h"] = round(train_end, 1)
    alerts = db().q("SELECT * FROM alerts WHERE (class_id = ? OR school_id = ?) AND kind IN ('sensor_fault','no_flow','blocked','offline') "
                    "ORDER BY created_at DESC LIMIT 6", cls["id"], cls["school_id"])
    return render_template("ai/sensor.html", cls=cls, team=team, trays=trays, tray=tray, is_student=is_student, res=res, chart=chart,
                           metric=metric, hours=hours, alerts=alerts, q=_args(cls, tray))


# ---------------------------------------------------------------- 2.4 which beds behave alike?
@bp.route("/zones")
def zones():
    cls, team, trays, tray, is_student = ctx()
    k = 3 if request.args.get("k") == "3" else 2
    hours = max(12, min(720, int(request.args.get("hours", 168) or 168)))
    z = ai.zone_table(db(), cls, trays, hours, k)
    return render_template("ai/zones.html", cls=cls, team=team, trays=trays, tray=tray, is_student=is_student, z=z, k=k, hours=hours,
                           features=ai.FEATURES, q=_args(cls, tray))


# ---------------------------------------------------------------- 2.2 is this leaf healthy?
@bp.route("/leaf", methods=["GET", "POST"])
def leaf():
    cls, team, trays, tray, is_student = ctx()
    d = db()
    n = len(ai.LEAF_CLASSES)
    if request.method == "POST":
        m = []
        try:
            for i in range(n):
                m.append([max(0, min(999, int(request.form.get(f"m{i}{j}") or 0))) for j in range(n)])
            train = [max(0, min(9999, int(request.form.get(f"train{i}") or 0))) for i in range(n)]
        except ValueError:
            err("Use whole numbers in the table.")
            return redirect(url_for("ai.leaf", **_args(cls, tray)))
        score = ai.leaf_score(m)
        if not score["total"]:
            err("Fill in how many test photos the model got right and wrong.")
            return redirect(url_for("ai.leaf", **_args(cls, tray)))
        ai.save_result(d, cls, team["id"] if team else None, g.user["id"], "leaf",
                       {"matrix": m, "train": train, "score": score, "note": (request.form.get("note") or "")[:300]})
        ok(f"Saved: the model got {score['right']} of {score['total']} test photos right ({score['accuracy']} %).")
        return redirect(url_for("ai.leaf", **_args(cls, tray)))
    rows = ai.results(d, cls, "leaf", team_id=team["id"] if team else None)
    return render_template("ai/leaf.html", cls=cls, team=team, trays=trays, tray=tray, is_student=is_student, rows=rows,
                           classes=ai.LEAF_CLASSES, q=_args(cls, tray))


# ---------------------------------------------------------------- 2.5 should AI decide?
@bp.route("/decide")
def decide():
    cls, team, trays, tray, is_student = ctx()
    d = db()
    for t in trays:
        ai.check_predictions(d, cls, t)
    s = ai.decision_stats(d, cls)
    return render_template("ai/decide.html", cls=cls, team=team, trays=trays, tray=tray, is_student=is_student, s=s, q=_args(cls, tray))
