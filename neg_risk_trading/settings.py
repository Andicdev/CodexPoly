from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Mapping

from cbr_trading.db_config import resolve_database_selection
from neg_risk_trading.domain import RouteDirection
from neg_risk_trading.polymarket import (
    DEFAULT_FED_SEPTEMBER_SLUG,
    extract_event_slug,
)


@dataclass(frozen=True)
class NegRiskRecorderSettings:
    mode: str = "shadow"
    event_slug: str = DEFAULT_FED_SEPTEMBER_SLUG
    quantities: tuple[Decimal, ...] = (Decimal("200"),)
    route_directions: tuple[RouteDirection, ...] = (
        RouteDirection.MAKER_BUY,
        RouteDirection.MAKER_SELL,
    )
    database_url: str | None = field(default=None, repr=False)
    database_target: str = "server_ext"
    database_source: str = "DATABASE_URL_SERVER_EXT"
    database_error: str | None = None
    queue_capacity: int = 5_000
    write_batch_size: int = 100
    flush_interval_seconds: float = 0.25
    route_sample_interval_ms: int = 250
    reconnect_initial_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    heartbeat_seconds: float = 10.0
    bootstrap_timeout_seconds: float = 15.0
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> NegRiskRecorderSettings:
        env = environ if environ is not None else os.environ
        database = resolve_database_selection("primary", env)
        settings = cls(
            mode=(
                _clean(env.get("NEG_RISK_RECORDER_MODE"))
                or "shadow"
            ).lower(),
            event_slug=extract_event_slug(
                _clean(env.get("NEG_RISK_EVENT_SLUG"))
                or DEFAULT_FED_SEPTEMBER_SLUG
            ),
            quantities=_quantities(
                _clean(env.get("NEG_RISK_QUANTITIES"))
                or "200"
            ),
            route_directions=_route_directions(
                _clean(
                    env.get("NEG_RISK_ROUTE_DIRECTIONS")
                )
                or "MAKER_BUY,MAKER_SELL"
            ),
            database_url=database.url,
            database_target=database.target,
            database_source=database.source,
            database_error=database.error,
            queue_capacity=int(
                _clean(env.get("NEG_RISK_QUEUE_CAPACITY"))
                or "5000"
            ),
            write_batch_size=int(
                _clean(env.get("NEG_RISK_DB_BATCH_SIZE"))
                or "100"
            ),
            flush_interval_seconds=float(
                _clean(env.get("NEG_RISK_DB_FLUSH_SEC"))
                or "0.25"
            ),
            route_sample_interval_ms=int(
                _clean(
                    env.get("NEG_RISK_ROUTE_SAMPLE_INTERVAL_MS")
                )
                or "250"
            ),
            reconnect_initial_seconds=float(
                _clean(
                    env.get("NEG_RISK_RECONNECT_INITIAL_SEC")
                )
                or "1"
            ),
            reconnect_max_seconds=float(
                _clean(
                    env.get("NEG_RISK_RECONNECT_MAX_SEC")
                )
                or "30"
            ),
            heartbeat_seconds=float(
                _clean(env.get("NEG_RISK_HEARTBEAT_SEC"))
                or "10"
            ),
            bootstrap_timeout_seconds=float(
                _clean(
                    env.get("NEG_RISK_BOOTSTRAP_TIMEOUT_SEC")
                )
                or "15"
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
                "NEG_RISK_RECORDER_MODE must remain 'shadow'"
            )
        if not self.database_url:
            raise ValueError(
                self.database_error
                or "Neg-risk database URL is not configured"
            )
        if not self.quantities:
            raise ValueError("NEG_RISK_QUANTITIES is required")
        if (
            not self.route_directions
            or len(self.route_directions)
            != len(set(self.route_directions))
        ):
            raise ValueError(
                "NEG_RISK_ROUTE_DIRECTIONS must be unique"
            )
        if not 100 <= self.queue_capacity <= 100_000:
            raise ValueError(
                "NEG_RISK_QUEUE_CAPACITY must be between "
                "100 and 100000"
            )
        if not 1 <= self.write_batch_size <= 1_000:
            raise ValueError(
                "NEG_RISK_DB_BATCH_SIZE must be between 1 and 1000"
            )
        if self.write_batch_size > self.queue_capacity:
            raise ValueError(
                "NEG_RISK_DB_BATCH_SIZE cannot exceed queue capacity"
            )
        if not 0.01 <= self.flush_interval_seconds <= 10:
            raise ValueError(
                "NEG_RISK_DB_FLUSH_SEC must be between 0.01 and 10"
            )
        if not 0 <= self.route_sample_interval_ms <= 60_000:
            raise ValueError(
                "NEG_RISK_ROUTE_SAMPLE_INTERVAL_MS must be "
                "between 0 and 60000"
            )
        if not 0.1 <= self.reconnect_initial_seconds <= 60:
            raise ValueError(
                "NEG_RISK_RECONNECT_INITIAL_SEC must be "
                "between 0.1 and 60"
            )
        if (
            self.reconnect_max_seconds
            < self.reconnect_initial_seconds
            or self.reconnect_max_seconds > 300
        ):
            raise ValueError(
                "NEG_RISK_RECONNECT_MAX_SEC must be between "
                "the initial delay and 300"
            )
        if not 1 <= self.heartbeat_seconds <= 60:
            raise ValueError(
                "NEG_RISK_HEARTBEAT_SEC must be between 1 and 60"
            )
        if not 1 <= self.bootstrap_timeout_seconds <= 120:
            raise ValueError(
                "NEG_RISK_BOOTSTRAP_TIMEOUT_SEC must be "
                "between 1 and 120"
            )


@dataclass(frozen=True)
class NegRiskCatalogSettings:
    mode: str = "shadow"
    database_url: str | None = field(default=None, repr=False)
    database_target: str = "server_ext"
    database_source: str = "DATABASE_URL_SERVER_EXT"
    database_error: str | None = None
    poll_interval_seconds: float = 900.0
    retry_interval_seconds: float = 30.0
    page_size: int = 100
    maximum_pages: int = 2_000
    maximum_markets: int = 200_000
    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 15.0
    maximum_response_bytes: int = 8 * 1024 * 1024
    log_level: str = "INFO"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> NegRiskCatalogSettings:
        env = environ if environ is not None else os.environ
        database = resolve_database_selection("primary", env)
        settings = cls(
            mode=(
                _clean(env.get("NEG_RISK_CATALOG_MODE"))
                or "shadow"
            ).lower(),
            database_url=database.url,
            database_target=database.target,
            database_source=database.source,
            database_error=database.error,
            poll_interval_seconds=float(
                _clean(
                    env.get("NEG_RISK_CATALOG_POLL_SEC")
                )
                or "900"
            ),
            retry_interval_seconds=float(
                _clean(
                    env.get("NEG_RISK_CATALOG_RETRY_SEC")
                )
                or "30"
            ),
            page_size=int(
                _clean(
                    env.get("NEG_RISK_CATALOG_PAGE_SIZE")
                )
                or "100"
            ),
            maximum_pages=int(
                _clean(
                    env.get("NEG_RISK_CATALOG_MAX_PAGES")
                )
                or "2000"
            ),
            maximum_markets=int(
                _clean(
                    env.get("NEG_RISK_CATALOG_MAX_MARKETS")
                )
                or "200000"
            ),
            connect_timeout_seconds=float(
                _clean(
                    env.get(
                        "NEG_RISK_CATALOG_CONNECT_TIMEOUT_SEC"
                    )
                )
                or "2"
            ),
            read_timeout_seconds=float(
                _clean(
                    env.get(
                        "NEG_RISK_CATALOG_READ_TIMEOUT_SEC"
                    )
                )
                or "15"
            ),
            maximum_response_bytes=int(
                _clean(
                    env.get(
                        "NEG_RISK_CATALOG_MAX_RESPONSE_BYTES"
                    )
                )
                or str(8 * 1024 * 1024)
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
                "NEG_RISK_CATALOG_MODE must remain 'shadow'"
            )
        if not self.database_url:
            raise ValueError(
                self.database_error
                or "Neg-risk database URL is not configured"
            )
        if not 60 <= self.poll_interval_seconds <= 86_400:
            raise ValueError(
                "NEG_RISK_CATALOG_POLL_SEC must be between "
                "60 and 86400"
            )
        if not 1 <= self.retry_interval_seconds <= 3_600:
            raise ValueError(
                "NEG_RISK_CATALOG_RETRY_SEC must be between "
                "1 and 3600"
            )
        if not 1 <= self.page_size <= 500:
            raise ValueError(
                "NEG_RISK_CATALOG_PAGE_SIZE must be between "
                "1 and 500"
            )
        if not 1 <= self.maximum_pages <= 10_000:
            raise ValueError(
                "NEG_RISK_CATALOG_MAX_PAGES must be between "
                "1 and 10000"
            )
        if not 100 <= self.maximum_markets <= 1_000_000:
            raise ValueError(
                "NEG_RISK_CATALOG_MAX_MARKETS must be between "
                "100 and 1000000"
            )
        if (
            self.connect_timeout_seconds <= 0
            or self.read_timeout_seconds <= 0
            or self.connect_timeout_seconds > 60
            or self.read_timeout_seconds > 120
        ):
            raise ValueError(
                "Neg-risk catalog timeouts are invalid"
            )
        if not (
            1024
            <= self.maximum_response_bytes
            <= 64 * 1024 * 1024
        ):
            raise ValueError(
                "NEG_RISK_CATALOG_MAX_RESPONSE_BYTES is invalid"
            )


def _quantities(value: str) -> tuple[Decimal, ...]:
    try:
        quantities = tuple(
            Decimal(part.strip())
            for part in str(value or "").split(",")
            if part.strip()
        )
    except InvalidOperation as exc:
        raise ValueError(
            "NEG_RISK_QUANTITIES must contain decimals"
        ) from exc
    if (
        not quantities
        or any(
            not quantity.is_finite() or quantity <= 0
            for quantity in quantities
        )
        or len(set(quantities)) != len(quantities)
    ):
        raise ValueError(
            "NEG_RISK_QUANTITIES must contain unique "
            "positive finite values"
        )
    return quantities


def _route_directions(
    value: str,
) -> tuple[RouteDirection, ...]:
    try:
        directions = tuple(
            RouteDirection(part.strip().upper())
            for part in value.split(",")
            if part.strip()
        )
    except ValueError as exc:
        raise ValueError(
            "NEG_RISK_ROUTE_DIRECTIONS is invalid"
        ) from exc
    if (
        not directions
        or len(directions) != len(set(directions))
    ):
        raise ValueError(
            "NEG_RISK_ROUTE_DIRECTIONS must be unique"
        )
    return directions


def _clean(value: str | None) -> str:
    return str(value or "").strip()
