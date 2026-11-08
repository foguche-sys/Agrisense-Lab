# Deploying

## Easiest: one-button deploy on Render (no command line)

1. Go to render.com and sign up with your GitHub account. When asked, let Render see the **Agrisense-Lab** repository.
2. In the Render dashboard click **New → Blueprint**, then pick **Agrisense-Lab**. Render reads `render.yaml` and shows two things to create: the database `agrisense-db` and the website `agrisense-lab`.
3. Fill in the two boxes it asks for:
   - **OWNER_EMAIL**: the email you'll sign in with as the AgriSense Hub owner.
   - **OWNER_PASSWORD**: at least 10 characters. Keep it in a password manager.
4. Choose plans for the database and the website. Free plans are fine for trying it out, but they sleep when idle or expire, so use paid plans before a school relies on it. Then click **Apply**.
5. Wait for the build to finish (a few minutes). Click the address Render shows, for example `https://agrisense-lab.onrender.com`. Sign in with your owner email and password.
6. **Your own address:** in the website's **Settings → Custom Domains**, add `lab.agrisensehub.com`. Render shows one DNS record (a CNAME). Add it where your agrisensehub.com DNS is managed, the same place you set up `iot.agrisensehub.com`. HTTPS turns on by itself once the record is live.

Every push to `main` on GitHub now updates the site automatically.

- The database tables are created on every start; this is safe to repeat.
- Housekeeping (offline devices, data retention) runs inside the app every 5 minutes, so you don't need a cron job.
- To try the demo school, set `SEED_DEMO` to `1` under the website's **Environment** tab, then redeploy. Set it back to `0` afterwards. The demo accounts share a known password, so delete the demo school before real schools join.

After deploying, schools sign up at `/signup`. As the owner, you make device serials and keys under **Inventory**.

## Docker (any server)

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
