"""Common FastAPI dependencies: database session, current coordinator."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.db import get_session
from app.models.coordinator import Coordinator
from app.models.login_attempt import LoginAttempt

# Rate limit window and threshold (F1.3)
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_MAX_FAILS = 5


def hash_username(username: str) -> str:
    return hashlib.sha256(username.lower().encode("utf-8")).hexdigest()


def recent_failed_login_count(session: Session, username: str, now: datetime) -> int:
    cutoff = now - LOGIN_WINDOW
    stmt = select(LoginAttempt).where(
        LoginAttempt.username_hash == hash_username(username),
        LoginAttempt.success == False,  # noqa: E712
        LoginAttempt.created_at >= cutoff,
    )
    return len(session.exec(stmt).all())


def is_rate_limited(session: Session, username: str, now: datetime) -> bool:
    return recent_failed_login_count(session, username, now) >= LOGIN_MAX_FAILS


def get_current_coordinator(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Coordinator:
    coord_id = request.session.get("coordinator_id")
    if not coord_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    coord = session.get(Coordinator, coord_id)
    if not coord or not coord.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    return coord


RequireCoordinator = Annotated[Coordinator, Depends(get_current_coordinator)]


def flash(request: Request, level: str, message: str) -> None:
    """Stash a one-shot flash message in the session."""
    flashes = request.session.get("_flashes", [])
    flashes.append({"level": level, "message": message})
    request.session["_flashes"] = flashes


def pop_flashes(request: Request) -> list[dict[str, str]]:
    flashes = request.session.pop("_flashes", [])
    return flashes
