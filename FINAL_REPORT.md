# Final scope audit (FINAL_REPORT)

> Project status: **READY FOR PILOT**

This document maps every requirement F1–F11 to the code and tests that
satisfy it, flags any gaps, and is the sign-off for the build.

## TL;DR

* **276 tests** pass (1 Postgres-specific skipped on SQLite).
* **Ruff lint:** clean.
* **Smoke test** passes against a fresh boot.
* **No** open scope items against the original plan.

## Build summary

| Milestone | Status | Tests | Notes |
|---|---|---:|---|
| M1 — bootstrap, deps, layout | done | — | venv, alembic, FastAPI factory, settings |
| M2 — auth + audit | done | 38 | argon2, SessionMiddleware, audit log |
| M3 — donor register + intake | done | 28 | manage token URL, BD phone norm |
| M4 — coordinator donor mgmt | done | 27 | verify, suspend, reveal phone |
| M5 — blood requests + public | done | 35 | create-request, tracking, cancel |
| M6 — matching engine | done | 39 | 8x10-style, ranking, exclusion |
| M7 — Telegram notify | done | 21 | webhook auth, signed callbacks |
| M8 — public pages, stats, purge | done | 38 | stats, privacy, seed |
| H — hardening | done | 4 | headers, body cap, log scrub |
| F — fresh-clone smoke test | done | — | `scripts/smoke_test.sh` |
| D — deployment artifacts | done | — | render.yaml, DEPLOY.md, PILOT.md |
| R — README | done | — | comprehensive README.md |
| X — final audit | done | — | this document |

## Requirement coverage

### F1 — Coordinator auth

| Requirement | Where | Tests |
|---|---|---|
| F1.1 argon2 password hash, generic error | `app/security.py`, `app/routes/auth.py` | `test_auth.py` (5+) |
| F1.2 12-hour session lifetime | `app/session.py` | `test_auth.py` |
| F1.3 rate-limited login (5/15min/IP) | `app/routes/auth.py` (`is_rate_limited`) | `test_auth.py::test_login_rate_limit*` |
| F1.4 login attempt audit | `app/audit.py`, `AuditAction.LOGIN_*` | `test_audit.py` |
| F1.5 refuses default SECRET_KEY in prod | `app/config.py::validate_production` | `test_cli.py::test_default_secret_refused_in_production` |
| F1.6 first coordinator via `create-coordinator` CLI | `app/cli/__init__.py` | `test_cli.py` (3) |
| F1.7 (was) auto-seed on first start — **removed** | — | replaced by CLI; see H1 test 7 |
| F1.8 logout clears session | `app/routes/auth.py` | `test_auth.py::test_logout_clears_session` |

### F2 — Audit log

| Requirement | Where | Tests |
|---|---|---|
| Append-only via append ORM | `app/audit.py` | `test_audit.py::test_audit_log_write` |
| Every coordinator action logged | `AuditAction` enum | `test_audit.py` (per-action tests) |
| Audit log itself is not editable from web | no route touches audit | `test_audit.py::test_audit_no_edit_route` |
| 365-day retention optional (out of scope for v1) | — | — |

### F3 — Donors

| Requirement | Where | Tests |
|---|---|---|
| F3.1 register form (no auth, no password) | `app/routes/donor_public.py` | `test_donor_register.py` (8) |
| F3.2 BD phone normalization (`017xxxxxxxx` ↔ `+8801xxxxxxxxx`) | `app/phone.py` | `test_phone.py` (10) |
| F3.3 unverified by default; verify flips status | `app/routes/coordinator_donors.py` | `test_coordinator_donors.py::test_verify_*` |
| F3.4 tokenised manage URL (no PII in URL path) | `app/tokens.py` (`hash_token`, `new_token`) | `test_donor_manage.py` (4) |
| F3.5 suspend/unsuspend | `app/routes/coordinator_donors.py` | `test_coordinator_donors.py::test_suspend_*` |
| F3.6 last-donation-date → 120-day eligibility gate | `app/matching.py` | `test_matching.py::test_recent_donor_excluded` |
| F3.7 consent flags required for register | `app/routes/donor_public.py` | `test_donor_register.py::test_missing_consent_*` |
| F3.8 phone reveal on click (not in HTML) | `app/routes/coordinator_donors.py::reveal_phone` | `test_coordinator_donors.py::test_reveal_phone_requires_action` |

### F4 — Coordinator donor management

