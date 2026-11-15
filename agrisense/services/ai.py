"""AI Lab: small, explainable models trained on the class's own readings.

Everything here is plain arithmetic students can check by hand or in a spreadsheet:
  predict_tray   least-squares line through the drying curve -> hours until the refill point
  sensor_check   fixed rules vs a "learned normal" band (mean +/- 3 standard deviations)
  zones          k-means clustering of trays/nodes on moisture, EC, temperature and drying rate
  leaf_score     accuracy and per-class recall from a Teachable Machine test (confusion matrix)
"""
import math
from datetime import datetime, timedelta, timezone
from html import escape

from ..db import jdump, jload, new_id, now, parse_ts
from .agronomy import bands
from .live import tray_series

RISE = 1.0            # a jump of more than 1 % moisture between readings = a watering (the curve restarts)
LEAF_CLASSES = ["Healthy", "Yellowing (nutrients)", "Pest damage"]


# ---------------------------------------------------------------- maths
def fit_line(xs, ys):
    """Least squares y = a + b x. Returns (a, b, r2) or None."""
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return a, b, max(0.0, min(1.0, r2))


def mean_std(vals):
    if not vals:
        return None, None
    m = sum(vals) / len(vals)
    return m, math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def kmeans(rows, k, iters=25):
    """rows: list of equal-length number lists (already scaled). Deterministic start: farthest-point."""
    if not rows:
        return []
    k = max(1, min(k, len(rows)))
    d2 = lambda p, q: sum((a - b) ** 2 for a, b in zip(p, q))
    centres = [min(rows, key=lambda r: r[0])]                     # start from the driest row
    while len(centres) < k:
        centres.append(max(rows, key=lambda r: min(d2(r, c) for c in centres)))
    labels = [0] * len(rows)
    for _ in range(iters):
        labels = [min(range(k), key=lambda j: d2(r, centres[j])) for r in rows]
        new = []
        for j in range(k):
            members = [r for r, lab in zip(rows, labels) if lab == j]
            new.append([sum(c) / len(members) for c in zip(*members)] if members else centres[j])
        if new == centres:
            break
        centres = new
    return labels


# ---------------------------------------------------------------- data
def _ts(s):
    return parse_ts(s).timestamp()


def series(db, cls, tray, metric="moisture", hours=48):
    return [(p["t"], p["v"]) for p in tray_series(db, cls, tray, metric, hours) if p["v"] is not None]


def last_drying_stretch(points):
    """Keep only the readings after the most recent watering."""
    for i in range(len(points) - 1, 0, -1):
        if points[i][1] - points[i - 1][1] > RISE:
            return points[i:]
    return points


# ---------------------------------------------------------------- 1 predict
def predict_tray(db, cls, tray, hours=48):
    """Fit a straight line to the current drying curve and predict when it reaches the refill point."""
    b = bands(tray)
    pts = last_drying_stretch(series(db, cls, tray, "moisture", hours))
    out = {"refill": b["refill"], "fc": b["fc"], "wp": b["wp"], "crop": b["crop"], "points": pts, "n": len(pts), "ok": False}
    if len(pts) < 4:
        out["why"] = "Not enough readings since the last watering yet (need 4 or more)."
        return out
    t0 = _ts(pts[0][0])
    xs = [(_ts(t) - t0) / 3600 for t, _ in pts]
    ys = [v for _, v in pts]
    if xs[-1] - xs[0] < 0.5:
        out["why"] = "The readings cover less than half an hour. Wait a little longer."
        return out
    fit = fit_line(xs, ys)
    a, slope, r2 = fit
    out.update(xs=xs, ys=ys, a=round(a, 3), slope=round(slope, 4), rate=round(-slope, 3), r2=round(r2, 3),
               now_value=ys[-1], start=pts[0][0], last=pts[-1][0])
    if slope >= -0.005:
        out["why"] = "Moisture is not going down, so the line never reaches the refill point."
        return out
    x_cross = (b["refill"] - a) / slope
    hours_left = x_cross - xs[-1]
    out.update(ok=True, hours=round(hours_left, 1),
               eta=now(datetime.fromtimestamp(t0 + x_cross * 3600, timezone.utc)),
               already=ys[-1] <= b["refill"])
    return out


