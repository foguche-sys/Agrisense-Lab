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
    ("1.7", "My first dashboard", "activity", "In the Field Studio, add feeds and blocks to control the fan and pump and chart the pressure.",
     "40 min", "trainer", "SEP-8,ETS1-4", ["Create a dashboard", "Add toggles and a chart", "Test with your Trainer"]),
    ("1.8", "Smart irrigation rule", "lab", "Write an Action that waters when moisture drops below your threshold, then test and tune it.",
     "2 × 45 min", "trainer", "ETS1-3,SEP-2,SEP-6", ["Choose a threshold", "Write the Action", "Test, check, adjust"]),
    ("1.9", "Field decision report", "lab", "Use a week of bench data to recommend a watering schedule for each soil. Present to the class.",
     "2 × 45 min", "data", "HS-ESS3-4,SEP-7,SEP-8", ["Download data", "Analyze", "Write recommendation", "Present"]),
    # Unit 2: AI with your own data (AI Lab). Models are trained on the class's own readings, not a ready-made dataset.
    ("2.1", "When will my tray need water?", "lab", "Fit a line to your tray's drying curve, predict the hours until the refill point, "
     "then let the AI Lab check your prediction against what really happened.",
     "2 × 45 min", "ai", "AI4K12-3,SEP-4,SEP-5,CSTA 3A-DA-12", ["Guess first", "Fit the line in the AI Lab", "Save the prediction", "Check it later", "Explain the error"]),
    ("2.2", "Is this leaf healthy?", "lab", "Photograph healthy, yellowing and pest-damaged leaves, train an image model in Teachable Machine "
     "and test it on photos it has never seen.",
     "2 × 45 min", "ai", "AI4K12-1,AI4K12-3,SEP-3", ["Collect photos", "Train", "Test on new photos", "Record the results", "Find its blind spots"]),
    ("2.3", "Is the sensor lying?", "lab", "Find bad readings (probe out of the soil, frozen values, sudden drops). Compare rules an engineer "
     "writes in advance with a 'learned normal' band.",
     "45 min", "ai", "AI4K12-3,SEP-4,ETS1-3", ["Pick a sensor", "Read the flags", "Rules vs learned normal", "Decide what to trust"]),
    ("2.4", "Which beds behave alike?", "lab", "Group trays or field nodes into management zones with k-means clustering, the way precision "
     "farms split a field into zones.",
     "45 min", "ai", "AI4K12-2,SEP-4,HS-ESS3-4", ["Look at the four features", "Run the clustering", "Try 2 and 3 zones", "Recommend a plan per zone"]),
    ("2.5", "Should AI decide when to water?", "activity", "Debate who should have the final say: the model, the advisor or the farmer. "
     "Use your class's own prediction errors as evidence.",
     "45 min", "ai", "AI4K12-5,SEP-7", ["Look at the evidence", "Take a side", "Debate", "Write your position"]),
]

PLANS = [   # website licences (Nov 2026). Hardware kits are on /kits (services/kits.py).
    ("pilot", "Pilot", 0, "One kit, one school, one semester. Lessons 1.1–1.9, the AI Lab (2.1–2.5) and the Field Studio."),
    ("virtual", "Virtual", 30000, "No hardware: every lesson in simulation mode, the AI Lab and the Field Studio, for one school."),
    ("school", "School", 30000, "Per kit per year, with a Starter kit: all lessons on real hardware, unlimited classes, data exports, support."),
    ("district", "District", None, "Several schools: priced by quote, purchase order, privacy agreement, rostering."),
]


def seed_catalog(db):
    from .standards import MAP, short_codes
    have = {r["code"] for r in db.q("SELECT code FROM lessons")}
    for code, title, kind, summary, dur, eq, std, parts in LESSONS:      # adds new lessons to existing databases too
        if code in MAP:
            std = short_codes(code)                                        # standards come from services/standards.py
        if code in have:
            db.run("UPDATE lessons SET standards = ? WHERE code = ? AND standards <> ?", std, code, std)
        else:
            db.insert("lessons", id=new_id("ls"), code=code, title=title, kind=kind, summary=summary, duration=dur,
                      equipment=eq, standards=std, parts=jdump(parts))
    have_plans = {r["code"] for r in db.q("SELECT code FROM plans")}
    for code, name, cents, desc in PLANS:                                  # new plans are added, prices kept current
        if code in have_plans:
            db.run("UPDATE plans SET name = ?, price_cents = ?, description = ? WHERE code = ?", name, cents, desc, code)
        else:
            db.insert("plans", id=new_id("pl"), code=code, name=name, price_cents=cents, period="year", description=desc)
