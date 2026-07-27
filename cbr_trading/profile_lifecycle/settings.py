from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Mapping

from cbr_trading.db_config import resolve_database_selection


@dataclass(frozen=True)
class ProfileLifecycleSettings:
    database_url: str | None = field(default=None, repr=False)
    database_error: str | None = None
    poll_interval: float = 2.0
    heartbeat_interval: float = 60.0
    activation_grace_seconds: float = 60.0
    batch_size: int = 100
    auto_live_enabled: bool = False
    max_total_notional: Decimal | None = None
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ProfileLifecycleSettings":
        env = environ if environ is not None else os.environ
        database = resolve_database_selection("primary", env)
        settings = cls(
            database_url=database.url,
            database_error=database.error,
            poll_interval=float(
                _clean(env.get("PROFILE_SCHEDULER_POLL_SEC")) or "2"
            ),
            heartbeat_interval=float(
                _clean(env.get("PROFILE_SCHEDULER_HEARTBEAT_SEC"))
                or "60"
            ),
            activation_grace_seconds=float(
                _clean(
                    env.get(
                        "PROFILE_SCHEDULER_ACTIVATION_GRACE_SEC"
                    )
                )
                or "60"
            ),
            batch_size=int(
                _clean(env.get("PROFILE_SCHEDULER_BATCH_SIZE"))
                or "100"
            ),
            auto_live_enabled=_bool(
                env.get("PROFILE_SCHEDULER_AUTO_LIVE_ENABLED"),
                default=False,
            ),
            max_total_notional=_optional_decimal(
                env.get("PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL")
            ),
            log_level=(
                _clean(env.get("LOG_LEVEL")) or "INFO"
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
        for name in (
            "poll_interval",
            "heartbeat_interval",
            "activation_grace_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.max_total_notional is not None:
            if (
                not self.max_total_notional.is_finite()
                or self.max_total_notional <= 0
            ):
                raise ValueError(
                    "PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL "
                    "must be finite and positive"
                )
        if self.auto_live_enabled and self.max_total_notional is None:
            raise ValueError(
                "PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL is required "
                "when automatic live activation is enabled"
            )


@dataclass(frozen=True)
class ProfileReadinessSettings:
    database_url: str | None = field(default=None, repr=False)
    database_error: str | None = None
    poll_interval: float = 1.0
    heartbeat_interval: float = 60.0
    lease_seconds: float = 60.0
    readiness_ttl_seconds: float = 1_800.0
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "ProfileReadinessSettings":
        env = environ if environ is not None else os.environ
        database = resolve_database_selection("primary", env)
        settings = cls(
            database_url=database.url,
            database_error=database.error,
            poll_interval=float(
                _clean(env.get("PROFILE_READINESS_POLL_SEC")) or "1"
            ),
            heartbeat_interval=float(
                _clean(env.get("PROFILE_READINESS_HEARTBEAT_SEC"))
                or "60"
            ),
            lease_seconds=float(
                _clean(env.get("PROFILE_READINESS_LEASE_SEC")) or "60"
            ),
            readiness_ttl_seconds=float(
                _clean(env.get("PROFILE_READINESS_TTL_SEC")) or "1800"
            ),
            log_level=(
                _clean(env.get("LOG_LEVEL")) or "INFO"
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
        for name in (
            "poll_interval",
            "heartbeat_interval",
            "lease_seconds",
            "readiness_ttl_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


def _bool(
    value: str | None,
    *,
    default: bool,
) -> bool:
    normalized = _clean(value).lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _optional_decimal(value: str | None) -> Decimal | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(
            "Invalid PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL"
        ) from exc


def _clean(value: str | None) -> str:
    cleaned = str(value or "").strip().rstrip("\\").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned
