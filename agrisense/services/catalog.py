"""Built-in lessons and plans, loaded once when the database is created (flask --app agrisense init-db)."""
from ..db import jdump, new_id

# Lab 1 runs on the Starter kit, in this order; the Field add-on only adds logging in every tray and outdoors (KIT_NOTE).
LESSONS = [
    ("1.1", "Meet the soil bench", "activity", "Tour the five trays, name each soil and predict which one holds the most water.",
     "30 min", "bench", "HS-LS2-1,SEP-1", ["Predict", "Observe the trays", "Record first readings"]),
    ("1.2", "Reading the probe", "activity", "What moisture, temperature, EC and pH mean; move the Trainer's probe from tray to tray and record every reading.",
     "40 min", "bench", "SEP-3,SEP-4", ["What each number means", "Take five readings", "Compare with a partner"]),
    ("1.3", "Build the Trainer pump loop", "activity", "Wire the pump, pressure sensor and tank switch on the Trainer board and check NO FLOW protection.",
     "50 min", "trainer", "ETS1-2,SEP-2", ["Wire FIELD I/O", "Test pressure", "Trigger NO FLOW safely"]),
    ("1.4", "How much water is enough?", "lab", "Request pump runs of different lengths and measure the moisture change per second.",
     "45 min", "bench", "SEP-3,SEP-5,CCC-3", ["Choose run times", "Request water", "Calculate % per second"]),
    ("1.5", "Salt and fertilizer", "lab", "Compare EC in fertilized and salty trays with loam. Decide which plants could grow in each.",
     "45 min", "bench", "HS-LS2-6,SEP-6", ["Compare EC", "Look up crop tolerance", "Recommend"]),
    ("1.6", "Build your own sensor node", "lab", "Build a soil sensor node on the build deck, check its power with a meter, add sensor pods "
     "and get its readings on the website.",
     "2 × 45 min", "deck", "ETS1-2,SEP-3", ["Meet the parts", "Check the power", "Connect the probe", "Add sensor pods", "Go live"]),
    ("1.7", "Which soil dries fastest?", "lab", "Log moisture for 48 h in sandy and clay soil with your two probes. Plot drying curves and explain the difference.",
     "2 × 45 min", "bench", "HS-ESS2-5,SEP-4,SEP-5", ["Plan", "Collect 48 h of data", "Graph", "Claim–evidence–reasoning"]),
    ("1.8", "My first dashboard", "activity", "In the Field Studio, add feeds and blocks to control the fan and pump and chart the pressure.",
     "40 min", "trainer", "SEP-8,ETS1-4", ["Create a dashboard", "Add toggles and a chart", "Test with your Trainer"]),
    ("1.9", "Smart irrigation rule", "lab", "Write an Action that waters when moisture drops below your threshold, then test and tune it.",
     "2 × 45 min", "trainer", "ETS1-3,SEP-2,SEP-6", ["Choose a threshold", "Write the Action", "Test, check, adjust"]),
    ("1.10", "Code it yourself", "lab", "Program the student Arduino from a Chromebook to read the soil, show it on the LED grid "
     "and ask the Trainer for water. The Trainer answers OK or REFUSED.",
     "2 × 45 min", "r4", "ETS1-3,SEP-5", ["Connect", "Read the soil", "Show it on the LED grid", "Ask for water", "Test the safety"]),
    ("1.11", "Field decision report", "lab", "Use a week of data to recommend a watering schedule for each soil. Present to the class.",
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
    # Unit 3: greenhouse climate and control (Starter kit: AIR and LIGHT pods, grow light, fan, vent, knobs, LED bar, buzzer, motor, pressure)
    ("3.1", "Reading the air", "lab", "Measure air temperature and humidity, work out the vapour pressure deficit (VPD) and judge whether the air is good for plants.",
     "45 min", "climate", "MS-LS1-5,SEP-3,SEP-5", ["Read the air", "Change the air", "Work out VPD", "Judge the air"]),
    ("3.2", "Light for growth", "lab", "Measure light, work out the daily light integral (DLI) and set the grow light and hours to reach a target.",
     "45 min", "climate", "MS-LS1-5,SEP-4,SEP-5", ["Measure the room", "Measure the grow light", "Work out daily light", "Plan the lighting"]),
    ("3.3", "Keep the greenhouse cool", "lab", "Control the fan with a dead band (two rules), compare it with one rule, and decide when to use the vent.",
     "45 min", "climate", "ETS1-3,SEP-2,SEP-6", ["Find set points", "One rule first", "Add the dead band", "Use the vent too"]),
    ("3.4", "Alarms and displays", "activity", "Build an operator panel: knobs as set points, the LED bar as a gauge, and buzzer alarms that mean something.",
     "45 min", "climate", "ETS1-2,SEP-6", ["Read the knobs", "Make a gauge", "Set the alarms", "Design the panel"]),
    ("3.5", "Motors on the farm", "activity", "Drive the motor at different speeds and directions and use it to model a shade cloth that closes on bright days.",
     "45 min", "climate", "ETS1-2,SEP-3", ["Speed and direction", "Time a shade cloth", "Plan the shade", "Link it to light"]),
    ("3.6", "Is the irrigation healthy?", "lab", "Use pump pressure to tell a healthy line from a blocked or leaking one, and make a troubleshooting chart.",
     "45 min", "trainer", "ETS1-3,SEP-3,SEP-4", ["Normal pressure", "Blocked line", "Leak", "Troubleshooting chart"]),
    # Unit 4: precision farm decisions
    ("4.1", "Water by the weather", "lab", "Find how temperature, humidity and light change how fast soil dries, then predict tomorrow's water need from a forecast.",
     "2 × 45 min", "data", "HS-ESS3-4,SEP-4,SEP-5", ["Download", "Daily numbers", "Find the link", "Predict tomorrow"]),
    ("4.2", "A virtual field trial", "lab", "Test three watering plans side by side in simulation mode, compare water used and crop stress, then check the winner on the real bench.",
     "2 × 45 min", "sim", "ETS1-3,SEP-2,SEP-5", ["Choose the plans", "Run the trial", "Compare", "Check on the real bench"]),
    ("4.3", "Map your field", "lab", "Map where your sensors are, colour the map by soil readings and draw management zones.",
     "45 min", "map", "SEP-4,SEP-8", ["Collect positions", "Add the readings", "Colour the map", "Draw the zones"]),
    ("4.4", "Variable-rate plan", "lab", "Write a watering plan with a different amount for each zone, and show the water and money it saves.",
     "2 × 45 min", "data", "HS-ESS3-4,SEP-5,SEP-7", ["Uniform plan", "Variable-rate plan", "Savings", "Pitch it"]),
]

KIT_NOTE = {  # what the optional Field add-on changes; every lesson runs on the Starter kit (or the Virtual plan, in simulation)
    "1.7": "Field add-on: logs every tray, so loam joins the comparison",
    "1.11": "Field add-on: a full week of data for every tray",
    "2.1": "Field add-on: predict for any tray or field node",
    "2.4": "Field add-on: zones from your own field nodes",
    "4.3": "Field add-on: map your own field nodes outdoors",
    "4.4": "Field add-on: zones from a real field",
}
EQUIPMENT = {"bench": "Soil bench", "trainer": "Trainer board", "deck": "Build deck", "r4": "Student Arduino", "data": "Data", "ai": "AI Lab",
             "climate": "Trainer + pods", "sim": "Simulation", "map": "Map"}

RENUMBER_2026 = {"1.3": "1.7", "1.6": "1.3", "1.7": "1.8", "1.8": "1.9", "1.9": "1.11"}


PLANS = [   # website licences (Nov 2026). Hardware kits are on /kits (services/kits.py).
    ("pilot", "Pilot", 0, "Free website licence for one school for one semester: all 26 lessons, the AI Lab and the Field Studio. "
                          "The kit is bought separately at pilot pricing (see Kits and pricing)."),
    ("virtual", "Virtual", 30000, "No hardware: every lesson in simulation mode, the AI Lab and the Field Studio, for one school."),
    ("school", "School", 30000, "Per kit per year, with a Starter kit: all lessons on real hardware, unlimited classes, data exports, support."),
    ("district", "District", None, "Several schools: priced by quote, purchase order, privacy agreement, rostering."),
]


def seed_catalog(db):
    from .standards import MAP, short_codes
    # Nov 2026 re-order (Starter kit first): old 1.3/1.6/1.7/1.8/1.9 became 1.7/1.3/1.8/1.9/1.11. Move existing rows with
    # their content, so assignments and journals keep pointing at the same lesson.
    old_16 = db.one("SELECT id FROM lessons WHERE code = '1.6' AND title = 'Build the Trainer pump loop'")
    if old_16:
        for old in RENUMBER_2026:
            db.run("UPDATE lessons SET code = ? WHERE code = ?", "tmp-" + old, old)
        for old, new in RENUMBER_2026.items():
            db.run("UPDATE lessons SET code = ? WHERE code = ?", new, "tmp-" + old)
    have = {r["code"] for r in db.q("SELECT code FROM lessons")}
    for seq, (code, title, kind, summary, dur, eq, std, parts) in enumerate(LESSONS, 1):   # adds new lessons, keeps text current
        if code in MAP:
            std = short_codes(code)                                        # standards come from services/standards.py
        if code in have:
            db.run("UPDATE lessons SET title = ?, kind = ?, summary = ?, duration = ?, equipment = ?, standards = ?, parts = ?, seq = ? "
                   "WHERE code = ?", title, kind, summary, dur, eq, std, jdump(parts), seq, code)
        else:
            db.insert("lessons", id=new_id("ls"), code=code, title=title, kind=kind, summary=summary, duration=dur,
                      equipment=eq, standards=std, parts=jdump(parts), seq=seq)
    have_plans = {r["code"] for r in db.q("SELECT code FROM plans")}
    for code, name, cents, desc in PLANS:                                  # new plans are added, prices kept current
        if code in have_plans:
            db.run("UPDATE plans SET name = ?, price_cents = ?, description = ? WHERE code = ?", name, cents, desc, code)
        else:
            db.insert("plans", id=new_id("pl"), code=code, name=name, price_cents=cents, period="year", description=desc)
