# AgriSense Lab platform

The web app for **AgriSense Lab**, the precision-agriculture teaching kit from AgriSense Hub. Schools register their kits. Teachers run live soil-bench labs and approve pump runs. Students build their own dashboards in an IoT Studio (in the style of Adafruit IO) to switch the Trainer Board's pump, fan and vent. Everyone downloads the data.

It runs as a new app beside iot.agrisensehub.com and uses the **same gateways**: the gateway posts readings to `/api/v1/ingest`.

## What's in it

| Area | Who | What |
|---|---|---|
| Public site | everyone | Landing page, lessons, plans, quote request, school sign-up (pilot), privacy page |
| Sign-in | adults / students | Email + password; students use class code → tap name → two pictures |
| School admin | client admin, school admin, IT, billing, privacy | People and roles, classes, students (printable sign-in cards), kits and trays, **register hardware** (serial + claim code), device health, settings (pump limits, class hours, retention), privacy agreement, time-limited support access, billing (quotes, invoices, PO), activity log |
| Teacher | teacher, co-teacher, substitute | Live bench (5 trays), approve or decline pump requests, **STOP ALL**, simulation (dry spell, heat wave, speed), unlock IoT Studio controls, lessons 1.1–1.9, gradebook, teams and trays |
| Student | student | Team tray (charts, observations, ask for water), lab journal (claim, evidence, reasoning + data table) |
| IoT Studio | student team (teacher can view or lock) | **Dashboards** (toggle, slider, gauge, chart, big number, indicator, stream), **Feeds**, **Devices** (Trainer components), **Actions** (when X then Y), **Code & key** (team API key and examples) |
| Data | anyone with data access | Pick feeds and a range, chart, download **CSV / Excel / JSON** (de-identified unless the user has named-export rights) |
| Parent | parent | Their own child's lab status and scores |
| AgriSense staff | owner, ops, support, finance, content, sales | Clients, fleet health, **device inventory** (make serials, claim codes, keys), quotes and invoices, leads, staff roles; can see inside a school only while that school has granted support access |

Every role in the "Access levels" board is in `agrisense/rbac.py`. Pages and API calls check permissions through `can()`.

## Safety (enforced on the server and again in firmware)

- **Bench pump**: a student requests, a teacher approves; one tray at a time; never more than 300 s (each school can set a lower limit); optionally only during class hours. Any adult can press STOP.
- **Trainer pump**: runs only while the teacher has unlocked controls. It runs at most 30 s, then rests 60 s, and only if the tank level is OK. The board stops the pump on NO FLOW (under 10 kPa after 2 s) or BLOCKED (over 150 kPa).
- **Actions** that turn the pump on wait until a teacher approves them. Each rule has a minimum rest time and a time-of-day window.
- In **simulated classes**, pump approvals water the simulated tray and send no real command.

## Run it locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
flask --app agrisense init-db
flask --app agrisense seed-demo        # prints the demo logins and device keys
flask --app agrisense run
```

Demo logins (password `agrisense-demo-2026`): `teacher@`, `admin@`, `district@`, `it@`, `coteacher@`, `observer@`, `parent@`, `owner@`, `support@`, `finance@`, all at `demo.agrisensehub.com`.
To sign in as a student, use class code **AGRI03** (live) or **AGRI05** (simulated), pick any name, then tap **Corn + Sun**.

## Tests

```bash
python -m pytest -q          # 44 tests: pages for every role, access denials, ingest, pump safety, actions, Studio, exports, admin flows
# PostgreSQL check: record each test's SQL, then replay it on a real Postgres
PG_TRACE_DIR=/tmp/trace python -m pytest -q && tools/pg_replay.sh /tmp/trace "psql -h localhost -U postgres"
```

## Layout

```
agrisense/        app factory, db (SQLite or PostgreSQL), auth, rbac, schema.sql, seed.py
  services/       feeds, safety, actions, ingest, simulate, live, exports, catalog, audit
  routes/         public, admin, teacher, student, studio, data, staff, api
  templates/      Jinja pages        static/  app.css, app.js (no build step, no libraries)
firmware/         trainer_studio (Trainer Board ↔ Studio), gateway_bridge (bench gateway ↔ platform)
docs/             API.md, DEPLOY.md, screenshots/
tests/            pytest suite        tools/pg_replay.sh
```

See `docs/DEPLOY.md` to put it online at iot.agrisensehub.com, and `docs/API.md` for the device and team-key API.
