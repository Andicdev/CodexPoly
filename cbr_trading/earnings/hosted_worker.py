from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from cbr_trading.earnings.contracts import EarningsMarketRule
from cbr_trading.earnings.document_fetcher import SecDocumentFetcher
from cbr_trading.earnings.parsers import earnings_parser_registry
from cbr_trading.earnings.processor import (
    EarningsShadowProcessor,
    ShadowProcessingStatus,
)
from cbr_trading.earnings.repository import SqlAlchemyEarningsStore
from cbr_trading.earnings.sec_stream import (
    SecEarningsWatch,
    SecStreamEarningsTransport,
    SecStreamTransportError,
)
from cbr_trading.earnings.settings import EarningsWorkerSettings
from cbr_trading.secret_guard import redact_exception


class StreamTransport(Protocol):
    def stream_once(self): ...


TransportBuilder = Callable[
    [Sequence[SecEarningsWatch]],
    StreamTransport,
]


class WorkerCycleStatus(str, Enum):
    STREAM_CLOSED = "stream_closed"
    NO_RULES = "no_rules"


@dataclass(frozen=True)
class WorkerCycleResult:
    status: WorkerCycleStatus
    watch_count: int
    processed_count: int = 0
    signal_count: int = 0


class EarningsHostedShadowWorker:
    """Reconnect SEC transport and persist only shadow source outcomes."""

    def __init__(
        self,
        *,
        settings: EarningsWorkerSettings,
        store: SqlAlchemyEarningsStore,
        transport_builder: TransportBuilder | None = None,
        parsers: Mapping[str, object] | None = None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._store = store
        self._transport_builder = (
            transport_builder
            or self._default_transport_builder
        )
        self._parsers = dict(
            parsers
            or earnings_parser_registry()
        )
        self._logger = logger or logging.getLogger(
            "cbr_trading.earnings"
        )
        self._connected = False
        self._watch_count = 0
        self._processed_count = 0
        self._signal_count = 0
        self._error_count = 0

    async def run_forever(self) -> None:
        await asyncio.to_thread(self._store.ensure_ready)
        self._logger.info(
            "Earnings shadow worker schema ready mode=shadow"
        )
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        delay = self._settings.reconnect_initial_delay
        try:
            while True:
                try:
                    cycle = await self.run_connection_cycle()
                    if cycle.status is WorkerCycleStatus.NO_RULES:
                        await asyncio.sleep(
                            self._settings.no_rules_retry_delay
                        )
                        delay = (
                            self._settings.reconnect_initial_delay
                        )
                        continue
                    self._logger.warning(
                        "SEC earnings stream closed; reconnecting "
                        "watches=%s processed=%s signals=%s",
                        cycle.watch_count,
                        cycle.processed_count,
                        cycle.signal_count,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._connected = False
                    self._error_count += 1
                    error_code = (
                        exc.diagnostic_code
                        if isinstance(exc, SecStreamTransportError)
                        else type(exc).__name__
                    )
                    self._logger.warning(
                        "SEC earnings stream cycle failed; "
                        "reconnecting error_code=%s",
                        error_code,
                    )
                await asyncio.sleep(delay)
                delay = min(
                    delay * 2,
                    self._settings.reconnect_max_delay,
                )
        finally:
            self._connected = False
            heartbeat.cancel()
            await asyncio.gather(
                heartbeat,
                return_exceptions=True,
            )

    async def run_connection_cycle(self) -> WorkerCycleResult:
        rules = tuple(
            await asyncio.to_thread(
                self._store.load_active_rules
            )
        )
        watches = _watches_from_rules(rules)
        self._watch_count = len(watches)
        if not watches:
            self._logger.warning(
                "Earnings shadow worker has no active SEC rules"
            )
            return WorkerCycleResult(
                status=WorkerCycleStatus.NO_RULES,
                watch_count=0,
            )

        fetcher = SecDocumentFetcher(
            api_key=self._settings.sec_api_key or "",
            user_agent=self._settings.http_user_agent,
            timeout=self._settings.fetch_timeout,
            max_bytes=self._settings.max_document_bytes,
            logger=self._logger,
        )
        processor = EarningsShadowProcessor(
            store=self._store,
            rules=rules,
            parsers=self._parsers,
            document_fetcher=fetcher,
            max_fetch_attempts=self._settings.max_fetch_attempts,
            fetch_retry_delay=self._settings.fetch_retry_delay,
        )
        transport = self._transport_builder(watches)
        processed = 0
        signals = 0
        self._connected = True
        self._logger.info(
            "SEC earnings shadow stream connecting watches=%s",
            len(watches),
        )
        try:
            async for candidate in transport.stream_once():
                result = await asyncio.to_thread(
                    processor.process,
                    candidate,
                )
                processed += 1
                self._processed_count += 1
                if result.status is ShadowProcessingStatus.SIGNAL:
                    signals += 1
                    self._signal_count += 1
                if result.status is ShadowProcessingStatus.ERROR:
                    self._error_count += 1
                self._logger.info(
                    "Earnings shadow document processed "
                    "scope=%s ticker=%s status=%s reason=%s "
                    "event_id=%s fact_id=%s value=%s",
                    result.scope_id,
                    candidate.ticker,
                    result.status.value,
                    result.reason,
                    result.event_id,
                    result.fact_id,
                    (
                        result.signal.value
                        if result.signal is not None
                        else None
                    ),
                )
        finally:
            self._connected = False
        return WorkerCycleResult(
            status=WorkerCycleStatus.STREAM_CLOSED,
            watch_count=len(watches),
            processed_count=processed,
            signal_count=signals,
        )

    def _default_transport_builder(
        self,
        watches: Sequence[SecEarningsWatch],
    ) -> SecStreamEarningsTransport:
        api_key = self._settings.sec_api_key
        if not api_key:
            raise RuntimeError("SEC API credential is unavailable")
        return SecStreamEarningsTransport(
            api_key=api_key,
            watches=watches,
        )

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._settings.heartbeat_interval
            )
            self._logger.info(
                "Earnings shadow heartbeat connected=%s watches=%s "
                "processed=%s signals=%s errors=%s",
                self._connected,
                self._watch_count,
                self._processed_count,
                self._signal_count,
                self._error_count,
            )


def main(
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    _load_dotenv_if_available()
    env = environ if environ is not None else os.environ
    try:
        settings = EarningsWorkerSettings.from_env(env)
    except Exception as exc:
        print(
            redact_exception(exc),
            file=sys.stderr,
        )
        return 3
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format=(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ),
    )
    logger = logging.getLogger("cbr_trading.earnings")
    store = SqlAlchemyEarningsStore(
        database_url=settings.database_url
    )
    worker = EarningsHostedShadowWorker(
        settings=settings,
        store=store,
        logger=logger,
    )
    try:
        asyncio.run(worker.run_forever())
    except KeyboardInterrupt:
        logger.info("Earnings shadow worker stopped")
        return 130
    except Exception as exc:
        logger.error(
            "Earnings shadow worker stopped error=%s",
            redact_exception(
                RuntimeError(type(exc).__name__)
            ),
        )
        return 5
    finally:
        store.close()
    return 0


def _watches_from_rules(
    rules: Sequence[EarningsMarketRule],
) -> tuple[SecEarningsWatch, ...]:
    watches: list[SecEarningsWatch] = []
    issuer_scopes: dict[str, str] = {}
    for rule in rules:
        if not rule.source_policy.get("sec"):
            continue
        existing_scope = issuer_scopes.get(rule.cik)
        if existing_scope and existing_scope != rule.scope_id:
            raise ValueError(
                "multiple active earnings scopes for one CIK"
            )
        issuer_scopes[rule.cik] = rule.scope_id
        watches.append(
            SecEarningsWatch(
                scope_id=rule.scope_id,
                ticker=rule.ticker,
                cik=rule.cik,
            )
        )
    return tuple(watches)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()
