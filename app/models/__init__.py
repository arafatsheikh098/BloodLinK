"""SQLModel entities.

Each module defines one or more tables. Imported here so SQLModel.metadata
picks them all up before Alembic autogenerate runs.
"""
from app.models.area import Area
from app.models.audit_log import AuditLog
from app.models.contact_attempt import ContactAttempt
from app.models.coordinator import Coordinator
from app.models.donor import Donor, DonorStatus
from app.models.login_attempt import LoginAttempt
from app.models.request import BloodRequest, RequestStatus
from app.models.telegram_link import TelegramLink

__all__ = [
    "Area",
    "AuditLog",
    "BloodRequest",
    "ContactAttempt",
    "Coordinator",
    "Donor",
    "DonorStatus",
    "LoginAttempt",
    "RequestStatus",
    "TelegramLink",
]
