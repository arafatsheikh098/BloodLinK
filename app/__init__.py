"""FastAPI app factory."""
from __future__ import annotations

from fastapi import FastAPI, Request

from app.config import get_settings
from app.db import make_engine, set_engine
from app.middleware import SecurityHeadersMiddleware
from app.session import add_session_middleware
from app.templates import make_templates, mount_static, render_lang_from_request


def create_app() -> FastAPI:
    settings = get_settings()
    settings.validate_production()

    app = FastAPI(
        title="BloodLink",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    engine = make_engine(settings)
    set_engine(engine)

    app.add_middleware(SecurityHeadersMiddleware)
    add_session_middleware(app)

    mount_static(app)
    _register_routes(app)
    _register_error_handlers(app)

    return app


def _register_routes(app: FastAPI) -> None:
    from app.routes import health, home, lang

    app.include_router(health.router)
    app.include_router(home.router)
    app.include_router(lang.router)


def _register_error_handlers(app: FastAPI) -> None:
    templates = make_templates()

    @app.exception_handler(404)
    async def not_found(request: Request, exc):  # type: ignore[no-untyped-def]
        return templates.TemplateResponse(
            request,
            "errors/404.html",
            {
                "lang": render_lang_from_request(request),
                "demo_mode": False,
                "csrf_token": "",
            },
            status_code=404,
        )

    @app.exception_handler(500)
    async def server_error(request: Request, exc):  # type: ignore[no-untyped-def]
        return templates.TemplateResponse(
            request,
            "errors/500.html",
            {
                "lang": render_lang_from_request(request),
                "demo_mode": False,
                "csrf_token": "",
            },
            status_code=500,
        )


# Convenience for uvicorn app:app
app = create_app()
