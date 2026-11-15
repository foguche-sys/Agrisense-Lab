"""Level 1 'Get started' course: the guide behind each module and step.

Each step: how to do it (where to click, what to type) and what success looks like.
Each module: a short intro, why it matters in class, and fixes for the usual problems.
"""

GUIDES = {
    "m1": {
        "intro": "Before the first class, make sure every part is there and fits. It takes half an hour and saves a lesson.",
        "why": "A missing lead or a jack that won't go in stops a whole team. Students notice when the kit is ready.",
        "steps": {
            "box": ("Open the case. Lift out the top tray and lay the parts on a table. Tick them off against the packing list "
                    "in the lid: Trainer board, field nodes A–D, pump node, gateway, build deck, water station tray, 12 V adapter, leads.",
                    "Every line on the packing list is ticked, or you've emailed support about what's missing."),
            "fit": ("Print the fit-test coupon (the first STL file) or use the one in the kit. Push a 4 mm banana socket into the "
                    "6.5 mm hole and a 2 mm jack into the 6.3 mm hole.",
                    "Both go in by hand and don't wobble. If they're tight, use the slicer's hole compensation, not a drill."),
            "label": ("Put a label on the 12 V adapter ('AgriSense Trainer only'). Choose a spot for the water station tray on the "
                      "table beside the board, never on it.",
                      "The adapter is labeled and the tray has its own place, at least a hand's width from the board."),
        },
        "trouble": [("A part is missing or broken", "Email the support address at the bottom of any page with a photo. Keep teaching with simulation mode meanwhile."),
                    ("A jack is loose in its hole", "Tighten the nut underneath. If it still turns, a drop of hot glue under the panel holds it.")],
    },
    "m2": {
        "intro": "The Trainer runs on 12 V. Three quick checks prove the power is right and that STOP really stops everything.",
        "why": "Students trust the kit when you've shown them it's safe. You'll also know what 'normal' looks like.",
        "steps": {
            "power": ("Plug the 12 V adapter into the DC jack on the power panel (back-left of the board), then into the wall.",
                      "The power LED lights and the controller screen comes on within a few seconds."),
            "rails": ("Set a multimeter to DC volts. Black probe in the black GND post on the power panel. Red probe in TP1, then TP2, then TP3.",
                      "About 12 V, 5.0 V and 3.3 V. Within ±0.2 V on TP2 and TP3 is fine."),
            "stop": ("On the Teach page, open the live bench and press STOP. Watch the pump and fan outputs.",
                     "Every output shows OFF within a few seconds, and the activity log records the STOP."),
        },
        "trouble": [("Nothing lights up", "Check the wall socket and the adapter plug. Check the fuse on the power panel (3 A with the grow light fitted)."),
                    ("TP2 isn't 5.0 V", "Don't connect anything. The 5 V buck must be set to 5.0 V: email support before class."),
                    ("The screen stays dark", "Re-seat the controller's USB-C cable and power cycle. If it's still dark, use simulation mode and contact support.")],
    },
    "m3": {
        "intro": "Students sign in with a class code and two pictures, no passwords. Set it up once and it works all year.",
        "why": "Teams and trays decide who can water what. Picture sign-in means no lost passwords in class.",
        "steps": {
            "class": ("Teach → (your class) → Teams & students. Add the students, make teams of 3–4 and give each team a tray (A–E).",
                      "Every student is in a team, and every team has a tray."),
            "cards": ("On Teams & students, print the sign-in cards. Go to the student sign-in page, enter the class code, tap a name "
                      "and the two pictures from that card.",
                      "You land on that student's 'My class' page. Sign out again."),
            "roles": ("School → People: your school admin adds a co-teacher or substitute and chooses their role. "
                      "The website shows a temporary password once: pass it on; they set their own at first sign-in.",
                      "They can sign in and see your class, with the limits of their role."),
        },
        "trouble": [("A student forgot their pictures", "Teams & students → Reprint cards for that student. The old pictures stop working."),
                    ("Two classes share one kit", "That's fine: each class has its own teams. Use the class switcher at the top of Teach.")],
    },
    "m4": {
        "intro": "Lessons 1.1–1.3 need no wiring: students read the soil bench and write a claim with evidence.",
        "why": "These lessons build the habits for everything later: predict, measure, explain with numbers.",
        "steps": {
            "assign": ("Teach → Lessons. Open lesson 1.1, set dates and points, and press Assign. Repeat for 1.2 and 1.3.",
                       "The lessons show 'Assigned' and appear on students' 'My class' pages, with the lab instructions and a printable sheet."),
            "sim": ("On the live bench, switch simulation on. Try the 'dry spell' event and a faster speed.",
                    "A purple SIMULATED DATA banner appears for you and your students, and the readings change faster."),
            "journal": ("Sign in as a test student, open lesson 1.1 and submit a short journal. Then Teach → Gradebook: open it, score it and add feedback.",
                        "The journal shows 'Graded' with your score on the student's page."),
        },
        "trouble": [("Readings say 'stale'", "The bench hasn't reported for 15 minutes: check power and Wi-Fi, or use simulation for the lesson."),
                    ("Students finish early", "Each lab has a 'Challenge' at the end of its instructions.")],
    },
    "m5": {
        "intro": "Water and electricity meet in this kit, so every pump run has limits, an approval and a STOP.",
        "why": "You stay in control: students request, you approve, and the system refuses unsafe runs on its own.",
        "steps": {
            "approve": ("Sign in as a test student, open Our tray and request a 10 s watering with a prediction. As the teacher, approve it on the live bench.",
                        "The pump runs, and 10 minutes later the decision log shows the actual moisture next to the prediction."),
            "rule": ("As a student: Field Studio → Rules → 'Water at the refill point'. As the teacher: approve the rule on the live bench.",
                     "The rule shows 'approved' and only runs during class hours."),
            "lock": ("On the live bench, lock the Field Studio controls, then unlock them for 40 minutes.",
                     "While locked, students' switches show 'locked'; after unlocking they work."),
        },
        "trouble": [("'The pump is resting'", "Every run is followed by a rest (60 s on the Trainer). Wait and try again."),
                    ("'Tank level is LOW'", "Refill the reservoir until the float switch lifts."),
                    ("NO FLOW alarm", "The pump isn't moving water: check it's under water and the hose isn't kinked.")],
    },
    "m6": {
        "intro": "Three problems cover most calls for help. Know these and you can fix most of them in under a minute.",
        "why": "A two-minute fix keeps the lesson going instead of losing the class.",
        "steps": {
            "offline": ("If a node shows 'offline': 1) is its power on? 2) is the gateway powered and on Wi-Fi? 3) is the node within range of the gateway?",
                        "You can name the three checks without looking."),
            "probe": ("A moisture reading near 0 % usually means the probe is out of the soil, not that the soil is bone dry. Push it back in fully.",
                      "You can explain this to a student, and AI Lab lesson 2.3 shows it on a chart."),
            "help": ("Every page has the support email at the bottom. Include the class name, the device serial and a photo.",
                     "You know where to find it."),
        },
        "trouble": [("Everything is offline", "The gateway or the school Wi-Fi is down. Use simulation mode for today's lesson."),
                    ("A reading looks impossible", "Check AI Lab → 2.3 Sensor check: it flags readings outside the sensor's range.")],
    },
}


