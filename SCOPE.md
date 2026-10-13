# SCOPE.md — the contract (do not edit)

## IN SCOPE
F1 Coordinator auth: login/logout; argon2 (argon2-cffi); signed session cookie (HttpOnly, SameSite=Lax, Secure in production); CSRF on every state-changing request; login rate limit stored in the database; coordinators created by CLI (python -m app.cli create-coordinator) and optionally seeded from env on first start when none exists; app refuses to start in production with the default SECRET_KEY.
F2 Donor registration (public form): name, blood group (A+, A-, B+, B-, AB+, AB-, O+, O-), mobile number, area (chosen from a coordinator-managed list), optional last donation date (not in the future), checkbox "I am 18 or older", checkbox "I consent to being contacted by the club about blood requests", checkbox "I understand the club will call to verify me and that final eligibility is decided at the donation site". No date of birth is stored. Bangladesh mobile numbers are validated and normalized to +8801XXXXXXXXX (operator digit 3-9); duplicates by normalized number are rejected without revealing whether the number exists to anyone but the coordinator view. On success the donor sees a private manage link once (random token, at least 128 bits, stored only as a hash) and a message that a coordinator will call. New donors start unverified and are never matched until a coordinator verifies them.
F3 Donor self-service via the manage link: toggle availability, change area, update last donation date, update phone (resets to unverified), delete my data (hard delete of the donor row and its contact history PII; an anonymous audit entry remains). A lost link is replaced by a coordinator (generate a new link; the old one stops working).
F4 Coordinator donor management: list, search and filter donors (group, area, status, availability); statuses unverified / verified / suspended; verify with an optional short note; record a donation (date, optional request) which updates the last donation date. Phone numbers are masked in lists and shown in full only after an explicit reveal action that is written to the audit log. Notes must be non-medical (the form warns about this).
F5 Blood requests (public form): blood group needed, units (1-10), hospital name, area, needed-by date and time (in the future, at most 14 days ahead), requester name, requester mobile number, short note (max 200 characters, with a warning not to enter medical details), consent to be contacted. Abuse controls: hidden honeypot field, rate limit per IP (5 per hour) and per phone (3 active requests), no JavaScript required. The requester gets a private tracking link (random token) showing status and allowing cancellation. Whole blood only; platelets and plasma are out of scope.
F6 Request lifecycle: pending, verified, fulfilled, cancelled, expired. A coordinator phones the requester, then marks the request verified or rejected (with reason). Requests past their needed-by time are shown as expired (computed on read, no background scheduler required). Only verified requests can be matched.
F7 Matching: for a verified request, list candidate donors who are verified, available, not suspended, eligible (last donation older than MIN_DONATION_GAP_DAYS, configurable, default 120, or never donated), and blood-group compatible for red-cell transfusion using the standard compatibility table (O- donates to all; AB+ receives from all; Rh-negative recipients are never matched with Rh-positive donors). Rank by: exact group match first, then same area, then longest time since last donation, then donor id for stable order. Show why each donor matched. A donor contacted for another request in the last 24 hours (configurable) is flagged, not hidden. Coordinators record a contact attempt per donor per request: contacted, accepted, declined, no answer, donated. Marking donated updates the donor's last donation date.
F8 Optional Telegram notifications (enabled only when TELEGRAM_BOT_TOKEN is set): a donor can link their Telegram from the manage page using a one-time code sent to the bot; a coordinator can notify selected candidates; the message contains blood group, hospital, area and needed-by time only (never requester name or phone); the donor taps Accept or Decline; acceptance is recorded and shown to the coordinator, who then phones the donor. Webhook requests must be authenticated with Telegram's secret-token header; callback data is signed and expires; double taps are idempotent.
F9 Public pages: home (how it works, safety disclaimer, club emergency hotline from settings), request form, donor form, privacy page, and aggregate counts of verified donors by blood group and area with small-number suppression (any cell below 3 is shown as "fewer than 3"). No names, phones or individual donor details are ever public. Public IDs are random tokens, never sequential integers.
F10 Languages: English and Bangla UI with a language toggle; all user-facing strings come from translation dictionaries; a test fails if the two dictionaries differ in keys. Bangla text must be reviewed by a native reader before the app is used by real people.
F11 Privacy and operations: audit log for coordinator actions (verify, suspend, reveal phone, contact attempt, status changes, deletions); `python -m app.cli purge` removes requester names and phones from requests closed more than RETENTION_DAYS ago (default 30); GET /health; security headers (CSP without inline scripts, X-Content-Type-Options, Referrer-Policy, frame-ancestors none); no phone numbers, tokens or names in logs or URLs; custom 404/500 pages; DEMO_MODE shows a banner, uses fake data only and disables Telegram; idempotent demo seed.

