from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping

from cbr_trading.client import CbrClientConfig
from cbr_trading.release import DEFAULT_RELEASE_TIME_SUFFIX


def _clean(value: str | None) -> str:
    cleaned = str(value or "").strip().rstrip("\\").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _bool(value: str | None, *, default: bool) -> bool:
    cleaned = _clean(value).lower()
    if not cleaned:
        return default
    if cleaned in {"1", "true", "yes", "y", "on"}:
        return True
    if cleaned in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _optional_float(value: str | None) -> float | None:
    cleaned = _clean(value)
    return float(cleaned) if cleaned else None


@dataclass(frozen=True)
class CbrSettings:
    mode: str = "hot"
    release_date: str | None = None
    release_time_suffix: str = DEFAULT_RELEASE_TIME_SUFFIX
    poll_interval: float = 0.25
    heartbeat_interval: float = 10.0
    connect_timeout: float = 0.5
    read_timeout: float = 0.5
    prefix_max_bytes: int = 32768
    prefix_chunk_size: int = 2048
    cache_bust: bool = True
    log_level: str = "INFO"
    dry_run: bool = True
    previous_rate: float | None = None
    telegram_enabled: bool = False
    telegram_bot_token: str | None = field(default=None, repr=False)
    telegram_chat_id: str | None = None
    telegram_timeout: float = 10.0

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "CbrSettings":
        env = environ if environ is not None else os.environ
        mode = _clean(env.get("BOR_MODE") or "hot").lower()
        if mode not in {"hot", "live_once"}:
            raise ValueError(
                "BOR_MODE must be 'hot' or 'live_once' for cbr_trading"
            )

        settings = cls(
            mode=mode,
            release_date=_clean(env.get("BOR_RELEASE_DATE")) or None,
            release_time_suffix=(
                _clean(env.get("BOR_RELEASE_TIME_SUFFIX"))
                or DEFAULT_RELEASE_TIME_SUFFIX
            ),
            poll_interval=float(
                _clean(env.get("BOR_POLL_SLEEP_SEC")) or "0.25"
            ),
            heartbeat_interval=float(
                _clean(env.get("BOR_HEARTBEAT_SEC")) or "10"
            ),
            connect_timeout=float(
                _clean(env.get("BOR_CONNECT_TIMEOUT_SEC")) or "0.5"
            ),
            read_timeout=float(
                _clean(env.get("BOR_READ_TIMEOUT_SEC")) or "0.5"
            ),
            prefix_max_bytes=int(
                _clean(env.get("BOR_PREFIX_MAX_BYTES")) or "32768"
            ),
            prefix_chunk_size=int(
                _clean(env.get("BOR_PREFIX_CHUNK_SIZE")) or "2048"
            ),
            cache_bust=not _bool(
                env.get("BOR_DISABLE_CACHE_BUSTER"),
                default=False,
            ),
            log_level=(_clean(env.get("LOG_LEVEL")) or "INFO").upper(),
            dry_run=_bool(env.get("CBR_DRY_RUN"), default=True),
            previous_rate=_optional_float(env.get("BOR_PREV_RATE")),
            telegram_enabled=_bool(
                env.get("CBR_TELEGRAM_ENABLED"),
                default=False,
            ),
            telegram_bot_token=(
                _clean(env.get("TG_BOT_TOKEN")) or None
            ),
            telegram_chat_id=(
                _clean(env.get("TELEGRAM_INGEST_CHAT_ID")) or None
            ),
            telegram_timeout=float(
                _clean(env.get("TG_HTTP_TIMEOUT")) or "10"
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.poll_interval <= 0:
            raise ValueError("BOR_POLL_SLEEP_SEC must be greater than zero")
        if self.heartbeat_interval < 0:
            raise ValueError("BOR_HEARTBEAT_SEC cannot be negative")
        if self.connect_timeout <= 0:
            raise ValueError("BOR_CONNECT_TIMEOUT_SEC must be positive")
        if self.read_timeout <= 0:
            raise ValueError("BOR_READ_TIMEOUT_SEC must be positive")
        if self.prefix_max_bytes < 1024:
            raise ValueError("BOR_PREFIX_MAX_BYTES must be at least 1024")
        if self.prefix_chunk_size < 256:
            raise ValueError("BOR_PREFIX_CHUNK_SIZE must be at least 256")
        if self.prefix_chunk_size > self.prefix_max_bytes:
            raise ValueError(
                "BOR_PREFIX_CHUNK_SIZE cannot exceed BOR_PREFIX_MAX_BYTES"
            )
        if self.telegram_timeout <= 0:
            raise ValueError("TG_HTTP_TIMEOUT must be positive")
        if self.telegram_enabled and not self.telegram_bot_token:
            raise ValueError(
                "TG_BOT_TOKEN is required when CBR_TELEGRAM_ENABLED=1"
            )
        if self.telegram_enabled and not self.telegram_chat_id:
            raise ValueError(
                "TELEGRAM_INGEST_CHAT_ID is required when "
                "CBR_TELEGRAM_ENABLED=1"
            )

    def client_config(self) -> CbrClientConfig:
        return CbrClientConfig(
            release_time_suffix=self.release_time_suffix,
            connect_timeout=self.connect_timeout,
            read_timeout=self.read_timeout,
            prefix_max_bytes=self.prefix_max_bytes,
            prefix_chunk_size=self.prefix_chunk_size,
            cache_bust=self.cache_bust,
        )
