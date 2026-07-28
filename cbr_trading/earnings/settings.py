from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.runtime_secrets import read_runtime_secret


@dataclass(frozen=True)
class EarningsWorkerSettings:
    """Non-trading runtime configuration for the earnings shadow worker."""

    mode: str = "shadow"
    database_url: str | None = field(default=None, repr=False)
    database_target: str = "server_ext"
    database_source: str = "DATABASE_URL_SERVER_EXT"
    database_error: str | None = None
    sec_api_key: str | None = field(default=None, repr=False)
    http_user_agent: str = field(default="", repr=False)
    fetch_timeout: float = 15.0
    max_document_bytes: int = 8 * 1024 * 1024
    max_fetch_attempts: int = 3
    fetch_retry_delay: float = 0.5
    reconnect_initial_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    no_rules_retry_delay: float = 30.0
    heartbeat_interval: float = 60.0
    public_sources_enabled: bool = False
    public_poll_interval: float = 1.0
    sec_current_polling_enabled: bool = False
    sec_current_poll_interval: float = 0.25
    sec_current_max_requests_per_second: float = 5.0
    mstr_btc_shadow_enabled: bool = False
    mstr_btc_ledger_enabled: bool = False
    mstr_btc_ledger_url: str = "https://www.strategy.com/ledger"
    mstr_btc_ledger_poll_interval: float = 2.0
    mstr_btc_ledger_timeout: float = 10.0
    notification_delivery_delay: float = 2.0
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "EarningsWorkerSettings":
        env = environ if environ is not None else os.environ
        database = resolve_database_selection("primary", env)
        settings = cls(
            mode=(
                _clean(env.get("EARNINGS_WORKER_MODE"))
                or "shadow"
            ).lower(),
            database_url=database.url,
            database_target=database.target,
            database_source=database.source,
            database_error=database.error,
            sec_api_key=(
                _clean(
                    read_runtime_secret(
                        "SEC_API_KEY",
                        environ=env,
                    )
                    or read_runtime_secret(
                        "SEC_API_IO_KEY",
                        environ=env,
                    )
                    or read_runtime_secret(
                        "SEC_API_STREAM_KEY",
                        environ=env,
                    )
                )
                or None
            ),
            http_user_agent=(
                _clean(env.get("EARNINGS_HTTP_USER_AGENT"))
            ),
            fetch_timeout=float(
                _clean(env.get("EARNINGS_FETCH_TIMEOUT_SEC"))
                or "15"
            ),
            max_document_bytes=int(
                _clean(env.get("EARNINGS_MAX_DOCUMENT_BYTES"))
                or str(8 * 1024 * 1024)
            ),
            max_fetch_attempts=int(
                _clean(env.get("EARNINGS_FETCH_ATTEMPTS"))
                or "3"
            ),
            fetch_retry_delay=float(
                _clean(env.get("EARNINGS_FETCH_RETRY_SEC"))
                or "0.5"
            ),
            reconnect_initial_delay=float(
                _clean(env.get("EARNINGS_RECONNECT_INITIAL_SEC"))
                or "1"
            ),
            reconnect_max_delay=float(
                _clean(env.get("EARNINGS_RECONNECT_MAX_SEC"))
                or "30"
            ),
            no_rules_retry_delay=float(
                _clean(env.get("EARNINGS_NO_RULES_RETRY_SEC"))
                or "30"
            ),
            heartbeat_interval=float(
                _clean(env.get("EARNINGS_HEARTBEAT_SEC"))
                or "60"
            ),
            public_sources_enabled=_bool_value(
                env.get("EARNINGS_PUBLIC_SOURCES_ENABLED"),
                default=False,
                name="EARNINGS_PUBLIC_SOURCES_ENABLED",
            ),
            public_poll_interval=float(
                _clean(env.get("EARNINGS_PUBLIC_POLL_SEC"))
                or "1"
            ),
            sec_current_polling_enabled=_bool_value(
                env.get("EARNINGS_SEC_CURRENT_POLL_ENABLED"),
                default=False,
                name="EARNINGS_SEC_CURRENT_POLL_ENABLED",
            ),
            sec_current_poll_interval=float(
                _clean(env.get("EARNINGS_SEC_CURRENT_POLL_SEC"))
                or "0.25"
            ),
            sec_current_max_requests_per_second=float(
                _clean(
                    env.get(
                        "EARNINGS_SEC_CURRENT_MAX_REQUESTS_PER_SEC"
                    )
                )
                or "5"
            ),
            mstr_btc_shadow_enabled=_bool_value(
                env.get("MSTR_BTC_SHADOW_ENABLED"),
                default=False,
                name="MSTR_BTC_SHADOW_ENABLED",
            ),
            mstr_btc_ledger_enabled=_bool_value(
                env.get("MSTR_BTC_LEDGER_ENABLED"),
                default=False,
                name="MSTR_BTC_LEDGER_ENABLED",
            ),
            mstr_btc_ledger_url=(
                _clean(env.get("MSTR_BTC_LEDGER_URL"))
                or "https://www.strategy.com/ledger"
            ),
            mstr_btc_ledger_poll_interval=float(
                _clean(env.get("MSTR_BTC_LEDGER_POLL_SEC"))
                or "2"
            ),
            mstr_btc_ledger_timeout=float(
                _clean(env.get("MSTR_BTC_LEDGER_TIMEOUT_SEC"))
                or "10"
            ),
            notification_delivery_delay=float(
                _clean(
                    env.get("NEWS_NOTIFICATION_DELIVERY_DELAY_SEC")
                )
                or "2"
            ),
            log_level=(
                _clean(env.get("LOG_LEVEL"))
                or "INFO"
            ).upper(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.mode != "shadow":
            raise ValueError(
                "EARNINGS_WORKER_MODE must remain 'shadow'"
            )
        if not self.database_url:
            raise ValueError(
                self.database_error
                or "Primary database URL is not configured"
            )
        if not self.sec_api_key:
            raise ValueError(
                "SEC_API_KEY, SEC_API_IO_KEY, or "
                "SEC_API_STREAM_KEY is required"
            )
        if not self.http_user_agent.strip():
            raise ValueError("EARNINGS_HTTP_USER_AGENT is required")
        if self.fetch_timeout <= 0:
            raise ValueError(
                "EARNINGS_FETCH_TIMEOUT_SEC must be positive"
            )
        if not 1024 <= self.max_document_bytes <= 32 * 1024 * 1024:
            raise ValueError(
                "EARNINGS_MAX_DOCUMENT_BYTES must be between "
                "1024 and 33554432"
            )
        if not 1 <= self.max_fetch_attempts <= 10:
            raise ValueError(
                "EARNINGS_FETCH_ATTEMPTS must be between 1 and 10"
            )
        if self.fetch_retry_delay < 0:
            raise ValueError(
                "EARNINGS_FETCH_RETRY_SEC cannot be negative"
            )
        if self.reconnect_initial_delay <= 0:
            raise ValueError(
                "EARNINGS_RECONNECT_INITIAL_SEC must be positive"
            )
        if self.reconnect_max_delay < self.reconnect_initial_delay:
            raise ValueError(
                "EARNINGS_RECONNECT_MAX_SEC cannot be smaller than "
                "EARNINGS_RECONNECT_INITIAL_SEC"
            )
        if self.no_rules_retry_delay <= 0:
            raise ValueError(
                "EARNINGS_NO_RULES_RETRY_SEC must be positive"
            )
        if self.heartbeat_interval <= 0:
            raise ValueError(
                "EARNINGS_HEARTBEAT_SEC must be positive"
            )
        if not 0.25 <= self.public_poll_interval <= 60:
            raise ValueError(
                "EARNINGS_PUBLIC_POLL_SEC must be between 0.25 and 60"
            )
        if not 0.1 <= self.sec_current_poll_interval <= 60:
            raise ValueError(
                "EARNINGS_SEC_CURRENT_POLL_SEC must be between "
                "0.1 and 60"
            )
        if not (
            0.5
            <= self.sec_current_max_requests_per_second
            <= 5
        ):
            raise ValueError(
                "EARNINGS_SEC_CURRENT_MAX_REQUESTS_PER_SEC must be "
                "between 0.5 and 5"
            )
        if (
            self.mstr_btc_ledger_enabled
            and not self.mstr_btc_shadow_enabled
        ):
            raise ValueError(
                "MSTR_BTC_LEDGER_ENABLED requires "
                "MSTR_BTC_SHADOW_ENABLED"
            )
        if not self.mstr_btc_ledger_url.lower().startswith("https://"):
            raise ValueError("MSTR_BTC_LEDGER_URL must use HTTPS")
        if not 0.5 <= self.mstr_btc_ledger_poll_interval <= 60:
            raise ValueError(
                "MSTR_BTC_LEDGER_POLL_SEC must be between 0.5 and 60"
            )
        if not 1 <= self.mstr_btc_ledger_timeout <= 60:
            raise ValueError(
                "MSTR_BTC_LEDGER_TIMEOUT_SEC must be between 1 and 60"
            )
        if not 0 <= self.notification_delivery_delay <= 60:
            raise ValueError(
                "NEWS_NOTIFICATION_DELIVERY_DELAY_SEC must be "
                "between 0 and 60"
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


def _bool_value(
    value: str | None,
    *,
    default: bool,
    name: str = "boolean setting",
) -> bool:
    normalized = _clean(value).casefold()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")
