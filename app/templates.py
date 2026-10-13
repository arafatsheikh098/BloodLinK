"""Jinja2 environment setup and template globals (i18n, csrf, request)."""
from __future__ import annotations

from fastapi import Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import i18n as i18n_mod
from app.config import get_settings

TEMPLATES_DIR = i18n_mod.TRANSLATIONS_DIR.parent / "templates"
STATIC_DIR = i18n_mod.TRANSLATIONS_DIR.parent / "static"


def make_templates() -> Jinja2Templates:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["t"] = i18n_mod.t
    env.globals["get_settings"] = get_settings
    env.filters["t"] = lambda key, **p: i18n_mod.t(key, **p)

    templates = Jinja2Templates(env=env)
    templates.env = env  # type: ignore[attr-defined]

    # Make static_url_for and request context available to templates.
    return templates


def render_lang_from_request(request: Request) -> str:
    cookie = request.cookies.get(i18n_mod.COOKIE_NAME)
    if cookie in i18n_mod.SUPPORTED_LANGS:
        return cookie
    return i18n_mod.DEFAULT_LANG


def is_demo_mode() -> bool:
    return get_settings().demo_mode


def mount_static(app) -> None:
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
