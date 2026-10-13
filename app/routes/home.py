"""Minimal placeholder home for M1 — fleshed out in M8."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.csrf import get_or_create_csrf
from app.templates import make_templates, render_lang_from_request

router = APIRouter()
templates = make_templates()


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "lang": render_lang_from_request(request),
            "demo_mode": False,
            "csrf_token": get_or_create_csrf(request),
        },
    )