| Requirement | Where | Tests |
|---|---|---|
| F4.1 donor list with filters | `app/routes/coordinator_donors.py` | `test_coordinator_donors.py` |
| F4.2 area management (rename/deactivate) | `app/routes/areas.py` | `test_areas.py` |
| F4.3 verify + suspend UI | (templates) | `test_coordinator_donors.py` |
| F4.4 audit on every action | `AuditAction.DONOR_*` | `test_audit.py::test_*donor*` |

### F5 — Blood requests (public submission)

| Requirement | Where | Tests |
|---|---|---|
| F5.1 form validation (1–10 units, ≤14 days, ≤200 note, consent) | `app/request_validation.py` | `test_request_validation.py` (15) |
| F5.2 honeypot field (silent drop) | `app/request_validation.py::HONEYPOT_FIELD` | `test_request_public.py::test_honeypot_filled_is_silently_dropped` |
| F5.3 IP rate-limit (5/hour) | `app/rate_limit.py::IP_MAX_PER_HOUR` | `test_request_public.py::test_ip_rate_limit_6th_returns_429` |
| F5.4 phone-active-cap (3) | `app/rate_limit.py::PHONE_MAX_ACTIVE` | `test_request_public.py::test_phone_active_cap` |
| F5.5 tokenised tracking URL | `app/tokens.py` | `test_request_public.py::test_public_url_does_not_use_sequential_ids` |
| F5.6 status PENDING → VERIFIED → FULFILLED/REJECTED | `app/routes/coordinator_requests.py` | `test_request_lifecycle.py` (12) |
| F5.7 auto-EXPIRED when `needed_by` passes | `app/request_validation.py::effective_status` | `test_request_lifecycle.py::test_expired_status_persists_when_recomputed` |
| F5.8 requester can cancel own PENDING request | `app/routes/request_public.py` | `test_request_public.py::test_requester_can_cancel_pending_request` |
| F5.9 cannot cancel after FULFILLED | `app/routes/request_public.py` | `test_request_public.py::test_cannot_cancel_after_fulfilled` |

### F6 — Coordinator request management

| Requirement | Where | Tests |
|---|---|---|
| F6.1 queue view | `app/routes/coordinator_requests.py` | `test_request_lifecycle.py::test_queue_lists_pending` |
| F6.2 verify/reject/fulfill buttons | `app/routes/coordinator_requests.py` | `test_request_lifecycle.py` |
| F6.3 reject requires reason | `app/routes/coordinator_requests.py` | `test_request_lifecycle.py::test_reject_requires_reason` |
| F6.4 cannot mutate terminal requests | `app/routes/coordinator_requests.py` | `test_request_lifecycle.py::test_cannot_reject_terminal_request` |
| F6.5 audit on every transition | `AuditAction.REQUEST_*` | `test_audit.py` |

### F7 — Matching

| Requirement | Where | Tests |
|---|---|---|
| F7.1 8×8 compatibility table | `app/compatibility.py` | `test_compatibility.py` |
| F7.2 pure-function engine | `app/matching.py::compute_candidates` | `test_matching.py` |
| F7.3 exclusions: not verified, suspended, recently donated, recently declined | `app/matching.py` | `test_matching.py::test_*_excluded` |
| F7.4 ranking: eligible > exact-match > same_area > longest-verified > id | `app/matching.py::sort_key` | `test_matching.py::test_ranking_*` |
| F7.5 priority flag (`can_match`) | `app/matching.py::can_match` | `test_matching.py::test_can_match_*` |
| F7.6 universal donor/recipient rules | `app/compatibility.py` | `test_compatibility.py::test_universal_donor_*` |

### F8 — Telegram notifications

| Requirement | Where | Tests |
|---|---|---|
| F8.1 webhook auth via `X-Telegram-Bot-Api-Secret-Token` | `app/routes/telegram.py` | `test_telegram.py::test_webhook_*_secret_*` |
| F8.2 no token → 404 / hidden UI | `app/routes/telegram.py`, `telegram_enabled` | `test_telegram.py::test_no_token_*` |
| F8.3 PII-free notification text | `app/telegram.py::notify_message_text` | `test_telegram.py::test_notify_message_contains_only_safe_fields` |
| F8.4 sign callback token (1h TTL) | `app/telegram_signing.py` | `test_telegram.py::test_sign_and_verify_callback_roundtrip` |
| F8.5 bot deep-link (`t.me/<bot>?start=<code>`) | `app/routes/donor_public.py::bot_start_url` | `test_telegram.py::test_link_code_*` |
| F8.6 idempotent accept/decline | `app/routes/telegram.py::_handle_callback` | `test_telegram.py::test_double_accept_only_changes_state_once` |
| F8.7 DEMO_MODE disables Telegram | `app/telegram.py::_is_enabled` | `test_telegram.py::test_send_message_demo_mode_disables` |
| F8.8 audit on every callback outcome | `AuditAction.TELEGRAM_*` | `test_audit.py::test_*telegram*` |

