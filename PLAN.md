# PLAN.md — milestones

## M1: Foundation and i18n scaffold
**Files to create:**
- `pyproject.toml` (pinned versions)
- `app/__init__.py` — `create_app()` factory
- `app/config.py` — pydantic-settings, every env var
- `app/db.py` — SQLModel engine/session
- `app/models/__init__.py` + per-entity model modules:
  - `coordinator.py`, `donor.py`, `area.py`, `request.py`, `contact_attempt.py`, `audit_log.py`, `telegram_link.py`, `login_attempt.py`
- `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`
- `app/routes/health.py` — `GET /health`
- `app/templates/base.html`, `app/templates/partials/lang_switch.html`
- `app/static/vendor/htmx.min.js` (vendored)
- `app/static/css/main.css` (minimal base)
- `app/i18n.py` — translation helper `t(key)`, loads `en.json`/`bn.json`
- `app/translations/en.json`, `app/translations/bn.json`
- `app/phone.py` — Bangladesh number normalization
- `tests/test_phone.py` — exhaustive phone normalization tests
- `tests/test_i18n.py` — en/bn key parity
- `tests/test_health.py` — `/health` 200
- `tests/test_migrations.py` — upgrade/downgrade on SQLite and Postgres
- `Dockerfile`, `docker-compose.yml`
- `Makefile`
- `.github/workflows/ci.yml` (Postgres service)
- `.env.example`
- `.gitignore`
- `README.md` (skeleton — full README in final phase)

**Tests required:** phone normalization (F2.2, F2.3), i18n parity (F10.1), health, migrations up/down.

**Acceptance:** A1 `docker compose up --build` serves /health with 200. A2 migrations upgrade and downgrade on Postgres and SQLite. A3 phone normalization tests. A4 i18n key parity test. A5 CI is green.

---

## M2: Coordinator auth and security baseline
**Files to create:**
- `app/security.py` — argon2 hashing, signed cookie helpers
- `app/csrf.py` — CSRF token + dependency
- `app/audit.py` — `write_audit()` helper
- `app/routes/auth.py` — `GET/POST /login`, `POST /logout`
- `app/routes/csrf.py` — `GET /csrf` (returns token if needed)
- `app/deps.py` — `require_coordinator` dependency
- `app/middleware.py` — security headers middleware
- `app/cli/__init__.py` + `app/cli/main.py` — `create-coordinator` subcommand
- `app/models/login_attempt.py` — rate-limit table
- `tests/test_auth.py` — login success/fail, rate limit, cookie flags
- `tests/test_csrf.py` — route-discovery test
- `tests/test_audit.py` — audit writes
- `tests/test_cli.py` — `create-coordinator` CLI

**Tests required:** F1.1, F1.2, F1.3, F1.4, F1.5, F1.6, F1.7.

**Acceptance:** A1 wrong password and unknown username return the same generic error. A2 route-discovery test enumerates all state-changing routes. A3 rate limit triggers on 6th failure within 15 min (freezegun). A4 cookie flags asserted. A5 production refuses to start with default SECRET_KEY.

---

## M3: Donor registration and self-service
**Files to create:**
- `app/routes/donor_public.py` — `GET/POST /donor/register`, `GET/POST /donor/manage/{token}`
- `app/routes/areas.py` — coordinator area CRUD (needed by form)
- `app/tokens.py` — secure token + hash helpers
- `app/templates/donor/register.html`, `manage.html`, `registered.html`
- `app/templates/areas/list.html`, `form.html`
- `tests/test_donor_register.py` — F2.1, F2.4, F2.5, F2.6, F2.7, F2.8
- `tests/test_donor_manage.py` — F3.1, F3.2, F3.3, F3.4, F3.5
- `tests/test_areas.py` — area CRUD
- `tests/test_phone_dup.py` — duplicate phone rejection (G6)

**Tests required:** F2.1-F2.8, F3.1-F3.6.

**Acceptance:** A1 all three checkboxes required. A2 duplicate phone rejected. A3 manage link works, token hashed, 404 on bad token. A4 phone change resets to unverified. A5 delete-my-data works. A6 future last_donation_date rejected. A7 HTML escaped.

---

## M4: Coordinator donor management
**Files to create:**
- `app/routes/coordinator_donors.py` — list, search, filter, verify, suspend, unsuspend, regenerate link, record donation, reveal phone
- `app/templates/coordinator/donors/list.html`, `detail.html`
- `tests/test_coordinator_donors.py` — F4.1-F4.9

