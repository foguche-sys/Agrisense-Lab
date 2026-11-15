"""What schools can buy: the kit options shown on /kits and offered on the quote form (Nov 2026).

Hardware prices are ESTIMATES from the parts list's "Price tiers" sheet (2.2 x cost). Change them here when supplier
quotes are in; the page and the quote form read them from this file. Prices are whole US dollars.
"""

ESTIMATED = True                      # shows "Estimated" beside prices until real quotes are in
PILOT_TERM = "fall 2027"
LICENCE_PER_KIT = 300                 # website licence, $ per kit (or per Virtual school) per year
PER_STUDENT_STARTER = 13              # Starter + licence, 3 sections x 24 students, kit lasts 5 years

KITS = [
    {"code": "starter", "name": "Starter", "price": 3149, "unit": "one-time, per kit", "image": "img/kits/starter_trainer.jpg",
     "tag": "The complete classroom lab",
     "summary": "Everything students need to wire, measure, water and decide at one bench.",
     "includes": ["Trainer board: power, controller, coding panel, relays (pump, fan, motor, grow light) and knobs",
                  "UNO R4 WiFi student controller, screwed beside the controller (codes from a Chromebook)",
                  "Water station: pump, pressure sensor, float switch, test cups",
                  "Build deck: students assemble their own sensor node (node E)",
                  "Plug-in sensor pods, banana leads, 12 V adapter",
                  "Hard carry case with foam", f"Website licence: ${LICENCE_PER_KIT} a year"],
     "best_for": "Agriculture, science and CTE classrooms starting hands-on precision agriculture."},
    {"code": "field", "name": "Field add-on", "price": 2249, "unit": "one-time, add to a Starter", "image": "img/kits/field_node.jpg",
     "tag": "Optional",
     "summary": "Turns the classroom lab into a real farm network for the greenhouse, garden or FFA plot.",
     "includes": ["Four sealed outdoor soil nodes (A to D) with 7-in-1 soil probes",
                  "Pump node for the drip line", "LoRa gateway: long-range radio to the website",
                  "Logs all five soil-bench tubs day and night, then moves outside"],
     "best_for": "Schools with a greenhouse, school garden or FFA plot."},
    {"code": "both", "name": "Starter + Field", "price": 5349, "unit": "one-time, per kit", "image": "img/kits/case.jpg",
     "tag": "Everything",
     "summary": "Both together: from the classroom bench to the school garden.",
     "includes": ["Everything in Starter", "Everything in the Field add-on", "Packs in one hard case"],
     "best_for": "Programs ready to run the full year with their own field data."},
    {"code": "virtual", "name": "Virtual", "price": LICENCE_PER_KIT, "unit": "per year", "image": None,
     "tag": "No hardware",
     "summary": "The website, simulation mode and the AI Lab. Every lesson runs on simulated sensors.",
     "includes": ["All 14 lessons in simulation mode", "AI Lab (lessons 2.1 to 2.5) with sample farm data",
                  "Field Studio dashboards", "Teacher training Level 1 (online)"],
     "best_for": "Trying AgriSense Lab before buying hardware, or a computer science class."},
]

SCHOOL_PROVIDES = [
    ("Soil bench supplies", "Five clear tubs, a drip kit, a bucket, sand, topsoil, clay, fertilizer and salt: about $100 at a local store. We send the shopping list and a setup card."),
    ("Two digital multimeters", "Most science and ag classrooms already have them."),
    ("Chromebooks or laptops", "Any computer with a web browser. Students code the UNO R4 in the Arduino Cloud Editor."),
    ("Wi-Fi", "The Trainer and the gateway join the school network."),
]

FAQ = [
    ("Do we need the Field add-on?", "No. Starter runs every hands-on lesson at the bench. Lessons that need days of continuous data use the shared sample data or simulation until you add the Field nodes, which record your own."),
    ("How do we pay?", "Request a quote. We send a formal quote your business office can turn into a purchase order. We ship the kit and invoice the school. We do not take card payments for kits."),
    ("How long does setup take?", "About an hour for the Trainer and the water station, plus an hour for the soil bench. Teacher training Level 1 (3 hours, online) walks through it."),
    ("Is student data safe?", "Students sign in with a class code and pictures, with no email or birthday. We sign your district's data privacy agreement."),
    ("What if something breaks?", "Every printed part can be reprinted and every electronic part is a standard part. Pilot schools get spare parts and direct support."),
    ("Are prices final?", "Not yet. They are estimates until our supplier quotes are in. Pilot schools get pilot pricing."),
]

QUOTE_CHOICES = [(k["code"], k["name"]) for k in KITS] + [("district", "District (several schools)")]
QUOTE_CODES = {c for c, _ in QUOTE_CHOICES} | {"school"}       # "school" kept for old links
