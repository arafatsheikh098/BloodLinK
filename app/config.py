"""Application configuration via pydantic-settings.

All env vars are documented in .env.example. The default SECRET_KEY is rejected
when ENV=production (see F1.5 / M2 acceptance).
"""
from __future__ import annotations

import secrets
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "change-me-in-production-this-is-not-a-real-secret-do-not-use"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    env: str = Field(default="development", alias="ENV")
    secret_key: str = Field(default=DEFAULT_SECRET_KEY, alias="SECRET_KEY")

    database_url: str = Field(default="sqlite:///./bloodlink.db", alias="DATABASE_URL")

    demo_mode: bool = Field(default=False, alias="DEMO_MODE")

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str | None = Field(
        default=None, alias="TELEGRAM_WEBHOOK_SECRET"
    )
    telegram_public_base_url: str | None = Field(
        default=None, alias="TELEGRAM_PUBLIC_BASE_URL"
    )

    display_timezone: str = Field(default="Asia/Dhaka", alias="DISPLAY_TIMEZONE")

    min_donation_gap_days: int = Field(default=120, alias="MIN_DONATION_GAP_DAYS")
    recent_contact_hours: int = Field(default=24, alias="RECENT_CONTACT_HOURS")
    retention_days: int = Field(default=30, alias="RETENTION_DAYS")
    small_number_suppression_threshold: int = Field(
        default=3, alias="SMALL_NUMBER_SUPPRESSION_THRESHOLD"
    )

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token) and not self.demo_mode

    def validate_production(self) -> None:
        """Refuse to start in production with the default SECRET_KEY (F1.5)."""
        if self.is_production and self.secret_key == DEFAULT_SECRET_KEY:
            raise RuntimeError(
                "Refusing to start in production with the default SECRET_KEY. "
                "Set a real SECRET_KEY (e.g. python -c \"import secrets; print(secrets.token_hex(32))\")."
            )

    def new_secret_key(self) -> str:
        """Generate a fresh secret (used for tests and CLI helpers)."""
        return secrets.token_hex(32)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
