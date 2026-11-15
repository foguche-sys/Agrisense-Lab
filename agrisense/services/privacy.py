"""Student data privacy: the agreement version, the data schedule (shared by the privacy policy, the agreement
page and the school's Privacy page), minimal-data mode (students as codes, no names) and deleting a class's
student data at the end of a course."""
from ..db import now

DPA_VERSION = "2026.2"

# What the platform collects (Exhibit B of the Student Data Privacy Agreement). Keep in step with the schema.
DATA_SCHEDULE = [
    ("Student identity", "Display name", "Yes", "First name + last initial, or a code such as \"Student 07\" in minimal-data mode"),
    ("Student identity", "Class, team and tray", "Yes", "Set by the teacher"),
    ("Student sign-in", "Two-picture password", "Yes", "Stored only as a one-way hash"),
    ("Student sign-in", "Email, phone, username or typed password", "No", "Students sign in with the class code and two pictures"),
    ("Student work", "Lab journals (claim, evidence, reasoning, data table), scores, feedback", "Yes", "Saved per team"),
    ("Student work", "Observations, pump requests (seconds, prediction, reason), dashboards and rules", "Yes", "Linked to the team or student who made them"),
    ("Student work", "AI Lab predictions and test results (numbers only)", "Yes", "Leaf photos stay in the student's browser with Teachable Machine; none are uploaded"),
    ("Usage", "Last sign-in time and an activity log of key actions", "Yes", ""),
    ("Technical", "IP address and browser type in server logs", "Yes", "For security only; kept 30 days"),
    ("Parents (optional)", "Name, email and which child", "Only if the school turns parent access on", ""),
    ("Teachers and staff", "Name, school email, password hash, roles, training progress", "Yes", "Adults, not student data"),
    ("Never collected", "Date of birth, home address, phone, student photos or video, biometrics, location, race, ethnicity, "
     "disability, religion, political affiliation, disciplinary or medical records, grades from other systems", "No", ""),
]

RETENTION = [
    ("Sensor readings", "365 days by default; each school sets 30 to 3,650 days"),
    ("Student accounts, journals, predictions, dashboards", "While the class is in use; removed when the school deletes the class's student data, or within 60 days after the contract ends"),
    ("Server logs (IP address, browser)", "30 days"),
    ("Activity log", "2 years"),
    ("Backups", "Deleted data drops out of backups as they are overwritten, within 30 days"),
]

NAME_MODES = {"initial": "First name and last initial (\"Maya R.\")",
              "code": "Codes only (\"Student 07\"): no student names are stored"}


def name_mode(settings):
    return settings.get("student_names") if settings.get("student_names") in NAME_MODES else "initial"


def display_name(raw, mode, number):
    """The only form of a student's name the platform stores."""
    if mode == "code":
        return f"Student {number:02d}"
    parts = raw.split()
    return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")


def class_students(db, class_id):
    return db.q("SELECT m.id AS mid, m.user_id, u.name, u.email FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.class_id = ? AND m.role = 'student' ORDER BY u.created_at, u.id", class_id)


def codes_for_school(db, school_id):
    """Replace every student name in the school with a code, class by class. Returns how many were renamed."""
    n = 0
    for c in db.q("SELECT id FROM classes WHERE school_id = ?", school_id):
        for i, s in enumerate(class_students(db, c["id"]), 1):
            if s["email"] is None:
                db.update("users", s["user_id"], name=f"Student {i:02d}")
                n += 1
    return n


def delete_class_student_data(db, class_id):
    """End-of-course clean-up: remove the class's students and everything they wrote.
    Kept: the class, its teams and trays, sensor readings, and pump run times (safety records, with no names or reasons)."""
    teams = [t["id"] for t in db.q("SELECT id FROM teams WHERE class_id = ?", class_id)]
    students = class_students(db, class_id)
    uids = [s["user_id"] for s in students if s["email"] is None]
    counts = {"students": len(uids)}

    def in_list(col, ids):
        return f"{col} IN ({','.join('?' * len(ids))})"

    if teams:
        counts["journals"] = db.val(f"SELECT COUNT(*) AS n FROM journals WHERE {in_list('team_id', teams)}", *teams) or 0
        db.run(f"DELETE FROM journals WHERE {in_list('team_id', teams)}", *teams)
        db.run(f"DELETE FROM observations WHERE {in_list('team_id', teams)}", *teams)
        db.run(f"DELETE FROM dashboards WHERE {in_list('team_id', teams)}", *teams)
        db.run(f"DELETE FROM actions WHERE {in_list('team_id', teams)}", *teams)
    if uids:
        db.run(f"DELETE FROM observations WHERE {in_list('user_id', uids)}", *uids)
        db.run(f"DELETE FROM memberships WHERE {in_list('child_user_id', uids)}", *uids)      # parents of these students
    db.run("DELETE FROM ai_predictions WHERE class_id = ?", class_id)
    db.run("DELETE FROM ai_results WHERE class_id = ?", class_id)
    db.run("UPDATE pump_requests SET reason = NULL WHERE class_id = ?", class_id)
    db.run("DELETE FROM memberships WHERE class_id = ? AND role = 'student'", class_id)
    for u in uids:
        if not db.val("SELECT COUNT(*) AS n FROM memberships WHERE user_id = ?", u):
            db.update("users", u, name="Deleted student", picture_hash=None, is_active=0)
    counts["at"] = now()
    return counts
