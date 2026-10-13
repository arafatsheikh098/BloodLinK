"""Coordinator login / logout (F1)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.audit import write_audit
from app.csrf import CsrfDep, get_or_create_csrf
from app.db import get_session
from app.deps import (
    flash,
    get_current_coordinator,
    hash_username,
    is_rate_limited,
    pop_flashes,
)
from app.models.audit_log import AuditAction
from app.models.coordinator import Coordinator
from app.models.login_attempt import LoginAttempt
from app.security import verify_password
from app.templates import make_templates, render_lang_from_request

router = APIRouter()
templates = make_templates()


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "error": None,
            "rate_limited": False,
            "flashes": pop_flashes(request),
        },
    )


@router.post("/login", dependencies=[CsrfDep])
def login_submit(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    username: str = Form(...),
    password: str = Form(...),
) -> HTMLResponse:
    username = username.strip()
    now = datetime.now(UTC)
    ip = _client_ip(request)
    rate_limited = is_rate_limited(session, username, now)

    if rate_limited:
        # Always log the attempt; do not reveal whether the username exists.
        session.add(
            LoginAttempt(
                username=username,
                username_hash=hash_username(username),
                coordinator_id=None,
                success=False,
                source_ip=ip,
                created_at=now,
            )
        )
        session.commit()
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {
                "lang": render_lang_from_request(request),
                "csrf_token": get_or_create_csrf(request),
                "error": "rate_limited",
                "rate_limited": True,
                "flashes": [],
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    coord = session.exec(
        select(Coordinator).where(Coordinator.username == username)
    ).first()

    # F1.1: same generic error through the same code path for both
    # "unknown username" and "wrong password".
    if coord and coord.is_active and verify_password(coord.password_hash, password):
        session.add(
            LoginAttempt(
                username=username,
                username_hash=hash_username(username),
                coordinator_id=coord.id,
                success=True,
                source_ip=ip,
                created_at=now,
            )
        )
        write_audit(
            session,
            AuditAction.LOGIN_SUCCESS,
            actor_kind="coordinator",
            coordinator_id=coord.id,
        )
        session.commit()
        request.session["coordinator_id"] = coord.id
        return RedirectResponse(url="/", status_code=303)

    # Failure path: log the attempt (with no coordinator_id if username unknown)
    session.add(
        LoginAttempt(
            username=username,
            username_hash=hash_username(username),
            coordinator_id=coord.id if coord else None,
            success=False,
            source_ip=ip,
            created_at=now,
        )
    )
    write_audit(
        session,
        AuditAction.LOGIN_FAILURE,
        actor_kind="anonymous",
        coordinator_id=coord.id if coord else None,
    )
    session.commit()
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "error": "invalid",
            "rate_limited": False,
            "flashes": [],
        },
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@router.post("/logout", dependencies=[CsrfDep])
def logout(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: Annotated[Coordinator, Depends(get_current_coordinator)],
) -> RedirectResponse:
    write_audit(
        session,
        AuditAction.LOGOUT,
        actor_kind="coordinator",
        coordinator_id=current.id,
    )
    session.commit()
    request.session.clear()
    flash(request, "success", "You have been logged out.")
    return RedirectResponse(url="/", status_code=303)