def save_prediction(db, cls, tray, team_id, user_id, p, student_hours=None, note=""):
    pid = new_id("ap")
    db.insert("ai_predictions", id=pid, class_id=cls["id"], tray_id=tray["id"], team_id=team_id, user_id=user_id,
              created_at=now(), moisture_now=p.get("now_value"), rate=p.get("rate"), r2=p.get("r2"), refill=p["refill"],
              predicted_hours=p.get("hours"), predicted_at=p.get("eta"), student_hours=student_hours, status="open",
              note=(note or "")[:300])
    return pid


def check_predictions(db, cls, tray):
    """The 'check' step: when did moisture really reach the refill point? Error = actual - predicted (hours)."""
    rows = db.q("SELECT * FROM ai_predictions WHERE tray_id = ? AND class_id = ? AND status = 'open'", tray["id"], cls["id"])
    for r in rows:
        age_h = (_ts(now()) - _ts(r["created_at"])) / 3600
        pts = [(t, v) for t, v in series(db, cls, tray, "moisture", min(720, int(age_h) + 2)) if t >= r["created_at"]]
        hit, prev = None, None
        for t, v in pts:
            if prev is not None and v - prev > RISE:            # watered before it got there
                db.run("UPDATE ai_predictions SET status = 'watered' WHERE id = ?", r["id"])
                hit = "watered"
                break
            if v <= r["refill"]:
                hit = t
                break
            prev = v
        if hit and hit != "watered":
            err = None
            if r["predicted_at"]:
                err = round((_ts(hit) - _ts(r["predicted_at"])) / 3600, 1)
            db.run("UPDATE ai_predictions SET status = 'checked', actual_at = ?, error_hours = ? WHERE id = ?", hit, err, r["id"])
        elif not hit and age_h > 168:
            db.run("UPDATE ai_predictions SET status = 'expired' WHERE id = ?", r["id"])


def prediction_rows(db, cls, tray=None, team_id=None, limit=12):
    sql = ("SELECT p.*, u.name AS who, t.name AS team, tr.letter FROM ai_predictions p JOIN users u ON u.id = p.user_id "
           "LEFT JOIN teams t ON t.id = p.team_id JOIN trays tr ON tr.id = p.tray_id WHERE p.class_id = ?")
    args = [cls["id"]]
    if tray:
        sql += " AND p.tray_id = ?"; args.append(tray["id"])
    if team_id:
        sql += " AND p.team_id = ?"; args.append(team_id)
    return db.q(sql + " ORDER BY p.created_at DESC LIMIT ?", *args, limit)


# ---------------------------------------------------------------- 2 is the sensor lying?
LIMITS = {"moisture": (0.0, 60.0), "temp": (-5.0, 45.0), "ec": (0.0, 5000.0), "ph": (3.0, 10.0)}
UNITS = {"moisture": "%", "temp": "°C", "ec": "µS/cm", "ph": ""}


def sensor_check(points, metric="moisture", train_share=0.6, frozen_run=6, spike=8.0):
    """Flag readings two ways. Fixed rules = what an engineer writes down in advance.
    Learned normal = mean +/- 3 sd of the first `train_share` of the readings (the 'training' part)."""
    vals = [v for _, v in points]
    out = {"n": len(vals), "rows": [], "rule_count": 0, "learned_count": 0, "both": 0}
    if len(vals) < 6:
        out["why"] = "Need at least 6 readings."
        return out
    lo, hi = LIMITS.get(metric, (None, None))
    n_train = max(3, int(len(vals) * train_share))
    m, sd = mean_std(vals[:n_train])
    sd = max(sd, 0.5 if metric == "moisture" else 0.05 * abs(m) + 0.01)
    out.update(train_n=n_train, mean=round(m, 2), sd=round(sd, 2), band=(round(m - 3 * sd, 2), round(m + 3 * sd, 2)), limits=(lo, hi))
    run = 1
    for i, (t, v) in enumerate(points):
        rules = []
        if lo is not None and (v < lo or v > hi):
            rules.append(f"outside the sensor's range {lo:g}–{hi:g}")
        if metric == "moisture" and v < 2:
            rules.append("near 0 %: probe out of the soil?")
        run = run + 1 if i and v == points[i - 1][1] else 1
        if run >= frozen_run:
            rules.append(f"same value {run} times: frozen?")
        if i and metric == "moisture" and points[i - 1][1] - v > spike:
            rules.append(f"dropped {points[i - 1][1] - v:.1f} in one step")
        learned = i >= n_train and abs(v - m) > 3 * sd
        if rules:
            out["rule_count"] += 1
        if learned:
            out["learned_count"] += 1
        if rules and learned:
            out["both"] += 1
        if rules or learned:
            out["rows"].append({"t": t, "v": v, "rules": rules, "learned": learned, "z": round((v - m) / sd, 1)})
    return out


