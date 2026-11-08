# Deploying

## Docker (recommended)

```bash
cp .env.example .env              # set SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec web flask --app wsgi init-db
docker compose exec web flask --app wsgi create-owner you@agrisensehub.com "Your Name"
```

The app listens on port 8000. Put it behind HTTPS (Caddy, nginx or your host's load balancer) at a subdomain such as `lab.agrisensehub.com`. Keep `SESSION_COOKIE_SECURE=1`.

The `housekeeping` service runs every 5 minutes. It marks silent devices offline, raises "offline" alerts, turns stale Trainer pump states off on dashboards, and deletes readings older than each school's retention setting.

## Without Docker

Requirements: Python 3.11+ and PostgreSQL 14+.

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql://user:pass@host:5432/agrisense SECRET_KEY=... SESSION_COOKIE_SECURE=1 FLASK_ENV=production
flask --app wsgi init-db
gunicorn -w 3 -k gthread --threads 4 -b 0.0.0.0:8000 wsgi:app
# cron: */5 * * * *  flask --app wsgi housekeeping
```

## Connecting hardware

1. Staff → Inventory → **Make** devices (gateway, node, pump, trainer). Each device gets a serial, a claim code and a device key, and the **key is shown only once**. Download the CSV.
2. Put the key in that board's `firmware/*/secrets.h` and flash it. Print the serial and claim code on the QR label.
3. The school registers the device: School → Kits & devices → **Register a device**. Then it assigns nodes to trays and Trainer Boards to teams.
4. The device appears **Online** after its first post.

The existing gateways keep working. Point the new bridge sketch (or your current gateway code) at `API_BASE/api/v1/ingest` with its `X-Device-Key`.

## Backups

Take a nightly `pg_dump` of the database. Everything (readings, journals, invoices, audit log) is in PostgreSQL.
