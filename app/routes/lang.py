"""Language switch endpoint (F10).

Persists the chosen language in a cookie. Works without JavaScript via the
<noscript> submit button in partials/lang_switch.html.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import i18n as i18n_mod
from app.csrf import CsrfDep

router = APIRouter()


@router.post("/lang", dependencies=[CsrfDep])
async def set_lang(request: Request, lang: str = Form(...)) -> RedirectResponse:
    next_url = request.headers.get("referer") or "/"
    response = RedirectResponse(url=next_url, status_code=303)
    if lang in i18n_mod.SUPPORTED_LANGS:
        response.set_cookie(
            i18n_mod.COOKIE_NAME,
            lang,
            max_age=60 * 60 * 24 * 365,
            path="/",
            samesite="lax",
        )
    return response
