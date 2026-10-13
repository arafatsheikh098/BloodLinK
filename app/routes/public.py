"""Public pages: home, privacy, stats (F9.1, F9.2, F9.3)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.csrf import get_or_create_csrf
from app.db import get_session
from app.deps import pop_flashes
from app.stats import compute_stats
from app.templates import make_templates, render_lang_from_request

router = APIRouter()
templates = make_templates()


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> HTMLResponse:
    from app.templates import is_demo_mode

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "lang": render_lang_from_request(request),
            "demo_mode": is_demo_mode(),
            "csrf_token": get_or_create_csrf(request),
            "flashes": pop_flashes(request),
            "stats": compute_stats(session),
        },
    )


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request) -> HTMLResponse:
    from app.templates import is_demo_mode

    return templates.TemplateResponse(
        request,
        "privacy.html",
        {
            "lang": render_lang_from_request(request),
            "demo_mode": is_demo_mode(),
            "csrf_token": get_or_create_csrf(request),
        },
    )


@router.get("/stats", response_class=HTMLResponse)
def stats(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> HTMLResponse:
    from app.templates import is_demo_mode

    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "lang": render_lang_from_request(request),
            "demo_mode": is_demo_mode(),
            "csrf_token": get_or_create_csrf(request),
            "stats": compute_stats(session),
        },
    )
