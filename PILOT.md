# Pilot runbook

This is a step-by-step guide for a small volunteer club running
BloodLink for a single city. Pilot length: **2 weeks**, then a 30-day
review.

## Day 0 — Setup

1. Pick a single coordinator (a club officer). They own the
   `coordinator` account and only they can see donor phone numbers.
2. Provision a server (Render Blueprint, or a small VM).
3. Generate a 32-byte `SECRET_KEY`. Store it in the password manager.
4. Create the coordinator account from the shell:

   ```bash
   .venv/bin/python -m app.cli create-coordinator coord 'STRONG-PASSWORD'
   ```

5. Open the site. `/health` should return 200.

## Day 1 — Seed the areas

Log in as `coord` and add the city's areas (Dhanmondi, Mirpur, etc.).
Areas marked inactive are hidden from public stats and the matching
engine.

## Day 2 — Onboard 5–10 donors by hand

Do not publish the registration link yet. Instead, the coordinator
manually enters 5–10 known donors (with consent) to:

* make sure the matching engine has data to work with
* spot-check the candidate page renders correctly
* confirm the manage link works end-to-end

The donor's manage page is the only place they can:

* mark themselves unavailable
* update their phone
* see their own contact history
* connect a Telegram bot for instant notifications

## Day 3 — Soft launch

Share the registration link with a small group (≤ 50 donors). Watch:

* the matching page for sanity: does the candidate ranking put the
  best match first?
* the stats page: does the small-number suppression feel right? If
  not, raise `SMALL_NUMBER_SUPPRESSION_THRESHOLD`.

## Day 4–7 — First request

When the first real request comes in:

* The requester fills `/request/new`. They get a tokenised URL they
  can share with family.
* The coordinator sees it in `/coordinator/requests` (status PENDING).
* After review, verify (`/coordinator/requests/{id}/verify`).
* The matching page shows ranked candidates.
* For each candidate, click "Record contact" → outcome (contacted,
  accepted, declined, no answer).
* Once a donor accepts, the requester is given a phone number to call
  (reveal-on-click, not in the page HTML by default).
* When the request is fulfilled, close it via `/coordinator/requests/{id}/fulfill`.
* The retention cron will null out the requester's PII after
  `RETENTION_DAYS` (default 30).

## Day 8–14 — Iterate

Things to watch for:

* **Phone numbers**: are they being normalized? +8801712345678
  and 01712345678 should both work.
* **Rate limits**: 5 submissions per IP per hour, 3 active requests
  per phone. Adjust if these are too tight.
* **Telegram opt-in**: if many donors want it, the link page should
  show a one-tap connect flow. Check that the webhook auth is firing.
* **Audit log**: every coordinator action is logged. Review weekly
  via the DB.

## Day 14 — Pilot review

Run through:

* [ ] No PII leaks in the logs (grep logs for `+880`, `01[3-9]\d{8}`)
* [ ] All unverified donors are excluded from stats
* [ ] Inactive areas are excluded
* [ ] Small-number suppression is on
* [ ] Purged requests have empty `requester_name` and `requester_phone_normalized`
* [ ] Telegram webhook rejects requests with a bad `X-Telegram-Bot-Api-Secret-Token`
* [ ] CSRF rejects every form POST without a valid token
* [ ] Login is rate-limited
* [ ] DEMO_MODE is **off** in production (the banner should not show)

If any of these fail, fix before going public. The smoke test
(`scripts/smoke_test.sh`) catches wiring regressions; the pytest suite
catches logic regressions.

## Day 15+ — Go public

* Share the public link in a single broadcast message.
* Keep the public link off search engines. Use `noindex` on the
  homepage if your reverse-proxy doesn't already.
* Monitor the audit log for unusual patterns (rapid registrations
  from a single IP, etc.).

## When to scale

The matching engine is in-process; it is fine up to ~10,000 verified
donors. After that, switch to a worker queue. The current
`ContactAttempt` table is the natural queue.

## When NOT to use BloodLink

* **Emergency services.** A 911-equivalent system is what the public
  should call. BloodLink is for friends-and-family-of-donor
  coordination, not for ambulances.
* **Multi-tenant SaaS.** The data model is single-club by design.
* **High-traffic media attention.** If the URL ends up on the front
  page of a newspaper, expect a flood of sign-ups that will tip the
  stats and need manual cleanup.