# ---------------------------------------------------------------- 3 which beds behave alike?
FEATURES = [("moisture", "Moisture %"), ("ec", "EC µS/cm"), ("temp", "Soil °C"), ("rate", "Drying %/h")]


def zone_table(db, cls, trays, hours=168, k=2):
    rows = []
    for tr in trays:
        f = {}
        for metric in ("moisture", "ec", "temp"):
            vals = [v for _, v in series(db, cls, tr, metric, hours)]
            f[metric] = round(sum(vals) / len(vals), 2) if vals else None
        stretch = last_drying_stretch(series(db, cls, tr, "moisture", min(hours, 48)))
        fit = None
        if len(stretch) >= 4:
            t0 = _ts(stretch[0][0])
            fit = fit_line([(_ts(t) - t0) / 3600 for t, _ in stretch], [v for _, v in stretch])
        f["rate"] = round(max(0.0, -fit[1]), 3) if fit else None
        rows.append({"tray": tr, **f})
    usable = [r for r in rows if all(r[m] is not None for m, _ in FEATURES)]
    if len(usable) < 2:
        return {"rows": rows, "ok": False, "why": "Need readings from at least 2 trays or nodes."}
    stats = {}
    for m, _ in FEATURES:
        mu, sd = mean_std([r[m] for r in usable])
        stats[m] = (mu, sd or 1.0)
    scaled = [[(r[m] - stats[m][0]) / stats[m][1] for m, _ in FEATURES] for r in usable]
    labels = kmeans(scaled, k)
    order = {}
    for r, lab in zip(usable, labels):
        r["zone_raw"] = lab
    # name zones by average moisture, driest first, so "Zone 1" is always the driest
    zmean = {}
    for lab in set(labels):
        zs = [r["moisture"] for r in usable if r["zone_raw"] == lab]
        zmean[lab] = sum(zs) / len(zs)
    for i, lab in enumerate(sorted(zmean, key=zmean.get)):
        order[lab] = i + 1
    for r in usable:
        r["zone"] = order[r["zone_raw"]]
    zones = []
    for z in sorted(set(order.values())):
        members = [r for r in usable if r["zone"] == z]
        zones.append({"zone": z, "trays": [m["tray"]["letter"] for m in members],
                      **{m: round(sum(x[m] for x in members) / len(members), 2) for m, _ in FEATURES}})
    return {"rows": rows, "ok": True, "zones": zones, "k": max(order.values())}


# ---------------------------------------------------------------- 4 is this leaf healthy?
def leaf_score(matrix):
    """matrix[i][j] = test photos of true class i that the model called class j."""
    n = len(matrix)
    total = sum(sum(r) for r in matrix)
    right = sum(matrix[i][i] for i in range(n))
    recall = []
    for i in range(n):
        row = sum(matrix[i])
        recall.append(round(100 * matrix[i][i] / row) if row else None)
    worst = None
    for i in range(n):
        for j in range(n):
            if i != j and matrix[i][j] and (worst is None or matrix[i][j] > worst[2]):
                worst = (i, j, matrix[i][j])
    return {"total": total, "right": right, "accuracy": round(100 * right / total) if total else None, "recall": recall,
            "confusion": worst}


def save_result(db, cls, team_id, user_id, kind, data):
    db.insert("ai_results", id=new_id("ar"), class_id=cls["id"], team_id=team_id, user_id=user_id, kind=kind,
              data=jdump(data), created_at=now())


def results(db, cls, kind, team_id=None, limit=20):
    sql = ("SELECT r.*, u.name AS who, t.name AS team FROM ai_results r JOIN users u ON u.id = r.user_id "
           "LEFT JOIN teams t ON t.id = r.team_id WHERE r.class_id = ? AND r.kind = ?")
    args = [cls["id"], kind]
    if team_id:
        sql += " AND r.team_id = ?"; args.append(team_id)
    rows = db.q(sql + " ORDER BY r.created_at DESC LIMIT ?", *args, limit)
    for r in rows:
        r["data"] = jload(r["data"], {})
    return rows


