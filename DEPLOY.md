# Deploying BloodLink

BloodLink is a small FastAPI app that can run anywhere Python 3.12 runs.
The default `render.yaml` provisions Postgres + a web service on
[Render](https://render.com), but the app also runs fine on a single
VM, Fly.io, Railway, or a Raspberry Pi.

## 0. Prerequisites

* Python 3.12 (the `requires-python` is `==3.12.*`)
* PostgreSQL 14+ if you want anything beyond a tiny SQLite dev DB
* A real `SECRET_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`

## 1. One-time install

```bash
git clone <your-fork> bloodlink
cd bloodlink
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env
# Edit .env: set DATABASE_URL, SECRET_KEY, ENV=production
```

## 2. Migrate the database

```bash
.venv/bin/alembic upgrade head
```

If `alembic` errors with `no such table: coordinators`, the app is being
imported before the tables exist. Make sure your DATABASE_URL points to
a fresh, empty database (no existing schema from a previous run).

## 3. Create a coordinator

There is **no auto-seed**. Pick a username and:

```bash
.venv/bin/python -m app.cli create-coordinator coord 'STRONG-PASSWORD'
```

This is the only entry point for the first coordinator. There is no
"forgot password" flow by design — losing the password means rotating
the coordinator hash via the CLI.

## 4. Boot with `uvicorn`

```bash
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000 --proxy-headers
```

`--proxy-headers` is required behind any TLS proxy (Render, Fly, Caddy,
nginx) so the app sees the real client IP and `https` scheme. Security
features (HSTS, Secure cookie flag) activate automatically when the request
scheme is `https`.

## 5. Purging old requester PII

The retention cron (F11.2) is run as a one-off CLI:

```bash
.venv/bin/python -m app.cli purge            # uses RETENTION_DAYS from env
.venv/bin/python -m app.cli purge --days 7   # override
```

Schedule it daily:

```cron
5 3 * * * cd /srv/bloodlink && .venv/bin/python -m app.cli purge >> /var/log/bloodlink-purge.log 2>&1
```

Each run is logged to the `audit_log` table with action `PURGE_RUN` and
the number of rows touched.

## 6. Telegram (optional)

If you want Telegram notifications:

1. Create a bot with [@BotFather](https://t.me/BotFather) on Telegram.
2. Set:
   * `TELEGRAM_BOT_TOKEN=...`
   * `TELEGRAM_WEBHOOK_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')`
   * `TELEGRAM_PUBLIC_BASE_URL=https://<your-domain>` (used for the
     `t.me/...` deep link in the donor's manage page)
4. Register it with Telegram once:

   ```bash
   curl -X POST \
     "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
     -d "url=https://<your-domain>/telegram/webhook" \
     -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
   ```

6. From a coordinator, on a verified donor's manage page, click
   "Connect Telegram on behalf of donor". The donor will see an
   8-character code on their public manage page that they type into the
   bot via `/start <code>`.

The webhook is protected by an `X-Telegram-Bot-Api-Secret-Token`
header check; without the right secret Telegram receives 403 and the
request is dropped (F8.1).

If `TELEGRAM_BOT_TOKEN` is unset, all Telegram UI is hidden and the
webhook returns 404. If `DEMO_MODE=true`, Telegram is **always**
disabled (F11.7).

## 7. Health check

`GET /health` returns 200 if the app can talk to the DB, otherwise 404.
Use this for container healthchecks and uptime monitors.

## 8. Smoke test

To verify a fresh deploy from a clean shell:

```bash
scripts/smoke_test.sh
```

This spins up uvicorn against a throwaway SQLite, hits every public
+ coordinator route, logs in as a smoke coordinator, and exits 0 on
success. Useful in CI.

## 9. Render-specific notes

`render.yaml` is the source of truth for Render. Two services are
provisioned:

* `bloodlink-db` — managed Postgres starter plan, private (no IP
  allow-list).
* `bloodlink-web` — Python web service. `startCommand` runs migrations
  + creates the first coordinator from env vars `COORD_USERNAME` /
  `COORD_PASSWORD`, then starts uvicorn.

The web service has its own URL once provisioned. Telegram, if used,
should point its webhook at `https://<service>.onrender.com/telegram/webhook`.

If you don't want the auto-coordinator-create step, drop the `python -m
app.cli create-coordinator` line from `startCommand` and create the
coordinator manually via `render shell bloodlink-web --command "..."`.

## 10. What never goes to the logs

* Donor phone numbers (full or partial)
* `manage_token` URL or token hashes
* `csrf_token` values
* Request `note` field
* Telegram chat IDs in error logs

Log scrubbers in the corporate SIEM are not needed; nothing sensitive
ever reaches the logger.