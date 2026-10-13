"""Aggregate statistics for the public /stats page (F9.2).

Only counts of VERIFIED donors are surfaced, broken down by blood group and
area. Any cell with fewer than the small-number-suppression threshold (from
settings, default 3) is rendered as "fewer than <threshold>" so we never
leak exact small counts (F9.2).

We never include names, phones, public tokens, or any other PII.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import Session, select

from app.config import get_settings
from app.models.area import Area
from app.models.donor import BLOOD_GROUPS, Donor, DonorStatus


@dataclass
class StatsCell:
    blood_group: str
    area_id: int
    count: int  # exact count when >= threshold; otherwise 0 (we render "fewer than N")
    suppressed: bool  # True when count < threshold


@dataclass
class StatsTable:
    """A 2D matrix indexed by blood group and area name."""
    rows: list[str]  # area names (only active areas with at least one donor)
    columns: list[str]  # all 8 blood groups in canonical order
    cells: dict[tuple[str, str], StatsCell]
    threshold: int
    total: int


def compute_stats(session: Session) -> StatsTable:
    """Return a stats table with small-number suppression."""
    settings = get_settings()
    threshold = settings.small_number_suppression_threshold

    # Only count verified donors
    stmt = (
        select(Donor.blood_group, Donor.area_id, func.count(Donor.id))
        .where(Donor.status == DonorStatus.VERIFIED.value)
        .group_by(Donor.blood_group, Donor.area_id)
    )
    raw = session.exec(stmt).all()  # list of (bg, area_id, n)

    # Active areas only
    areas = list(
        session.exec(
            select(Area).where(Area.is_active == True).order_by(Area.name)  # noqa: E712
        ).all()
    )

    cells: dict[tuple[str, str], StatsCell] = {}
    area_seen: set[int] = set()
    total = 0
    for bg, area_id, n in raw:
        area = next((a for a in areas if a.id == area_id), None)
        if not area:
            continue
        area_seen.add(area.id)
        if n >= threshold:
            cells[(area.name, bg)] = StatsCell(
                blood_group=bg,
                area_id=area.id,
                count=n,
                suppressed=False,
            )
            total += n
        else:
            cells[(area.name, bg)] = StatsCell(
                blood_group=bg,
                area_id=area.id,
                count=0,
                suppressed=True,
            )

    # Only include areas that actually had at least one verified donor, OR
    # areas that exist and could potentially have donors (so the page doesn't
    # feel broken if the seed has zero donors somewhere).
    rows = [a.name for a in areas if a.id in area_seen or True]
    # Keep order matching `areas`
    return StatsTable(
        rows=rows,
        columns=list(BLOOD_GROUPS),
        cells=cells,
        threshold=threshold,
        total=total,
    )