# ---------------------------------------------------------------- 5 should AI decide?
def decision_stats(db, cls):
    """How good were the students' and the line's predictions? Evidence for the debate."""
    pumps = db.q("SELECT moisture_after, prediction FROM pump_requests WHERE class_id = ? AND moisture_after IS NOT NULL "
                 "AND prediction IS NOT NULL", cls["id"])
    errs = [abs(r["moisture_after"] - r["prediction"]) for r in pumps]
    preds = db.q("SELECT error_hours, student_hours, predicted_hours, created_at, actual_at FROM ai_predictions "
                 "WHERE class_id = ? AND status = 'checked'", cls["id"])
    line_err = [abs(r["error_hours"]) for r in preds if r["error_hours"] is not None]
    stud_err = []
    for r in preds:
        if r["student_hours"] is not None and r["actual_at"]:
            actual_h = (_ts(r["actual_at"]) - _ts(r["created_at"])) / 3600
            stud_err.append(abs(actual_h - r["student_hours"]))
    avg = lambda v: round(sum(v) / len(v), 1) if v else None
    return {"pump_n": len(errs), "pump_err": avg(errs), "pump_close": sum(1 for e in errs if e <= 2),
            "line_n": len(line_err), "line_err": avg(line_err), "stud_n": len(stud_err), "stud_err": avg(stud_err),
            "waiting": db.val("SELECT COUNT(*) AS n FROM pump_requests WHERE class_id = ? AND status = 'pending'", cls["id"]) or 0}


# ---------------------------------------------------------------- chart (inline SVG, no script needed)
def svg_chart(series_list, hlines=(), w=640, h=260, y_label="", marks=()):
    """series_list: [(label, colour, [(x, y), ...], 'line'|'dots'|'dash')], hlines: [(y, label, colour)].
    marks: [(x, y, colour)] highlighted points. x is in hours."""
    xs = [x for _, _, pts, _ in series_list for x, _ in pts] + [m[0] for m in marks]
    ys = [y for _, _, pts, _ in series_list for _, y in pts] + [y for y, _, _ in hlines] + [m[1] for m in marks]
    if not xs or not ys:
        return ""
    x0, x1 = min(xs), max(xs) if max(xs) > min(xs) else min(xs) + 1
    y0, y1 = min(ys), max(ys)
    pad = max(1.0, (y1 - y0) * 0.1)
    y0, y1 = y0 - pad, y1 + pad
    L, R, T, B = 48, 26, 26, 30
    px = lambda x: L + (x - x0) / (x1 - x0) * (w - L - R)
    py = lambda y: T + (y1 - y) / (y1 - y0) * (h - T - B)
    o = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{escape(y_label)} chart" style="max-width:{w}px">']
    for i in range(5):
        yv = y0 + (y1 - y0) * i / 4
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{py(yv):.1f}" y2="{py(yv):.1f}" stroke="var(--line)" stroke-width="1"/>'
                 f'<text x="{L - 6}" y="{py(yv) + 4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">{yv:.1f}</text>')
    for i in range(5):
        xv = x0 + (x1 - x0) * i / 4
        o.append(f'<text x="{px(xv):.1f}" y="{h - 10}" text-anchor="middle" font-size="11" fill="var(--muted)">{xv:.1f} h</text>')
    for yv, lab, col in hlines:
        o.append(f'<line x1="{L}" x2="{w - R}" y1="{py(yv):.1f}" y2="{py(yv):.1f}" stroke="{col}" stroke-width="1.5" stroke-dasharray="5 4"/>'
                 f'<text x="{w - R - 4}" y="{py(yv) - 5:.1f}" text-anchor="end" font-size="11" fill="{col}">{escape(lab)}</text>')
    for lab, col, pts, style in series_list:
        if not pts:
            continue
        if style == "dots":
            o += [f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="3" fill="{col}"/>' for x, y in pts]
        else:
            d = " ".join(f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}" for i, (x, y) in enumerate(pts))
            dash = ' stroke-dasharray="6 4"' if style == "dash" else ""
            o.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.2"{dash}/>')
    for x, y, col in marks:
        o.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="6" fill="none" stroke="{col}" stroke-width="2.5"/>')
    o.append(f'<text x="{L}" y="12" font-size="11" fill="var(--muted)">{escape(y_label)}</text></svg>')
    return "".join(o)


def hours_axis(points):
    if not points:
        return []
    t0 = _ts(points[0][0])
    return [((_ts(t) - t0) / 3600, v) for t, v in points]