## OUT OF SCOPE
SMS or WhatsApp sending, payments, platelet/plasma matching, maps or GPS, donor ratings, appointments, hospital or blood-bank integrations, medical records or screening questions beyond the three checkboxes, user accounts for donors or requesters, mobile app, anything not listed above.

## ALLOWED STACK
Python 3.12; FastAPI; uvicorn; SQLModel; Alembic; psycopg[binary]; pydantic-settings; Jinja2; python-multipart; argon2-cffi; httpx (Telegram Bot API only); vendored HTMX (eval disabled); pytest, pytest-playwright, httpx, freezegun, hypothesis; ruff; Docker, docker compose; GitHub Actions.

## ACCEPTANCE CRITERIA (per feature, testable)

F1 (Coordinator auth):
- F1.1 Wrong password and unknown username return the same generic error through the same code path.
- F1.2 A route-discovery test enumerates every state-changing route and proves it rejects missing CSRF (and, for coordinator routes, missing session).
- F1.3 Login rate limit triggers on the 6th failure within 15 minutes and resets after the window (freezegun).
- F1.4 Session cookie has HttpOnly, SameSite=Lax, and Secure in production.
- F1.5 App refuses to start in production with the default SECRET_KEY.
- F1.6 Coordinators can be created via `python -m app.cli create-coordinator`.
- F1.7 On first start, if no coordinator exists, one is optionally seeded from env vars.

F2 (Donor registration):
- F2.1 All three consent checkboxes are required and the form works without JavaScript.
- F2.2 Bangladesh numbers accepted in 01712345678, +8801712345678, 8801712345678, 017-1234-5678 forms normalize to +8801712345678.
- F2.3 Invalid operator digit (e.g. 012...), landline, too short, too long numbers are rejected.
- F2.4 A donor registered with one form blocks a second registration with another form using the same number.
- F2.5 The one-time manage link is at least 128 bits, stored hashed in DB.
- F2.6 New donors start unverified and are not eligible for matching.
- F2.7 A future last_donation_date is rejected.
- F2.8 Name field with HTML or script is rendered escaped.

F3 (Donor self-service):
- F3.1 Manage link works for the owner; wrong or modified token returns 404 with no info leak.
- F3.2 Token is never stored in plain text (test reads the database).
- F3.3 Donor can toggle availability, change area, update last donation date, update phone.
- F3.4 Updating the phone resets verification to unverified.
- F3.5 Delete-my-data removes the donor row and PII, leaves an anonymous audit entry, and the old link returns 404.
- F3.6 A coordinator can regenerate the manage link; the old one stops working.

F4 (Coordinator donor management):
- F4.1 Phones are masked in every list and detail render.
- F4.2 Reveal action returns the full phone and writes exactly one audit row.
- F4.3 Every status change writes exactly one audit row (parametrized test).
- F4.4 Filters combine correctly (test matrix) and pagination boundaries are correct.
- F4.5 Only coordinators can access these routes (route-discovery covers CSRF).
- F4.6 Recording a donation updates last_donation_date and makes the donor ineligible until the gap has passed (test).
- F4.7 Statuses are unverified / verified / suspended.
- F4.8 Verify accepts an optional short note.
- F4.9 Notes form warns about non-medical content.

F5 (Blood requests):
- F5.1 Validation: units 1-10, needed-by in the future and within 14 days, note max 200 characters, valid normalized phone.
- F5.2 Honeypot-filled submissions are silently discarded without an error page.
- F5.3 The 6th request from one IP within an hour is rejected with 429 (freezegun).
- F5.4 A phone with 3 active requests cannot create a 4th.
- F5.5 The requester gets a private tracking link with status; the form works without JS.
- F5.6 Public request identifiers are random tokens; sequential ids are never exposed.

