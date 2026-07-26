from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsMarketRule,
)
from cbr_trading.earnings.document_fetcher import SecDocumentFetcher
from cbr_trading.earnings.parsers import earnings_parser_registry
from cbr_trading.earnings.processor import (
    EarningsShadowProcessor,
    ShadowProcessingStatus,
)
from cbr_trading.earnings.repository import SqlAlchemyEarningsStore
from cbr_trading.earnings.sec_stream import (
    SecEarningsWatch,
    SecStreamFilingRouter,
    SecStreamTransportError,
)
from cbr_trading.earnings.settings import EarningsWorkerSettings
from cbr_trading.mstr_btc.contracts import MstrBtcDocumentCandidate
from cbr_trading.mstr_btc.audit_repository import (
    SqlAlchemyMstrBtcAuditStore,
)
from cbr_trading.mstr_btc.processor import (
    MstrBtcShadowProcessor,
    MstrBtcShadowStatus,
)
from cbr_trading.mstr_btc.repository import (
    SqlAlchemyMstrBtcHoldingsStore,
)
from cbr_trading.mstr_btc.sec_router import (
    MstrBtcRouter,
    MstrBtcSecWatch,
    mstr_jul21_27_shadow_watch,
)
from cbr_trading.sec_filings.stream import SecStreamTransport
from cbr_trading.secret_guard import redact_exception


class StreamTransport(Protocol):
    def stream_once(self): ...


SecWatch = SecEarningsWatch | MstrBtcSecWatch
TransportBuilder = Callable[[Sequence[SecWatch]], StreamTransport]


class WorkerCycleStatus(str, Enum):
    STREAM_CLOSED = "stream_closed"
    NO_RULES = "no_rules"


@dataclass(frozen=True)
class WorkerCycleResult:
    status: WorkerCycleStatus
    watch_count: int
    processed_count: int = 0
    signal_count: int = 0
    mstr_accepted_count: int = 0


class _RoutedSecShadowTransport:
    """Fan one source-neutral SEC connection out to semantic routers."""

    def __init__(
        self,
        *,
        transport: SecStreamTransport,
        earnings_watches: Sequence[SecEarningsWatch],
        mstr_watches: Sequence[MstrBtcSecWatch],
    ):
        self._transport = transport
        self._earnings_router = (
            SecStreamFilingRouter(earnings_watches)
            if earnings_watches
            else None
        )
        if len(mstr_watches) > 1:
            raise ValueError("only one active MSTR BTC watch is supported")
        self._mstr_router = (
            MstrBtcRouter(mstr_watches[0])
            if mstr_watches
            else None
        )

    async def stream_once(
        self,
    ) -> AsyncIterator[
        EarningsDocumentCandidate | MstrBtcDocumentCandidate
    ]:
        async for envelope in self._transport.stream_once():
            if self._earnings_router is not None:
                for decision in self._earnings_router.route(envelope):
                    if decision.candidate is not None:
                        yield decision.candidate
            if self._mstr_router is not None:
                decision = self._mstr_router.route(envelope)
                if decision.candidate is not None:
                    yield decision.candidate


