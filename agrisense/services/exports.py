"""Downloads: CSV, Excel and JSON. Named exports need export.named; everyone else gets de-identified rows."""
import csv
import hashlib
import io
import json

from ..db import now
from . import feeds as F

COLUMNS = ["time_utc", "school", "kit", "tray", "soil", "team", "feed", "metric", "value", "unit", "source"]


def _pseudo(source, salt):
    """user:usr_abc -> participant-1f3a (stable within one school, can't be reversed)."""
    if not source or not source.startswith("user:"):
        return source or ""
    return "participant-" + hashlib.sha256(f"{salt}:{source}".encode()).hexdigest()[:4]


def rows_for(db, feed_ids, since=None, until=None, named=False):
    out = []
    for fid in feed_ids:
        f = db.one("SELECT * FROM feeds WHERE id = ?", fid)
        if not f:
            continue
        tray = db.one("SELECT * FROM trays WHERE id = ?", f["tray_id"]) if f["tray_id"] else None
        kit = db.one("SELECT * FROM kits WHERE id = ?", f["kit_id"]) if f["kit_id"] else None
        team = db.one("SELECT * FROM teams WHERE id = ?", f["team_id"]) if f["team_id"] else None
        school_id = f["school_id"] or (kit and kit["school_id"])
        if not school_id and team:
            school_id = db.val("SELECT school_id FROM classes WHERE id = ?", team["class_id"])
        school = db.val("SELECT name FROM schools WHERE id = ?", school_id) if school_id else ""
        for p in F.history(db, fid, since, until, limit=200000):
            src = p["source"] or ""
            if src.startswith("user:"):
                if named:
                    nm = db.val("SELECT name FROM users WHERE id = ?", src[5:])
                    src = f"user:{nm or src[5:]}"
                else:
                    src = _pseudo(src, school_id)
            out.append({
                "time_utc": p["created_at"], "school": school, "kit": kit["name"] if kit else "",
                "tray": tray["letter"] if tray else "", "soil": tray["soil"] if tray else "",
                "team": team["name"] if team else "", "feed": f["key"], "metric": f["key"].split(".")[-1],
                "value": p["value"], "unit": f["unit"] or "", "source": src,
            })
    out.sort(key=lambda r: (r["time_utc"], r["feed"]))
    return out


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def to_json(rows, meta):
    return json.dumps({"exported_at": now(), **meta, "rows": rows}, indent=1).encode()


def to_xlsx(rows, meta):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Readings"
    head = Font(name="Arial", bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="2F5D3A")
    ws.append(COLUMNS)
    for c in ws[1]:
        c.font, c.fill = head, fill
    for r in rows:
        v = r["value"]
        try:
            v = float(v)
        except ValueError:
            pass
        ws.append([r[k] if k != "value" else v for k in COLUMNS])
    for col, width in zip("ABCDEFGHIJK", [21, 22, 14, 6, 11, 10, 30, 10, 10, 8, 18]):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name="Arial")
    ws.freeze_panes = "A2"
    info = wb.create_sheet("About")
    info.append(["AgriSense Lab data export"])
    info["A1"].font = Font(name="Arial", bold=True, size=13)
    for k, v in [("Exported (UTC)", now()), *meta.items(), ("Rows", len(rows)),
                 ("Note", "EC, N, P and K are left blank when moisture was under 10 % (the probe can't read them in dry soil)."),
                 ("Note", "N, P, K are estimates from EC by the probe, not a lab soil test.")]:
        info.append([k, str(v)])
    for row in info.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name="Arial")
            c.alignment = Alignment(wrap_text=True, vertical="top")
    info.column_dimensions["A"].width = 18
    info.column_dimensions["B"].width = 90
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render(rows, fmt, meta):
    if fmt == "xlsx":
        return to_xlsx(rows, meta), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if fmt == "json":
        return to_json(rows, meta), "application/json"
    return to_csv(rows), "text/csv; charset=utf-8"