F6 (Request lifecycle):
- F6.1 A request whose needed-by time has passed shows as expired at the exact boundary (freezegun).
- F6.2 Only verified requests can reach matching.
- F6.3 Coordinator can verify or reject (with reason); unverified or rejected requests never reach matching (test).
- F6.4 The tracking link shows status but no donor information.
- F6.5 Effective status is computed on read; no background scheduler required.

F7 (Matching):
- F7.1 Exhaustive compatibility test over all 8 x 8 pairs against hand-written expected table.
- F7.2 Property: any Rh-negative request never receives an Rh-positive candidate (hypothesis).
- F7.3 One test per exclusion rule: unverified, suspended, unavailable, ineligible by gap (including exact MIN_DONATION_GAP_DAYS boundary day), incompatible group.
- F7.4 Ranking order is deterministic and matches a worked example in the test file.
- F7.5 A donor contacted in the last 24 hours is flagged but still listed.
- F7.6 Marking donated updates last_donation_date and closes that attempt.
- F7.7 Candidate page shows only masked phones with reveal-on-click.
- F7.8 Ranking: exact group match first, then same area, then longest time since last donation, then donor id.
- F7.9 Inactive area is ignored only for ranking, not for eligibility (donors always eligible by area).

F8 (Telegram):
- F8.1 With no token, Telegram UI is hidden and the app works fully.
- F8.2 Linking uses a one-time code that expires and cannot be reused.
- F8.3 The notification text contains only blood group, hospital, area, needed-by time.
- F8.4 The webhook returns 403 without the correct secret header.
- F8.5 Tampered or expired callback data is ignored.
- F8.6 Pressing Accept twice changes state once and sends no duplicate coordinator update.
- F8.7 Telegram API failures are caught, logged without personal data, and shown to the coordinator as "could not notify".
- F8.8 DEMO_MODE disables sending.

F9 (Public pages):
- F9.1 Home, request form, donor form, privacy page, aggregate counts page are all reachable and free of donor PII.
- F9.2 Counts below 3 render as "fewer than 3" and the page never reveals exact small counts (test at 2, 3, 4).
- F9.3 Public IDs are random tokens; no sequential integers in any public URL or page.

F10 (Languages):
- F10.1 English and Bangla dictionaries have identical keys (test fails otherwise).
- F10.2 Language toggle stored in a cookie persists across navigation.
- F10.3 No hard-coded user-facing strings in templates (test).
- F10.4 All user-facing strings come from translation dictionaries.

F11 (Privacy & operations):
- F11.1 Audit log records: verify, suspend, unsuspend, reveal phone, contact attempt, status changes, deletions.
- F11.2 `python -m app.cli purge` removes requester name and phone from requests closed longer than RETENTION_DAYS and leaves open requests untouched (frozen time).
- F11.3 GET /health returns 200.
- F11.4 Security headers: CSP (no inline scripts), X-Content-Type-Options, Referrer-Policy, frame-ancestors none.
- F11.5 No phone numbers, tokens, or names in logs or URLs.
- F11.6 Custom 404/500 pages render the base layout.
- F11.7 DEMO_MODE shows a banner, uses fake data only, and disables Telegram.
- F11.8 Idempotent demo seed: the seed runs twice without duplicates.

## GLOBAL ACCEPTANCE CRITERIA
G1 docker compose up --build serves the app; the demo seed loads; a fresh clone works from the README.
G2 The compatibility table is proven by an exhaustive test over all 8 x 8 donor/recipient pairs against a hand-written expected table kept in the test file, plus the property that no Rh-positive donor is ever matched to an Rh-negative request.
G3 Unverified, suspended, unavailable, ineligible and incompatible donors never appear as candidates (test per case, including the exact boundary of MIN_DONATION_GAP_DAYS).
G4 No public page or response ever contains a donor's name, phone or token (tests scan rendered pages and JSON for seeded phone numbers and names).
G5 Every state-changing route rejects missing CSRF and missing session where a session is required (route-discovery test).
G6 The same donor phone cannot be registered twice, in any input format.
G7 The Telegram webhook rejects requests without the correct secret header, and a duplicated Accept callback changes state once.
G8 The English and Bangla dictionaries have identical keys; no hard-coded user-facing strings in templates (test).
G9 CI is green on PostgreSQL.
