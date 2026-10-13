"""Idempotent demo seed (F11.7, F11.8).

Seeds fake areas, donors, and one pending request. Phone numbers are
clearly fake (e.g. starting with 01700000000) and are never real BD
mobile numbers. Re-running is safe: existing rows are left alone.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, select

from app.models.area import Area
from app.models.donor import BLOOD_GROUPS, Donor, DonorStatus
from app.models.request import BloodRequest, RequestStatus
from app.phone import normalize_bd_mobile
from app.tokens import hash_token, new_token

_DEMO_PHONE_PREFIX = "017555"  # operator 5 is valid; 555 is reserved for fiction


def _demo_phones() -> dict[str, str]:
    """Return a phone (11 digits, valid format) for each group."""
    return {
        "A+": "01755500001",
        "A-": "01755500002",
        "B+": "01755500003",
        "B-": "01755500004",
        "AB+": "01755500005",
        "AB-": "01755500006",
        "O+": "01755500007",
        "O-": "01755500008",
    }


def seed_demo(engine: Any = None) -> None:
    """Idempotently insert demo data."""
    if engine is None:
        from app.db import get_engine

        engine = get_engine()
    with Session(engine) as session:
        existing_areas = {a.name: a for a in session.exec(select(Area)).all()}
        demo_areas = ["Dhanmondi", "Mirpur", "Uttara"]
        area_objs: dict[str, Area] = {}
        for name in demo_areas:
            if name in existing_areas:
                area_objs[name] = existing_areas[name]
                continue
            a = Area(name=name, is_active=True)
            session.add(a)
            session.flush()
            area_objs[name] = a
        # Encode both group and copy in the phone so each (group, copy) has a
        # unique 11-digit phone. 017555[gi:2d][copy][00]
        group_index = {bg: i + 1 for i, bg in enumerate(BLOOD_GROUPS)}
        for bg in BLOOD_GROUPS:
            gi = group_index[bg]
            for copy in range(3):
                copy_phone = f"017555{gi:02d}{copy}00"
                existing = session.exec(
                    select(Donor).where(
                        Donor.phone_normalized == normalize_bd_mobile(copy_phone)
                    )
                ).first()
                if existing:
                    continue
                d = Donor(
                    manage_token_hash=hash_token(new_token(24)),
                    name=f"Demo {bg}-{copy + 1}",
                    blood_group=bg,
                    phone_normalized=normalize_bd_mobile(copy_phone),
                    area_id=area_objs[demo_areas[copy % len(demo_areas)]].id,
                    last_donation_date=None,
                    is_available=True,
                    status=DonorStatus.VERIFIED.value,
                    is_over_18=True,
                    consent_contact=True,
                    consent_verify=True,
                )
                session.add(d)
        existing_req = session.exec(
            select(BloodRequest).where(
                BloodRequest.hospital_name == "Demo Hospital"
            )
        ).first()
        if not existing_req:
            r = BloodRequest(
                public_token_hash=hash_token(new_token(24)),
                blood_group="A+",
                units=2,
                hospital_name="Demo Hospital",
                area_id=area_objs["Dhanmondi"].id,
                needed_by=datetime.now(UTC) + timedelta(hours=12),
                requester_name="Demo Requester",
                requester_phone_normalized=normalize_bd_mobile("01755500099"),
                note="Demo only.",
                consent_contact=True,
                status=RequestStatus.PENDING.value,
            )
            session.add(r)
        session.commit()