class EarningsHostedShadowWorker:
    """Reconnect SEC transport and persist only shadow source outcomes."""

    def __init__(
        self,
        *,
        settings: EarningsWorkerSettings,
        store: SqlAlchemyEarningsStore,
        mstr_store: SqlAlchemyMstrBtcHoldingsStore | None = None,
        mstr_audit_store: SqlAlchemyMstrBtcAuditStore | None = None,
        mstr_watch: MstrBtcSecWatch | None = None,
        transport_builder: TransportBuilder | None = None,
        parsers: Mapping[str, object] | None = None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._store = store
        self._mstr_watch = (
            mstr_watch
            if mstr_watch is not None
            else (
                mstr_jul21_27_shadow_watch()
                if settings.mstr_btc_shadow_enabled
                else None
            )
        )
        self._mstr_store = mstr_store
        self._mstr_audit_store = mstr_audit_store
        if self._mstr_watch is not None and (
            self._mstr_store is None
            or self._mstr_audit_store is None
        ):
            raise ValueError(
                "MSTR holdings and audit stores are required when "
                "MSTR shadow is enabled"
            )
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
        self._mstr_accepted_count = 0
        self._error_count = 0

    async def run_forever(self) -> None:
        await asyncio.to_thread(self._store.ensure_ready)
        if self._mstr_store is not None:
            await asyncio.to_thread(self._mstr_store.ensure_ready)
        if self._mstr_audit_store is not None:
            await asyncio.to_thread(
                self._mstr_audit_store.ensure_ready
            )
        self._logger.info(
            "SEC shadow worker schema ready mode=shadow "
            "earnings=true mstr=%s",
            self._mstr_watch is not None,
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
                        "SEC filing stream closed; reconnecting "
                        "watches=%s processed=%s signals=%s "
                        "mstr_accepted=%s",
                        cycle.watch_count,
                        cycle.processed_count,
                        cycle.signal_count,
                        cycle.mstr_accepted_count,
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
                        "SEC filing stream cycle failed; "
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
        earnings_watches = _watches_from_rules(rules)
        mstr_watches = (
            (self._mstr_watch,)
            if self._mstr_watch is not None
            else ()
        )
        watches: tuple[SecWatch, ...] = (
            *earnings_watches,
            *mstr_watches,
        )
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
        earnings_processor = (
            EarningsShadowProcessor(
                store=self._store,
                rules=rules,
                parsers=self._parsers,
                document_fetcher=fetcher,
                max_fetch_attempts=self._settings.max_fetch_attempts,
                fetch_retry_delay=self._settings.fetch_retry_delay,
            )
            if earnings_watches
            else None
        )
        mstr_processor = (
            MstrBtcShadowProcessor(
                store=self._mstr_store,
                audit_store=self._mstr_audit_store,
                watch=self._mstr_watch,
                document_fetcher=fetcher,
                max_fetch_attempts=self._settings.max_fetch_attempts,
                fetch_retry_delay=self._settings.fetch_retry_delay,
            )
            if (
                self._mstr_store is not None
                and self._mstr_audit_store is not None
                and self._mstr_watch is not None
            )
            else None
        )
        transport = self._transport_builder(watches)
        processed = 0
        signals = 0
        mstr_accepted = 0
        self._connected = True
        self._logger.info(
            "SEC shadow stream connecting watches=%s "
            "earnings_watches=%s mstr_watches=%s",
            len(watches),
            len(earnings_watches),
            len(mstr_watches),
        )
        try:
            async for candidate in transport.stream_once():
                processed += 1
                self._processed_count += 1
                if isinstance(candidate, EarningsDocumentCandidate):
                    if earnings_processor is None:
                        self._error_count += 1
                        self._logger.warning(
                            "Earnings SEC candidate has no processor "
                            "scope=%s ticker=%s",
                            candidate.scope_id,
                            candidate.ticker,
                        )
                        continue
                    result = await asyncio.to_thread(
                        earnings_processor.process,
                        candidate,
                    )
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
                    continue
                if isinstance(candidate, MstrBtcDocumentCandidate):
                    if mstr_processor is None:
                        self._error_count += 1
                        self._logger.warning(
                            "MSTR SEC candidate has no processor "
                            "scope=%s",
                            candidate.scope_id,
                        )
                        continue
                    result = await asyncio.to_thread(
                        mstr_processor.process,
                        candidate,
                    )
                    if result.status is MstrBtcShadowStatus.ACCEPTED:
                        mstr_accepted += 1
                        self._mstr_accepted_count += 1
                    if result.status is MstrBtcShadowStatus.ERROR:
                        self._error_count += 1
                    fact = result.fact
                    self._logger.info(
                        "MSTR BTC shadow document processed "
                        "scope=%s status=%s reason=%s baseline=%s "
                        "event_id=%s fact_id=%s result_id=%s "
                        "resolution_signals=%s signal_ids=%s "
                        "holdings_before=%s holdings_after=%s "
                        "acquired=%s sold=%s",
                        result.scope_id,
                        result.status.value,
                        result.reason,
                        result.baseline_state_id,
                        result.source_event_id,
                        result.fact_candidate_id,
                        result.processing_result_id,
                        len(result.signals),
                        ",".join(
                            signal.signal_id
                            for signal in result.signals
                        ),
                        (
                            fact.holdings_before_btc
                            if fact is not None
                            else None
                        ),
                        (
                            fact.holdings_after_btc
                            if fact is not None
                            else None
                        ),
                        (
                            fact.acquired_btc
                            if fact is not None
                            else None
                        ),
                        (
                            fact.sold_btc
                            if fact is not None
                            else None
                        ),
                    )
                    continue
                self._error_count += 1
                self._logger.warning(
                    "SEC router emitted unsupported candidate type=%s",
                    type(candidate).__name__,
                )
        finally:
            self._connected = False
        return WorkerCycleResult(
            status=WorkerCycleStatus.STREAM_CLOSED,
            watch_count=len(watches),
            processed_count=processed,
            signal_count=signals,
            mstr_accepted_count=mstr_accepted,
        )

    def _default_transport_builder(
        self,
        watches: Sequence[SecWatch],
    ) -> _RoutedSecShadowTransport:
        api_key = self._settings.sec_api_key
        if not api_key:
            raise RuntimeError("SEC API credential is unavailable")
        earnings_watches = tuple(
            watch
            for watch in watches
            if isinstance(watch, SecEarningsWatch)
        )
        mstr_watches = tuple(
            watch
            for watch in watches
            if isinstance(watch, MstrBtcSecWatch)
        )
        return _RoutedSecShadowTransport(
            transport=SecStreamTransport(api_key=api_key),
            earnings_watches=earnings_watches,
            mstr_watches=mstr_watches,
        )

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._settings.heartbeat_interval
            )
            self._logger.info(
                "SEC shadow heartbeat connected=%s watches=%s "
                "processed=%s signals=%s mstr_accepted=%s errors=%s",
                self._connected,
                self._watch_count,
                self._processed_count,
                self._signal_count,
                self._mstr_accepted_count,
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
    mstr_store = (
        SqlAlchemyMstrBtcHoldingsStore(
            database_url=settings.database_url
        )
        if settings.mstr_btc_shadow_enabled
        else None
    )
    mstr_audit_store = (
        SqlAlchemyMstrBtcAuditStore(
            database_url=settings.database_url
        )
        if settings.mstr_btc_shadow_enabled
        else None
    )
    worker = EarningsHostedShadowWorker(
        settings=settings,
        store=store,
        mstr_store=mstr_store,
        mstr_audit_store=mstr_audit_store,
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
        if mstr_store is not None:
            mstr_store.close()
        if mstr_audit_store is not None:
            mstr_audit_store.close()
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
