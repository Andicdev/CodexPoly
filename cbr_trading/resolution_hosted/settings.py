from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from cbr_trading.db_config import resolve_database_selection


class HostedResolutionMode(str, Enum):
    SHADOW = "shadow"
    PREFLIGHT = "preflight"
    LIVE = "live"


@dataclass(frozen=True)
class HostedResolutionSettings:
    """Fail-closed configuration for the separate resolution service."""

    mode: HostedResolutionMode = HostedResolutionMode.SHADOW
    database_url: str | None = field(default=None, repr=False)
    database_target: str = "server_ext"
    database_source: str = "DATABASE_URL_SERVER_EXT"
    database_error: str | None = None
    poll_interval: float = 0.25
    heartbeat_interval: float = 30.0
    no_profiles_retry_delay: float = 30.0
    supervision_enabled: bool = False
    supervision_watch_refresh_interval: float = 5.0
    supervision_reconciliation_interval: float = 5.0
    supervision_stale_after: float = 30.0
    supervision_batch_size: int = 100
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> HostedResolutionSettings:
        env = environ if environ is not None else os.environ
        database = resolve_database_selection("primary", env)
        raw_mode = (
            _clean(env.get("RESOLUTION_ORCHESTRATOR_MODE"))
            or HostedResolutionMode.SHADOW.value
        ).lower()
        try:
            mode = HostedResolutionMode(raw_mode)
        except ValueError:
            raise ValueError(
                "RESOLUTION_ORCHESTRATOR_MODE must be "
                "'shadow', 'preflight', or 'live'"
            ) from None
        settings = cls(
            mode=mode,
            database_url=database.url,
            database_target=database.target,
            database_source=database.source,
            database_error=database.error,
            poll_interval=float(
                _clean(
                    env.get("RESOLUTION_ORCHESTRATOR_POLL_SEC")
                )
                or "0.25"
            ),
            heartbeat_interval=float(
                _clean(
                    env.get("RESOLUTION_ORCHESTRATOR_HEARTBEAT_SEC")
                )
                or "30"
            ),
            no_profiles_retry_delay=float(
                _clean(
                    env.get(
                        "RESOLUTION_ORCHESTRATOR_NO_PROFILES_SEC"
                    )
                )
                or "30"
            ),
            supervision_enabled=_bool(
                env.get("RESOLUTION_SUPERVISION_ENABLED"),
                default=False,
            ),
            supervision_watch_refresh_interval=float(
                _clean(
                    env.get(
                        "RESOLUTION_SUPERVISION_WATCH_REFRESH_SEC"
                    )
                )
                or "5"
            ),
            supervision_reconciliation_interval=float(
                _clean(
                    env.get(
                        "RESOLUTION_SUPERVISION_RECONCILE_SEC"
                    )
                )
                or "5"
            ),
            supervision_stale_after=float(
                _clean(
                    env.get("RESOLUTION_SUPERVISION_STALE_SEC")
                )
                or "30"
            ),
            supervision_batch_size=int(
                _clean(
                    env.get("RESOLUTION_SUPERVISION_BATCH_SIZE")
                )
                or "100"
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
            "no_profiles_retry_delay",
            "supervision_watch_refresh_interval",
            "supervision_reconciliation_interval",
            "supervision_stale_after",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.supervision_batch_size < 1:
            raise ValueError(
                "supervision_batch_size must be positive"
            )


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


def _clean(value: str | None) -> str:
    cleaned = str(value or "").strip().rstrip("\\").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned
