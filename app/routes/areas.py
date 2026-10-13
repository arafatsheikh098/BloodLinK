"""Area management for coordinators (needed by the donor and request forms)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.audit import write_audit
from app.csrf import CsrfDep, get_or_create_csrf
from app.db import get_session
from app.deps import RequireCoordinator, flash, pop_flashes
from app.models.area import Area
from app.models.audit_log import AuditAction
from app.templates import make_templates, render_lang_from_request

router = APIRouter()
templates = make_templates()


def _list_active_areas(session: Session) -> list[Area]:
    return list(
        session.exec(
            select(Area).where(Area.is_active == True).order_by(Area.name)  # noqa: E712
        ).all()
    )


def _all_areas(session: Session) -> list[Area]:
    return list(session.exec(select(Area).order_by(Area.name)).all())


@router.get("/areas", response_class=HTMLResponse)
def areas_index(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "coordinator/areas/list.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "flashes": pop_flashes(request),
            "areas": _all_areas(session),
        },
    )


@router.post("/areas", dependencies=[CsrfDep])
def areas_create(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
    name: str = Form(...),
) -> RedirectResponse:
    name = name.strip()
    if not name:
        flash(request, "error", "Area name is required.")
        return RedirectResponse(url="/areas", status_code=303)
    existing = session.exec(select(Area).where(Area.name == name)).first()
    if existing:
        flash(request, "error", "An area with this name already exists.")
        return RedirectResponse(url="/areas", status_code=303)
    area = Area(name=name, is_active=True)
    session.add(area)
    session.flush()
    write_audit(
        session,
        AuditAction.AREA_CREATE,
        coordinator_id=_current.id,
        donor_id=None,
        detail=f"area_id={area.id}",
    )
    session.commit()
    flash(request, "success", "Area created.")
    return RedirectResponse(url="/areas", status_code=303)


@router.post("/areas/{area_id}/rename", dependencies=[CsrfDep])
def areas_rename(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
    area_id: int,
    name: str = Form(...),
) -> RedirectResponse:
    area = session.get(Area, area_id)
    if not area:
        raise HTTPException(status_code=404, detail="area not found")
    name = name.strip()
    if not name:
        flash(request, "error", "Area name is required.")
        return RedirectResponse(url="/areas", status_code=303)
    existing = session.exec(select(Area).where(Area.name == name, Area.id != area_id)).first()
    if existing:
        flash(request, "error", "An area with this name already exists.")
        return RedirectResponse(url="/areas", status_code=303)
    old_name = area.name
    area.name = name
    write_audit(
        session,
        AuditAction.AREA_RENAME,
        coordinator_id=_current.id,
        detail=f"area_id={area_id}",
    )
    session.commit()
    flash(request, "success", f"Renamed {old_name} to {name}.")
    return RedirectResponse(url="/areas", status_code=303)


@router.post("/areas/{area_id}/deactivate", dependencies=[CsrfDep])
def areas_deactivate(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
    area_id: int,
) -> RedirectResponse:
    area = session.get(Area, area_id)
    if not area:
        raise HTTPException(status_code=404, detail="area not found")
    area.is_active = False
    write_audit(
        session,
        AuditAction.AREA_DEACTIVATE,
        coordinator_id=_current.id,
        detail=f"area_id={area_id}",
    )
    session.commit()
    flash(request, "success", "Area deactivated.")
    return RedirectResponse(url="/areas", status_code=303)