**Tests required:** F4.1-F4.9.

**Acceptance:** A1 phones masked. A2 reveal writes audit. A3 status changes write audit. A4 filters combine. A5 coordinator only. A6 donation updates last_donation_date. A7 statuses work. A8 note optional. A9 non-medical warning.

---

## M5: Blood requests
**Files to create:**
- `app/routes/request_public.py` — `GET/POST /request/new`, `GET/POST /request/{token}` (tracking)
- `app/routes/coordinator_requests.py` — verify, reject
- `app/request_validation.py` — units, needed_by, note length, honeypot
- `app/rate_limit.py` — IP and phone rate limit helpers (using DB)
- `app/templates/request/new.html`, `tracking.html`
- `app/templates/coordinator/requests/list.html`, `detail.html`
- `tests/test_request_public.py` — F5.1-F5.6
- `tests/test_request_lifecycle.py` — F6.1-F6.5
- `tests/test_request_rate_limit.py` — honeypot, IP rate, phone rate

**Tests required:** F5.1-F5.6, F6.1-F6.5.

**Acceptance:** A1 validation. A2 honeypot. A3 IP rate 6th. A4 phone active limit. A5 tracking link. A6 random public id.

---

## M6: Matching engine
**Files to create:**
- `app/matching.py` — pure function: `(request, donors, settings, now) -> ranked candidates`
- `app/compatibility.py` — blood compatibility table
- `app/routes/coordinator_matching.py` — candidate page, contact-attempt recording
- `app/templates/coordinator/matching/candidates.html`
- `tests/test_matching.py` — F7.1 (exhaustive), F7.2 (hypothesis), F7.3, F7.4, F7.5, F7.6, F7.8
- `tests/test_compatibility.py` — table lookup
- `tests/test_matching_candidates_page.py` — F7.7

**Tests required:** F7.1-F7.9.

**Acceptance:** A1 exhaustive compatibility test. A2 hypothesis Rh- property. A3 exclusion rules + boundary. A4 ranking. A5 24h flag. A6 donated closes attempt + updates date. A7 masked phones.

---

## M7: Telegram notifications
**Files to create:**
- `app/telegram.py` — httpx client wrappers, sendMessage, answerCallbackQuery
- `app/telegram_signing.py` — callback data signing + verify + expiry
- `app/routes/telegram.py` — webhook endpoint with secret-header check
- `app/routes/coordinator_notify.py` — coordinator trigger
- `app/templates/partials/telegram_link.html`
- `tests/test_telegram.py` — F8.1-F8.8
- `tests/test_telegram_webhook.py` — secret header, tampered data, idempotency

**Tests required:** F8.1-F8.8.

**Acceptance:** A1 no token: hidden + app works. A2 one-time code. A3 message contents. A4 webhook secret. A5 tampered. A6 idempotent accept. A7 failure handling. A8 DEMO_MODE off.

---

## M8: Public pages, privacy operations, seed, end-to-end tests
**Files to create:**
- `app/routes/public.py` — `/`, `/privacy`, `/stats`
- `app/stats.py` — aggregate counts with small-number suppression
- `app/templates/home.html`, `privacy.html`, `stats.html`
- `app/templates/errors/404.html`, `500.html`
- `app/static/css/main.css` — mobile-first
- `app/seed.py` — idempotent demo seed
- `app/cli/seed_cmd.py` — `python -m app.cli seed`
- `app/cli/purge_cmd.py` — `python -m app.cli purge`
- `tests/test_stats.py` — F9.2
- `tests/test_purge.py` — F11.2
- `tests/test_security_headers.py` — F11.4
- `tests/test_errors.py` — F11.6
- `tests/test_demo_mode.py` — F11.7
- `tests/test_seed_idempotent.py` — F11.8
- `tests/e2e/test_full_flow.py` — Playwright end-to-end (F9 full)
- `tests/test_public_no_pii.py` — G4 scan
- `tests/test_i18n_keys.py` — F10.3 no hard-coded strings
- `tests/test_no_pii_in_logs.py` — F11.5

**Tests required:** F9.1-F9.3, F10.2-F10.4, F11.1-F11.8, G1, G4, G8.

**Acceptance:** A1 small-count suppression. A2 purge. A3 CSP. A4 no horizontal scroll at 375px. A5 end-to-end. A6 idempotent seed. A7 no PII in public pages/logs.
