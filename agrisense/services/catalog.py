"""Built-in lessons and plans, loaded once when the database is created (flask --app agrisense init-db)."""
from ..db import jdump, new_id

LESSONS = [
    ("1.1", "Meet the soil bench", "activity", "Tour the five trays, name each soil and predict which one holds the most water.",
     "30 min", "bench", "HS-LS2-1,SEP-1", ["Predict", "Observe the trays", "Record first readings"]),
    ("1.2", "Reading the probe", "activity", "What moisture, temperature, EC and pH mean; take and record readings from every tray.",
     "40 min", "bench", "SEP-3,SEP-4", ["What each number means", "Take five readings", "Compare with a partner"]),
    ("1.3", "Which soil dries fastest?", "lab", "Track moisture for 48 h in sandy, loam and clay. Plot drying curves and explain the difference.",
     "2 × 45 min", "bench", "HS-ESS2-5,SEP-4,SEP-5", ["Plan", "Collect 48 h of data", "Graph", "Claim–evidence–reasoning"]),
    ("1.4", "How much water is enough?", "lab", "Request pump runs of different lengths and measure the moisture change per second.",
     "45 min", "bench", "SEP-3,SEP-5,CCC-3", ["Choose run times", "Request water", "Calculate % per second"]),
    ("1.5", "Salt and fertilizer", "lab", "Compare EC in fertilized and salty trays with loam. Decide which plants could grow in each.",
     "45 min", "bench", "HS-LS2-6,SEP-6", ["Compare EC", "Look up crop tolerance", "Recommend"]),
    ("1.6", "Build the Trainer pump loop", "activity", "Wire the pump, pressure sensor and tank switch on the Trainer Board and check NO FLOW protection.",
     "50 min", "trainer", "ETS1-2,SEP-2", ["Wire FIELD I/O", "Test pressure", "Trigger NO FLOW safely"]),
    ("1.7", "My first dashboard", "activity", "In the IoT Studio, add feeds and blocks to control the fan and pump and chart the pressure.",
     "40 min", "trainer", "SEP-8,ETS1-4", ["Create a dashboard", "Add toggles and a chart", "Test with your Trainer"]),
    ("1.8", "Smart irrigation rule", "lab", "Write an Action that waters when moisture drops below your threshold, then test and tune it.",
     "2 × 45 min", "trainer", "ETS1-3,SEP-2,SEP-6", ["Choose a threshold", "Write the Action", "Test, check, adjust"]),
    ("1.9", "Field decision report", "lab", "Use a week of bench data to recommend a watering schedule for each soil. Present to the class.",
     "2 × 45 min", "data", "HS-ESS3-4,SEP-7,SEP-8", ["Download data", "Analyze", "Write recommendation", "Present"]),
]

PLANS = [
    ("pilot", "Pilot", 0, "One kit, one school, one semester. Lessons 1.1–1.9 and the IoT Studio."),
    ("school", "School", 120000, "Per kit per year: all lessons, unlimited classes, data exports, support."),
    ("district", "District", None, "Several schools: priced by quote, purchase order, privacy agreement, rostering."),
]


def seed_catalog(db):
    if not db.val("SELECT COUNT(*) AS n FROM lessons"):
        for code, title, kind, summary, dur, eq, std, parts in LESSONS:
            db.insert("lessons", id=new_id("ls"), code=code, title=title, kind=kind, summary=summary, duration=dur,
                      equipment=eq, standards=std, parts=jdump(parts))
    if not db.val("SELECT COUNT(*) AS n FROM plans"):
        for code, name, cents, desc in PLANS:
            db.insert("plans", id=new_id("pl"), code=code, name=name, price_cents=cents, period="year", description=desc)
