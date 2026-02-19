from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when required environment configuration is missing."""


def _mask_secret(value: str) -> str:
    return "[redacted]" if value else ""


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openai_api_key: str
    database_url: str
    log_level: str = "INFO"
    default_timezone: str = "UTC+3"

    def safe_log_values(self) -> dict[str, str]:
        return {
            "telegram_bot_token": _mask_secret(self.telegram_bot_token),
            "openai_api_key": _mask_secret(self.openai_api_key),
            "database_url": _mask_secret(self.database_url),
            "log_level": self.log_level,
            "default_timezone": self.default_timezone,
        }


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    load_dotenv(override=False)
    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        openai_api_key=_require("OPENAI_API_KEY"),
        database_url=_require("DATABASE_URL"),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "UTC+3").strip() or "UTC+3",
    )
