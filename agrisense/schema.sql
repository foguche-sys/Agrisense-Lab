-- AgriSense Lab platform schema. Portable between SQLite and PostgreSQL.
-- {AUTOID} is replaced by "INTEGER PRIMARY KEY AUTOINCREMENT" (SQLite) or "BIGSERIAL PRIMARY KEY" (PostgreSQL).
-- Times are ISO-8601 UTC strings ("2026-11-08T06:20:00Z"), so they sort and compare the same in both databases.

CREATE TABLE IF NOT EXISTS orgs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,                  -- platform | client
  client_type TEXT,                    -- district | private | college | extension | school
  state TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schools (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES orgs(id),
  name TEXT NOT NULL,
  city TEXT,
  state TEXT,
  timezone TEXT NOT NULL DEFAULT 'America/Chicago',
  settings TEXT NOT NULL DEFAULT '{}',   -- JSON: retention, pump limits, sign-in options, units
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT UNIQUE,                     -- staff and adults; students have none
  name TEXT NOT NULL,                    -- students: first name + last initial
  password_hash TEXT,
  picture_hash TEXT,                     -- students: two-picture password
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_login TEXT
);

CREATE TABLE IF NOT EXISTS memberships (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  role TEXT NOT NULL,                    -- see agrisense/rbac.py ROLES
  org_id TEXT REFERENCES orgs(id),
  school_id TEXT REFERENCES schools(id),
  class_id TEXT,
  team_id TEXT,
  child_user_id TEXT,                    -- parent/guardian: which student
  expires_at TEXT,                       -- substitutes, observers
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_memberships_user ON memberships(user_id);

CREATE TABLE IF NOT EXISTS kits (
  id TEXT PRIMARY KEY,
  school_id TEXT NOT NULL REFERENCES schools(id),
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trays (
  id TEXT PRIMARY KEY,
  kit_id TEXT NOT NULL REFERENCES kits(id),
  letter TEXT NOT NULL,                  -- A..E
  soil TEXT NOT NULL,                    -- sandy | loam | clay | fertilized | salty
  label TEXT NOT NULL,
  crop TEXT                              -- see services/agronomy.py CROPS
);

CREATE TABLE IF NOT EXISTS classes (
  id TEXT PRIMARY KEY,
  school_id TEXT NOT NULL REFERENCES schools(id),
  name TEXT NOT NULL,
  code TEXT NOT NULL UNIQUE,             -- class code students type
  kit_id TEXT REFERENCES kits(id),
  sim_enabled INTEGER NOT NULL DEFAULT 0,
  sim_event TEXT,                        -- none | dry_spell | heat_wave
  sim_started_at TEXT,                   -- when simulation was switched on
  sim_speed INTEGER NOT NULL DEFAULT 60, -- simulated minutes per real minute
  pump_requests_allowed INTEGER NOT NULL DEFAULT 1,
  controls_unlocked_until TEXT,          -- IoT Studio outputs usable until this time
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL REFERENCES classes(id),
  name TEXT NOT NULL,                    -- "Team 2"
  slug TEXT NOT NULL UNIQUE,             -- "p3-team-2" (MQTT/API user name)
  tray_id TEXT REFERENCES trays(id),
  key_hash TEXT,                         -- IoT Studio team key (hashed)
  key_hint TEXT,
  key_expires_at TEXT
);

CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  serial TEXT NOT NULL UNIQUE,           -- printed on the QR label, e.g. ND-1B33
  kind TEXT NOT NULL,                    -- gateway | node | deck | pump | trainer
  claim_code TEXT NOT NULL,              -- one-time code on the label
  key_hash TEXT NOT NULL,                -- device API key (flashed in firmware)
  school_id TEXT REFERENCES schools(id), -- NULL = still in AgriSense inventory
  kit_id TEXT REFERENCES kits(id),
  tray_id TEXT REFERENCES trays(id),
  team_id TEXT REFERENCES teams(id),     -- Trainer Boards are assigned to a team
  name TEXT,
  status TEXT NOT NULL DEFAULT 'inventory', -- inventory | online | offline | retired
  firmware TEXT,
  rssi INTEGER,
  supply_v REAL,
  config TEXT NOT NULL DEFAULT '{}',     -- JSON: components on a Trainer
  last_seen TEXT,
  claimed_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feeds (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,              -- "kit-1a2b.tray-b.moisture" or "p3-team-2.pump"
  name TEXT NOT NULL,
  unit TEXT,
  kind TEXT NOT NULL,                    -- sensor | output | manual
  school_id TEXT REFERENCES schools(id),
  kit_id TEXT REFERENCES kits(id),
  tray_id TEXT REFERENCES trays(id),
  team_id TEXT REFERENCES teams(id),
  device_id TEXT REFERENCES devices(id),
  last_value TEXT,
  last_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS datapoints (
  id {AUTOID},
  feed_id TEXT NOT NULL REFERENCES feeds(id),
  value TEXT NOT NULL,
  num REAL,
  source TEXT,                           -- device | user:<id> | action:<id> | sim
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_datapoints_feed_time ON datapoints(feed_id, created_at);

CREATE TABLE IF NOT EXISTS commands (
  id {AUTOID},
  device_id TEXT NOT NULL REFERENCES devices(id),
  command TEXT NOT NULL,                 -- e.g. "RUN,60,B" | "STOP" | "SET,pump,ON,30"
  created_by TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS pump_requests (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL REFERENCES classes(id),
  team_id TEXT REFERENCES teams(id),
  tray_id TEXT NOT NULL REFERENCES trays(id),
  requested_by TEXT NOT NULL REFERENCES users(id),
  seconds INTEGER NOT NULL,
  reason TEXT,
  moisture_before REAL,
  prediction REAL,                       -- the team's predicted moisture after watering
  moisture_after REAL,                   -- what the probe read once the water soaked in
  checked_at TEXT,
  status TEXT NOT NULL,                  -- pending | approved | declined | stopped | done
  decided_by TEXT,
  decided_at TEXT,
  simulated INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
  id TEXT PRIMARY KEY,
  tray_id TEXT NOT NULL REFERENCES trays(id),
  team_id TEXT REFERENCES teams(id),
  user_id TEXT NOT NULL REFERENCES users(id),
  what TEXT NOT NULL,
  amount TEXT,
  note TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dashboards (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL REFERENCES teams(id),
  name TEXT NOT NULL,
  blocks TEXT NOT NULL DEFAULT '[]',     -- JSON list of {id,type,feed,title,options}
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL REFERENCES teams(id),
  name TEXT NOT NULL,
  feed_key TEXT NOT NULL,
  op TEXT NOT NULL,                      -- lt | gt | eq
  threshold TEXT NOT NULL,
  effect TEXT NOT NULL,                  -- on | off | alert | beep
  target_feed TEXT,
  seconds INTEGER NOT NULL DEFAULT 20,
  rest_seconds INTEGER NOT NULL DEFAULT 120,
  start_hhmm TEXT NOT NULL DEFAULT '00:00',
  end_hhmm TEXT NOT NULL DEFAULT '23:59',
  enabled INTEGER NOT NULL DEFAULT 1,
  approved_by TEXT,                      -- pump actions need a teacher's OK once
  last_fired_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  kind TEXT NOT NULL,                    -- lab | activity
  summary TEXT NOT NULL,
  duration TEXT NOT NULL,
  equipment TEXT NOT NULL,               -- bench | trainer | data
  standards TEXT NOT NULL,               -- comma list
  parts TEXT NOT NULL DEFAULT '[]'       -- JSON list of part titles
);

CREATE TABLE IF NOT EXISTS assignments (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL REFERENCES classes(id),
  lesson_id TEXT NOT NULL REFERENCES lessons(id),
  starts_on TEXT,
  due_on TEXT,
  data_source TEXT NOT NULL DEFAULT 'live',
  allow_pump INTEGER NOT NULL DEFAULT 1,
  points INTEGER NOT NULL DEFAULT 20,
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journals (
  id TEXT PRIMARY KEY,
  assignment_id TEXT NOT NULL REFERENCES assignments(id),
  team_id TEXT NOT NULL REFERENCES teams(id),
  claim TEXT, evidence TEXT, reasoning TEXT,
  data_table TEXT NOT NULL DEFAULT '[]', -- JSON rows
  status TEXT NOT NULL DEFAULT 'draft',  -- draft | submitted | returned | graded
  score INTEGER,
  feedback TEXT,
  graded_by TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  school_id TEXT,
  class_id TEXT,
  device_id TEXT,
  kind TEXT NOT NULL,                    -- too_dry | sensor_fault | offline | tank_low | high_ec | no_flow | blocked
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,             -- pilot | school | district
  name TEXT NOT NULL,
  price_cents INTEGER,                   -- NULL = set by quote
  period TEXT NOT NULL DEFAULT 'year',
  description TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES orgs(id),
  plan_id TEXT NOT NULL REFERENCES plans(id),
  licences INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active',
  renews_on TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES orgs(id),
  number TEXT NOT NULL UNIQUE,           -- INV-1042 / Q-0311
  kind TEXT NOT NULL,                    -- quote | invoice
  lines TEXT NOT NULL DEFAULT '[]',      -- JSON [{desc, qty, unit_cents}]
  amount_cents INTEGER NOT NULL,
  status TEXT NOT NULL,                  -- draft | sent | accepted | due | paid | void
  po_number TEXT,
  paid_via TEXT,                         -- po | card | ach
  due_on TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,
  name TEXT, email TEXT, school TEXT, state TEXT, plan TEXT, kits INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS privacy_agreements (
  id TEXT PRIMARY KEY,
  org_id TEXT NOT NULL REFERENCES orgs(id),
  version TEXT NOT NULL,
  status TEXT NOT NULL,                  -- not_started | sent | signed | countersigned
  signed_by TEXT,
  signed_at TEXT,
  countersigned_at TEXT
);

CREATE TABLE IF NOT EXISTS support_access (
  id TEXT PRIMARY KEY,
  school_id TEXT NOT NULL REFERENCES schools(id),
  ticket TEXT NOT NULL,
  granted_by TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id {AUTOID},
  org_id TEXT,
  school_id TEXT,
  user_id TEXT,
  action TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_school ON audit_log(school_id, created_at);
