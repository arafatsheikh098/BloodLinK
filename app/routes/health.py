"""Liveness probe (F11.3)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
