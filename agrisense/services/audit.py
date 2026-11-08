from flask import g

from ..db import now


def log(db, action, detail="", school_id=None, org_id=None, user_id=None):
    if user_id is None and getattr(g, "user", None):
        user_id = g.user["id"]
    if school_id and not org_id:
        org_id = db.val("SELECT org_id FROM schools WHERE id = ?", school_id)
    db.insert("audit_log", org_id=org_id, school_id=school_id, user_id=user_id, action=action,
              detail=detail[:500] if detail else "", created_at=now())
