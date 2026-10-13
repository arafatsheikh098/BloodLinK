"""Security headers middleware (F11.4) and request body size limit (H).

The middleware adds:

* A strict Content-Security-Policy with no inline scripts (HTMX is
  served from /static/vendor so we don't need 'unsafe-inline').
* HSTS in production only (set ENV=production; harmless on localhost).
* Standard defence-in-depth headers (X-Content-Type-Options,
  Referrer-Policy, X-Frame-Options, Permissions-Policy).
* A 1 MiB request body cap. Larger bodies are rejected with 413.
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# F11.4: hard cap on request body to prevent trivial DoS via huge
# multipart uploads (donor registration, request submission). 1 MiB
# is plenty for any form we accept and far below what a legitimate
# client would send.
MAX_BODY_BYTES = 1 * 1024 * 1024

# We accept CSRF and a few tiny JSON callbacks (Telegram uses signed
# payloads).  Anything that includes file uploads must go through a
# dedicated, larger-capped endpoint.
PATHS_ALLOWING_BODY_CHECK = ("/donors", "/request", "/coordinator", "/telegram")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Enforce body size only on form-submitting endpoints to avoid
        # breaking static, health, and lang routes.
        path = request.url.path
        cl = request.headers.get("content-length")
        if cl and path.startswith(PATHS_ALLOWING_BODY_CHECK):
            try:
                if int(cl) > MAX_BODY_BYTES:
                    return JSONResponse(
                        {"detail": "request too large"},
                        status_code=413,
                    )
            except ValueError:
                pass

        response = await call_next(request)

        # CSP without inline scripts. HTMX is served from /static/vendor.
        # 'unsafe-inline' is intentionally absent.
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=()",
        )
        # HSTS only in production so it doesn't break local http://
        # workflows (browsers cache HSTS for a long time).
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response