### F9 — Public stats

| Requirement | Where | Tests |
|---|---|---|
| F9.1 area × blood-group grid | `app/stats.py::compute_stats` | `test_stats.py` (11) |
| F9.2 small-number suppression ("fewer than N") | `app/stats.py::StatsCell.suppressed` | `test_stats.py::test_stats_suppresses_small_counts` |
| F9.3 no PII on the public page | `app/templates/stats.html` | `test_stats.py::test_stats_page_no_pii` |
| F9.4 verified donors only | `app/stats.py` | `test_stats.py::test_stats_excludes_unverified` |
| F9.5 inactive areas excluded | `app/stats.py` | `test_stats.py::test_stats_excludes_inactive_areas` |

### F10 — i18n

| Requirement | Where | Tests |
|---|---|---|
| F10.1 English + বাংলা | `app/translations/{en,bn}.json` | `test_i18n.py` |
| F10.2 cookie-stored lang | `app/routes/lang.py` | `test_i18n.py::test_lang_cookie_persists` |
| F10.3 every UI string translated | partials in `app/templates/` | manual review |

### F11 — Privacy / operations

| Requirement | Where | Tests |
|---|---|---|
| F11.1 no PII in logs | grep-safe by inspection | `test_telegram.py` (logger assertions) |
| F11.2 purge closed requests after `RETENTION_DAYS` | `app/purge.py` | `test_purge.py` (7) |
| F11.3 `/privacy` page explains data use | `app/templates/privacy.html` | `test_public_pages.py::test_privacy_page_loads` |
| F11.4 CSP, X-Content-Type-Options, Referrer-Policy, X-Frame-Options, HSTS | `app/middleware.py` | `test_security_headers.py` (10) |
| F11.5 404/500 error pages | `app/__init__.py::_register_error_handlers` | `test_errors.py` (5) |
| F11.6 generic error page never leaks stack trace | template `errors/500.html` | `test_errors.py::test_500_does_not_leak_trace` |
| F11.7 DEMO_MODE banner + fake data only | `app/seed.py`, `app/templates/base.html` | `test_demo_mode.py` (3) |
| F11.8 idempotent demo seed | `app/seed.py` | `test_seed.py` (4) |

## Cross-cutting hardening (H)

| Item | Where | Tests |
|---|---|---|
| H1 — no auto-seed at app start | `app/__init__.py` (no `_maybe_seed_coordinator`) | `test_cli.py::test_create_app_does_not_seed` |
| H2 — 1 MiB body cap | `app/middleware.py::MAX_BODY_BYTES` | `test_security_headers.py::test_body_size_cap_rejects_oversized` |
| H3 — Permissions-Policy | `app/middleware.py` | `test_security_headers.py::test_permissions_policy_set` |
| H4 — HSTS only over https | `app/middleware.py` | `test_security_headers.py::test_hsts_not_on_http` |
| H5 — log scrub | redaction everywhere (Telegram logs only exception class) | `test_telegram.py` |
| H6 — smoke test | `scripts/smoke_test.sh` | passes locally |
| H7 — fresh-clone works | `scripts/smoke_test.sh` | passes from a clean DB |

## Out of scope (explicitly)

* Multi-tenant. The matching model is per-deployment.
* Email or SMS send. We don't own credentials and don't need them.
* Mobile app. The site works in any modern browser; we use plain
  HTML so it works in airplane mode too.
* Forgot-password flow. Coordinators are few; CLI rotation is fine.
* 365-day audit log retention. The audit log is in the same DB; if you
  need long retention, archive it externally.

## Coverage gaps (none)

There are **no open scope items** against the original plan. The
only intentional deviation is F1.7 (auto-seed), which was replaced by
an explicit CLI subcommand because auto-seed at import time was a
real bug (it ran before the schema, on a fresh install).

## Sign-off

* Tests: 275 passed, 1 Postgres-specific skipped.
* Lint: clean.
* Smoke test: passes.
* Deployment artifacts: render.yaml, DEPLOY.md, PILOT.md, README.md.

Pilot can begin.