# ---------------------------------------------------------------- Level 2: the workshop day (about 6 hours)
WORKSHOP = [
    ("0:00", "45 min", "Welcome and the farm problem", "Why precision irrigation matters; tour of the kit; safety rules for water and 12 V."),
    ("0:45", "60 min", "Wiring the Trainer", "Banana leads, the colour code, the coding panel, sensor pods. Each teacher wires a soil sensor and reads it."),
    ("1:45", "15 min", "Break", ""),
    ("2:00", "60 min", "Field nodes and the gateway", "Power a field node, pair it with the gateway, find its readings on the website, set up the pump node."),
    ("3:00", "45 min", "Lunch", ""),
    ("3:45", "60 min", "Irrigation lessons in practice", "Teach lessons 1.4 and 1.8 to each other: predict → water → check, approving runs, a smart irrigation rule."),
    ("4:45", "45 min", "The AI Lab", "Lessons 2.1 (predict watering) and 2.3 (sensor check) on real data; how to run the 2.5 debate."),
    ("5:30", "30 min", "Plan your unit", "Each teacher maps lessons onto their calendar and standards, and leaves with a plan for the first month."),
]
WORKSHOP_BRING = ["A laptop or Chromebook with Chrome", "Your class list (or a made-up one) to practise setup",
                  "Your school calendar, to plan your unit", "Level 1 finished beforehand, if you can"]

# ---------------------------------------------------------------- Level 3: the classroom project
PROJECT_IDEAS = [
    "A full irrigation unit: lessons 1.3, 1.4, 1.8 and 1.9 with one class, ending in student recommendations.",
    "The AI unit: lessons 2.1–2.5, with the class's own predictions checked over two weeks.",
    "A school-garden deployment: field nodes A–D outside for a month, with zones (lesson 2.4) and a watering plan.",
    "Your own idea, using the kit with a real local farm question.",
]
PROJECT_WRITEUP = [
    ("What you taught", "Which lessons, how many students, how many class periods, and any changes you made."),
    ("What students did", "One or two examples of student work: a journal, a dashboard, a prediction table, a presentation."),
    ("What students learned", "Evidence, not impressions: scores, before/after answers, quotes from journals."),
    ("What you'd change", "One thing that didn't work and how you'd do it next time."),
]
PROJECT_RUBRIC = [
    ("Students used real data", "Student work quotes numbers from the kit, not just descriptions."),
    ("Predict, test, explain", "Students predicted before measuring and explained the gap afterwards."),
    ("Safe practice", "Pump runs were approved, and water and electricity rules were followed."),
    ("Reflection", "The teacher names something to change, with a reason."),
]
