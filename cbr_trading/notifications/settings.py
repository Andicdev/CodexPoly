from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.runtime_secrets import read_runtime_secret


@dataclass(frozen=True)
class NotificationWorkerSettings:
    """Runtime configuration for durable Telegram event delivery."""

    database_url: str | None = field(default=None, repr=False)
    database_target: str = "server_ext"
    database_source: str = "DATABASE_URL_SERVER_EXT"
    database_error: str | None = None
    telegram_bot_token: str | None = field(default=None, repr=False)
    telegram_chat_id: str | None = field(default=None, repr=False)
    telegram_timeout: float = 10.0
    poll_interval: float = 0.5
    retry_delay: float = 10.0
    lease_seconds: float = 30.0
    heartbeat_interval: float = 60.0
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "NotificationWorkerSettings":
        env = environ if environ is not None else os.environ
        database = resolve_database_selection("primary", env)
        settings = cls(
            database_url=database.url,
            database_target=database.target,
            database_source=database.source,
            database_error=database.error,
            telegram_bot_token=(
                _clean(
                    read_runtime_secret(
                        "TG_BOT_TOKEN",
                        environ=env,
                    )
                )
                or None
            ),
            telegram_chat_id=(
                _clean(
                    read_runtime_secret(
                        "TELEGRAM_INGEST_CHAT_ID",
                        environ=env,
                    )
                )
                or None
            ),
            telegram_timeout=float(
                _clean(env.get("NEWS_TELEGRAM_TIMEOUT_SEC"))
                or "10"
            ),
            poll_interval=float(
                _clean(env.get("NEWS_NOTIFICATION_POLL_SEC"))
                or "0.5"
            ),
            retry_delay=float(
                _clean(env.get("NEWS_NOTIFICATION_RETRY_SEC"))
                or "10"
            ),
            lease_seconds=float(
                _clean(env.get("NEWS_NOTIFICATION_LEASE_SEC"))
                or "30"
            ),
            heartbeat_interval=float(
                _clean(env.get("NEWS_NOTIFICATION_HEARTBEAT_SEC"))
                or "60"
            ),
            log_level=(
                _clean(env.get("LOG_LEVEL"))
                or "INFO"
            ).upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.database_url:
            raise ValueError(
                self.database_error
                or "Primary database URL is not configured"
            )
        if not self.telegram_bot_token:
            raise ValueError("TG_BOT_TOKEN is required")
        if not self.telegram_chat_id:
            raise ValueError("TELEGRAM_INGEST_CHAT_ID is required")
        for name, value in (
            ("NEWS_TELEGRAM_TIMEOUT_SEC", self.telegram_timeout),
            ("NEWS_NOTIFICATION_POLL_SEC", self.poll_interval),
            ("NEWS_NOTIFICATION_LEASE_SEC", self.lease_seconds),
            (
                "NEWS_NOTIFICATION_HEARTBEAT_SEC",
                self.heartbeat_interval,
            ),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.retry_delay < 0:
            raise ValueError(
                "NEWS_NOTIFICATION_RETRY_SEC cannot be negative"
            )


def _clean(value: str | None) -> str:
    cleaned = str(value or "").strip().rstrip("\\").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned
