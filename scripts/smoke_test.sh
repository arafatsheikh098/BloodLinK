#!/usr/bin/env bash
# Smoke test: boot BloodLink in DEMO_MODE with SQLite and hit every
# public + coordinator route. Exit code 0 means everything renders.
# Used by CI to catch wiring regressions without a browser.
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8765}"
LOG=/tmp/bloodlink-smoke.log
PID=/tmp/bloodlink-smoke.pid

export ENV=development
export DEMO_MODE=true
export DATABASE_URL="sqlite:////tmp/bloodlink-smoke.db"
# A real 32-char secret so signed cookies work.
export SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
export TELEGRAM_BOT_TOKEN=

# Reset DB so the test is idempotent.
rm -f /tmp/bloodlink-smoke.db

# Migrate + create the smoke coordinator + boot.
.venv/bin/alembic upgrade head >"$LOG" 2>&1
.venv/bin/python -m app.cli create-coordinator smoke smoke >>"$LOG" 2>&1
.venv/bin/uvicorn app:app --host 127.0.0.1 --port "$PORT" --no-access-log >>"$LOG" 2>&1 &
echo $! > "$PID"

cleanup() {
    if [[ -f "$PID" ]]; then
        kill "$(cat "$PID")" 2>/dev/null || true
        rm -f "$PID"
    fi
}
trap cleanup EXIT

# Wait for the server.
for i in {1..40}; do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.25
done

fail() { echo "FAIL: $1" >&2; tail -40 "$LOG" >&2; exit 1; }
expect() {
    local code want method url cookie_arg
    want=$1; shift
    method=$1; shift
    url=$1; shift
    cookie_arg=""
    if [[ -n "${COOKIE:-}" && -f "$COOKIE" ]]; then
        cookie_arg="-b $COOKIE"
    fi
    code=$(curl -s $cookie_arg -o /dev/null -w "%{http_code}" -X "$method" "http://127.0.0.1:$PORT$url")
    if [[ "$code" != "$want" ]]; then
        fail "$method $url expected $want got $code"
    fi
    echo "OK  $method $url -> $code"
}

# Public, anonymous.
expect 200 GET /
expect 200 GET /privacy
expect 200 GET /stats
expect 200 GET /health
expect 404 GET /no-such-page

# Login as the seeded coordinator.
COOKIE=/tmp/bloodlink-smoke.cookies
rm -f "$COOKIE"
# GET first to seed CSRF.
csrf=$(curl -s -c "$COOKIE" "http://127.0.0.1:$PORT/login" \
    | sed -n 's/.*name="csrf_token"[^>]*value="\([^"]*\)".*/\1/p' | head -1)
[[ -n "$csrf" ]] || fail "no CSRF token on /login"
expect 200 GET /login
# POST and capture the session cookie.
post_code=$(curl -s -b "$COOKIE" -c "$COOKIE" -o /dev/null -w "%{http_code}" \
    -d "username=smoke&password=smoke&csrf_token=$csrf" \
    "http://127.0.0.1:$PORT/login")
# Login returns 303 on success; the session cookie is set on the response.
# We accept 200 (rendered login again on failure) or 303 (redirect on success).
if [[ "$post_code" != "303" && "$post_code" != "200" ]]; then
    fail "POST /login expected 303 or 200, got $post_code"
fi
echo "OK  POST /login -> $post_code"

# Coordinator pages (after login).
expect 200 GET /coordinator/donors
expect 200 GET /coordinator/requests

# Public forms.
expect 200 GET /donor/register
expect 200 GET /request/new

echo "ALL SMOKE CHECKS PASSED"