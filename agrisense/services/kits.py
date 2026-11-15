"""What schools can buy: the kit options shown on /kits and offered on the quote form (Nov 2026).

Hardware prices are ESTIMATES from the parts list's "Price tiers" sheet (2.2 x cost). Change them here when supplier
quotes are in; the page and the quote form read them from this file. Prices are whole US dollars.
"""

ESTIMATED = True                      # shows "Estimated" beside prices until real quotes are in
PILOT_TERM = "fall 2027"
LICENCE_PER_KIT = 300                 # website licence, $ per kit (or per Virtual school) per year
PER_STUDENT_STARTER = 13              # Starter + licence, 3 sections x 24 students, kit lasts 5 years

WHY = [   # short benefit tiles near the top of /kits
    ("Hands-on from day one", "Students plug in real sensors, a pump and a fan in the first lesson."),
    ("Real farm decisions", "They measure the soil, decide when to water, and check if they were right."),
    ("Works on Chromebooks", "Everything runs in the browser, including coding the student Arduino."),
    ("Ready to teach", "26 lessons mapped to NGSS, CSTA and AFNR, with training and PD hours."),
]

KITS = [
    {"code": "starter", "name": "Starter", "price": 3149, "unit": "one-time, per kit", "image": "img/kits/starter_trainer.jpg",
     "tag": "The complete classroom lab",
     "summary": "Everything your class needs to wire, measure, water and decide, in one carry case.",
     "includes": ["Trainer board with a pump, fan, motor and grow light to control",
                  "A student Arduino your class codes from a Chromebook",
                  "A water station to water plants and see the result",
                  "A build deck where students build their own sensor",
                  "Sensors, leads and a hard carry case",
                  "All 26 lessons, dashboards and the AI Lab online"],
     "best_for": "Agriculture, science and CTE classrooms starting hands-on precision agriculture."},
    {"code": "field", "name": "Field add-on", "price": 2249, "unit": "one-time, add to a Starter", "image": "img/kits/field_kit.jpg",
     "tag": "Optional",
     "summary": "Take the lab outside: real soil sensors in your greenhouse, garden or FFA plot.",
     "includes": ["Four weatherproof soil sensors", "Automatic watering control for a drip line",
                  "Long-range radio gateway to the website", "Live soil data, day and night"],
     "best_for": "Schools with a greenhouse, school garden or FFA plot."},
    {"code": "both", "name": "Starter + Field", "price": 5349, "unit": "one-time, per kit", "image": "img/kits/case.jpg",
     "tag": "Everything",
     "summary": "From the classroom bench to the school garden, all in one case.",
     "includes": ["Everything in Starter", "Everything in the Field add-on", "Packs in one hard case"],
     "best_for": "Programs ready to run the full year with their own field data."},
    {"code": "virtual", "name": "Virtual", "price": LICENCE_PER_KIT, "unit": "per year", "image": None,
     "tag": "No hardware",
     "summary": "Start today in the browser: every lesson runs on simulated sensors.",
     "includes": ["All 26 lessons in simulation mode", "AI Lab with real sample farm data",
                  "Dashboards students build themselves", "Online teacher training"],
     "best_for": "Trying AgriSense Lab before buying hardware, or a computer science class."},
]

SCHOOL_PROVIDES = [
    ("Soil bench supplies", "Tubs, a drip kit, soil and sand from a local store, about $100. We send the shopping list and a picture setup card."),
    ("Two digital multimeters", "Most science and ag classrooms already have them."),
    ("Chromebooks or laptops", "Any computer with a web browser."),
    ("Wi-Fi", "The kit joins your school network."),
]

FAQ = [
    ("Do we need the Field add-on?", "No. Starter runs every hands-on lesson at the bench. You can add the Field sensors any time, and they record your own garden data."),
    ("Is it hard to set up?", "No. The kit arrives assembled and tested: plug it in, join the Wi-Fi and it is ready. Online teacher training shows every step, and pilot schools get help from us directly."),
    ("Do I need coding experience?", "No. Lessons are step by step, and students start by plugging in leads, not writing code. Coding comes later, at each student's pace."),
    ("Is student data safe?", "Yes. Students sign in with a class code and pictures, with no email or birthday, and we sign your district's data privacy agreement."),
    ("How do we pay?", "Request a quote. We send a formal quote your business office can turn into a purchase order, then we ship and invoice the school."),
    ("Are prices final?", "Not yet. They are estimates until our supplier quotes are in, and pilot schools get pilot pricing."),
]

QUOTE_CHOICES = [(k["code"], k["name"]) for k in KITS] + [("district", "District (several schools)")]
QUOTE_CODES = {c for c, _ in QUOTE_CHOICES} | {"school"}       # "school" kept for old links
