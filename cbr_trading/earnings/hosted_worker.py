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
from cbr_trading.earnings.public_sources import (
    PublicReleaseDocumentFetcher,
    PublicReleaseFeedClient,
    PublicReleaseWatch,
    public_release_watches_from_rules,
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
    MstrBtcShadowResult,
    MstrBtcShadowStatus,
)
from cbr_trading.mstr_btc.ledger_source import (
    MstrBtcLedgerDocumentFetcher,
    MstrBtcLedgerParser,
    MstrBtcLedgerWatch,
    StrategyLedgerClient,
    evaluate_mstr_btc_ledger,
    mstr_jul21_27_ledger_watch,
)
from cbr_trading.mstr_btc.repository import (
    SqlAlchemyMstrBtcHoldingsStore,
)
from cbr_trading.mstr_btc.sec_router import (
    MstrBtcRouter,
    MstrBtcSecWatch,
    mstr_jul21_27_shadow_watch,
)
from cbr_trading.notifications import (
    SourceEventNotification,
    SqlAlchemyNotificationOutboxStore,
    source_event_notification_from_earnings,
    source_event_notification_from_mstr,
)
from cbr_trading.orchestration import (
    SqlAlchemyResolutionProfileStore,
)
from cbr_trading.sec_filings.stream import SecStreamTransport
from cbr_trading.secret_guard import redact_exception
from cbr_trading.source_runtime import ProfileWindowPollingGate
from cbr_trading.sources import (
    EARNINGS_SOURCE_NAME,
    MSTR_BTC_SOURCE_NAME,
)


class StreamTransport(Protocol):
    def stream_once(self): ...


SecWatch = SecEarningsWatch | MstrBtcSecWatch
TransportBuilder = Callable[[Sequence[SecWatch]], StreamTransport]
PublicDocumentFetcherBuilder = Callable[
    [Sequence[PublicReleaseWatch]],
    object,
]


class NotificationOutbox(Protocol):
    def ensure_ready(self) -> None: ...

    def enqueue(
        self,
        notification: SourceEventNotification,
        *,
        delivery_delay_seconds: float = 0,
    ): ...


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
        mstr_ledger_watch: MstrBtcLedgerWatch | None = None,
        ledger_client: StrategyLedgerClient | None = None,
        ledger_polling_gate: ProfileWindowPollingGate | None = None,
        public_release_client: PublicReleaseFeedClient | None = None,
        public_polling_gate: ProfileWindowPollingGate | None = None,
        public_document_fetcher_builder: (
            PublicDocumentFetcherBuilder | None
        ) = None,
        notification_store: NotificationOutbox | None = None,
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
        self._mstr_ledger_watch = (
            mstr_ledger_watch
            if mstr_ledger_watch is not None
            else (
                mstr_jul21_27_ledger_watch()
                if settings.mstr_btc_ledger_enabled
                else None
            )
        )
        self._mstr_store = mstr_store
        self._mstr_audit_store = mstr_audit_store
        if (
            self._mstr_watch is not None
            or self._mstr_ledger_watch is not None
        ) and (
            self._mstr_store is None
            or self._mstr_audit_store is None
        ):
            raise ValueError(
                "MSTR holdings and audit stores are required when "
                "MSTR shadow is enabled"
            )
        self._ledger_client = (
            ledger_client
            if ledger_client is not None
            else (
                StrategyLedgerClient(
                    url=settings.mstr_btc_ledger_url,
                    timeout=settings.mstr_btc_ledger_timeout,
                )
                if self._mstr_ledger_watch is not None
                else None
            )
        )
        self._ledger_polling_gate = ledger_polling_gate
        if (
            self._mstr_ledger_watch is not None
            and self._ledger_polling_gate is None
        ):
            raise ValueError(
                "MSTR Ledger polling requires an active-profile gate"
            )
        self._public_release_client = (
            public_release_client
            if public_release_client is not None
            else (
                PublicReleaseFeedClient(
                    user_agent=settings.http_user_agent,
                    timeout=settings.fetch_timeout,
                    logger=logger,
                )
                if settings.public_sources_enabled
                else None
            )
        )
        self._public_polling_gate = public_polling_gate
        if (
            self._public_release_client is not None
            and self._public_polling_gate is None
        ):
            raise ValueError(
                "public earnings polling requires an "
                "active-profile gate"
            )
        self._public_document_fetcher_builder = (
            public_document_fetcher_builder
            or self._default_public_document_fetcher
        )
        self._notification_store = notification_store
        self._ledger_processor = (
            MstrBtcShadowProcessor(
                store=self._mstr_store,
                audit_store=self._mstr_audit_store,
                watch=self._mstr_ledger_watch,
                document_fetcher=MstrBtcLedgerDocumentFetcher(),
                parser=MstrBtcLedgerParser(),
                max_fetch_attempts=1,
                fetch_retry_delay=0,
            )
            if (
                self._mstr_store is not None
                and self._mstr_audit_store is not None
                and self._mstr_ledger_watch is not None
            )
            else None
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
        self._ledger_connected = False
        self._ledger_polling_active = False
        self._ledger_active_profile_count = 0
        self._ledger_poll_count = 0
        self._ledger_accepted_count = 0
        self._ledger_last_fingerprint: str | None = None
        self._public_polling_active = False
        self._public_active_scope_count = 0
        self._public_watch_count = 0
        self._public_poll_count = 0
        self._public_feed_success_count = 0
        self._public_candidate_count = 0
        self._public_signal_count = 0
        self._public_completed_events: set[
            tuple[str, str, str, str]
        ] = set()
        self._error_count = 0

    async def run_forever(self) -> None:
        await asyncio.to_thread(self._store.ensure_ready)
        if self._mstr_store is not None:
            await asyncio.to_thread(self._mstr_store.ensure_ready)
        if self._mstr_audit_store is not None:
            await asyncio.to_thread(
                self._mstr_audit_store.ensure_ready
            )
        if self._notification_store is not None:
            await asyncio.to_thread(
                self._notification_store.ensure_ready
            )
        self._logger.info(
            "SEC shadow worker schema ready mode=shadow "
            "earnings=true public=%s mstr=%s ledger=%s",
            self._public_release_client is not None,
            self._mstr_watch is not None,
            self._mstr_ledger_watch is not None,
        )
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        ledger_task = (
            asyncio.create_task(self._ledger_poll_loop())
            if self._ledger_client is not None
            else None
        )
        public_task = (
            asyncio.create_task(self._public_poll_loop())
            if self._public_release_client is not None
            else None
        )
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
            self._ledger_connected = False
            heartbeat.cancel()
            if ledger_task is not None:
                ledger_task.cancel()
            if public_task is not None:
                public_task.cancel()
            await asyncio.gather(
                *tuple(
                    task
                    for task in (
                        heartbeat,
                        ledger_task,
                        public_task,
                    )
                    if task is not None
                ),
                return_exceptions=True,
            )
            if self._ledger_client is not None:
                await asyncio.to_thread(self._ledger_client.close)
            if self._public_release_client is not None:
                await asyncio.to_thread(
                    self._public_release_client.close
                )

    async def run_connection_cycle(self) -> WorkerCycleResult:
        rules = tuple(
            await asyncio.to_thread(
                self._store.load_active_rules
            )
        )
        rules_by_scope = {
            rule.scope_id: rule
            for rule in rules
        }
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
                        await self._enqueue_notification(
                            source_event_notification_from_earnings(
                                candidate=candidate,
                                signal=result.signal,
                                rule=rules_by_scope[candidate.scope_id],
                            )
                        )
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
                        await self._enqueue_notification(
                            source_event_notification_from_mstr(
                                fact=result.fact,
                                signals=result.signals,
                            )
                        )
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

    def _default_public_document_fetcher(
        self,
        watches: Sequence[PublicReleaseWatch],
    ) -> PublicReleaseDocumentFetcher:
        return PublicReleaseDocumentFetcher(
            watches=watches,
            user_agent=self._settings.http_user_agent,
            timeout=self._settings.fetch_timeout,
            max_bytes=self._settings.max_document_bytes,
        )

    async def run_public_poll_cycle(self) -> int:
        """Poll IR/wire feeds only for enabled, in-window scopes."""

        if self._public_release_client is None:
            return 0
        active_scopes = await asyncio.to_thread(
            self._public_polling_gate.active_scope_ids
        )
        self._public_active_scope_count = len(active_scopes)
        self._public_polling_active = bool(active_scopes)
        if not active_scopes:
            self._public_watch_count = 0
            return 0

        rules = tuple(
            await asyncio.to_thread(
                self._store.load_active_rules
            )
        )
        active_rules = tuple(
            rule
            for rule in rules
            if rule.scope_id in active_scopes
        )
        rules_by_scope = {
            rule.scope_id: rule
            for rule in active_rules
        }
        watches = public_release_watches_from_rules(active_rules)
        self._public_watch_count = len(watches)
        if not watches:
            return 0

        watches_by_feed: dict[
            tuple[str, str, int],
            list[PublicReleaseWatch],
        ] = {}
        for watch in watches:
            watches_by_feed.setdefault(
                (
                    watch.kind,
                    watch.feed_url,
                    watch.listing_utc_offset_minutes,
                ),
                [],
            ).append(watch)
        poll_results = await asyncio.gather(
            *(
                asyncio.to_thread(
                    self._public_release_client.poll,
                    tuple(feed_watches),
                )
                for _, feed_watches
                in sorted(watches_by_feed.items())
            )
        )
        self._public_poll_count += 1
        self._public_feed_success_count += (
            sum(
                result.success_count
                for result in poll_results
            )
        )
        self._error_count += sum(
            result.error_count
            for result in poll_results
        )
        candidates = tuple(
            candidate
            for result in poll_results
            for candidate in result.candidates
        )
        if not candidates:
            return 0

        fetcher = self._public_document_fetcher_builder(watches)
        processor = EarningsShadowProcessor(
            store=self._store,
            rules=active_rules,
            parsers=self._parsers,
            document_fetcher=fetcher,
            max_fetch_attempts=self._settings.max_fetch_attempts,
            fetch_retry_delay=self._settings.fetch_retry_delay,
        )
        processed = 0
        for candidate in candidates:
            event_key = (
                candidate.scope_id,
                candidate.provider.value,
                candidate.provider_event_id,
                candidate.source_url,
            )
            if event_key in self._public_completed_events:
                continue
            processed += 1
            self._public_candidate_count += 1
            result = await asyncio.to_thread(
                processor.process,
                candidate,
            )
            if result.status is ShadowProcessingStatus.SIGNAL:
                self._public_signal_count += 1
                await self._enqueue_notification(
                    source_event_notification_from_earnings(
                        candidate=candidate,
                        signal=result.signal,
                        rule=rules_by_scope[candidate.scope_id],
                    )
                )
            if result.status is ShadowProcessingStatus.ERROR:
                self._error_count += 1
            else:
                self._public_completed_events.add(event_key)
            self._logger.info(
                "Public earnings document processed "
                "provider=%s scope=%s ticker=%s status=%s "
                "reason=%s event_id=%s fact_id=%s value=%s",
                candidate.provider.value,
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
        return processed

    async def _public_poll_loop(self) -> None:
        previous_active: bool | None = None
        while True:
            try:
                await self.run_public_poll_cycle()
                if previous_active is not self._public_polling_active:
                    self._logger.info(
                        "Public earnings polling state active=%s "
                        "scopes=%s watches=%s",
                        self._public_polling_active,
                        self._public_active_scope_count,
                        self._public_watch_count,
                    )
                    previous_active = self._public_polling_active
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error_count += 1
                self._logger.warning(
                    "Public earnings poll failed error_code=%s",
                    type(exc).__name__,
                )
            await asyncio.sleep(
                self._settings.public_poll_interval
            )

    async def run_ledger_poll_cycle(
        self,
    ) -> MstrBtcShadowResult | None:
        if (
            self._ledger_client is None
            or self._mstr_ledger_watch is None
            or self._ledger_processor is None
        ):
            return None
        profile_count = await asyncio.to_thread(
            self._ledger_polling_gate.active_profile_count
        )
        self._ledger_active_profile_count = profile_count
        self._ledger_polling_active = profile_count > 0
        if not self._ledger_polling_active:
            self._ledger_connected = False
            return None
        snapshot = await asyncio.to_thread(
            self._ledger_client.fetch_snapshot
        )
        self._ledger_connected = True
        self._ledger_poll_count += 1
        if snapshot is None:
            return None
        if snapshot.fingerprint == self._ledger_last_fingerprint:
            return None
        self._ledger_last_fingerprint = snapshot.fingerprint
        decision = evaluate_mstr_btc_ledger(
            snapshot,
            watch=self._mstr_ledger_watch,
        )
        if decision.candidate is None:
            if decision.reason != "no_new_ledger_rows":
                self._logger.warning(
                    "Strategy Ledger snapshot rejected reason=%s",
                    decision.reason,
                )
            return None
        result = await asyncio.to_thread(
            self._ledger_processor.process,
            decision.candidate,
        )
        if result.status is MstrBtcShadowStatus.ACCEPTED:
            self._ledger_accepted_count += 1
            await self._enqueue_notification(
                source_event_notification_from_mstr(
                    fact=result.fact,
                    signals=result.signals,
                )
            )
        if result.status is MstrBtcShadowStatus.ERROR:
            self._error_count += 1
        fact = result.fact
        self._logger.info(
            "MSTR BTC Ledger document processed "
            "scope=%s status=%s reason=%s baseline=%s "
            "event_id=%s fact_id=%s result_id=%s "
            "resolution_signals=%s holdings_before=%s "
            "holdings_after=%s acquired=%s sold=%s",
            result.scope_id,
            result.status.value,
            result.reason,
            result.baseline_state_id,
            result.source_event_id,
            result.fact_candidate_id,
            result.processing_result_id,
            len(result.signals),
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
            fact.acquired_btc if fact is not None else None,
            fact.sold_btc if fact is not None else None,
        )
        return result

    async def _ledger_poll_loop(self) -> None:
        previous_active: bool | None = None
        while True:
            try:
                await self.run_ledger_poll_cycle()
                if previous_active is not self._ledger_polling_active:
                    self._logger.info(
                        "Strategy Ledger polling state active=%s "
                        "profiles=%s",
                        self._ledger_polling_active,
                        self._ledger_active_profile_count,
                    )
                    previous_active = self._ledger_polling_active
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ledger_connected = False
                self._error_count += 1
                self._logger.warning(
                    "Strategy Ledger poll failed error_code=%s",
                    type(exc).__name__,
                )
            await asyncio.sleep(
                self._settings.mstr_btc_ledger_poll_interval
            )

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._settings.heartbeat_interval
            )
            self._logger.info(
                "SEC shadow heartbeat connected=%s watches=%s "
                "processed=%s signals=%s mstr_accepted=%s "
                "public_active=%s public_scopes=%s "
                "public_watches=%s public_polls=%s "
                "public_feed_success=%s public_candidates=%s "
                "public_signals=%s "
                "ledger_active=%s ledger_profiles=%s "
                "ledger_connected=%s ledger_polls=%s "
                "ledger_accepted=%s errors=%s",
                self._connected,
                self._watch_count,
                self._processed_count,
                self._signal_count,
                self._mstr_accepted_count,
                self._public_polling_active,
                self._public_active_scope_count,
                self._public_watch_count,
                self._public_poll_count,
                self._public_feed_success_count,
                self._public_candidate_count,
                self._public_signal_count,
                self._ledger_polling_active,
                self._ledger_active_profile_count,
                self._ledger_connected,
                self._ledger_poll_count,
                self._ledger_accepted_count,
                self._error_count,
            )

    async def _enqueue_notification(
        self,
        notification: SourceEventNotification,
    ) -> None:
        if self._notification_store is None:
            return
        try:
            stored = await asyncio.to_thread(
                self._notification_store.enqueue,
                notification,
                delivery_delay_seconds=(
                    self._settings.notification_delivery_delay
                ),
            )
        except Exception as exc:
            self._error_count += 1
            self._logger.warning(
                "Source notification enqueue failed source=%s "
                "scope=%s error_code=%s",
                notification.source_name,
                notification.scope_id,
                type(exc).__name__,
            )
            return
        self._logger.info(
            "Source notification enqueued source=%s scope=%s "
            "row_id=%s created=%s",
            notification.source_name,
            notification.scope_id,
            stored.row_id,
            stored.created,
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
    profile_store = (
        SqlAlchemyResolutionProfileStore(
            database_url=settings.database_url
        )
        if (
            settings.mstr_btc_ledger_enabled
            or settings.public_sources_enabled
        )
        else None
    )
    ledger_polling_gate = (
        ProfileWindowPollingGate(
            profile_store=profile_store,
            source_name=MSTR_BTC_SOURCE_NAME,
        )
        if profile_store is not None
        and settings.mstr_btc_ledger_enabled
        else None
    )
    public_polling_gate = (
        ProfileWindowPollingGate(
            profile_store=profile_store,
            source_name=EARNINGS_SOURCE_NAME,
        )
        if profile_store is not None
        and settings.public_sources_enabled
        else None
    )
    notification_store = SqlAlchemyNotificationOutboxStore(
        database_url=settings.database_url
    )
    worker = EarningsHostedShadowWorker(
        settings=settings,
        store=store,
        mstr_store=mstr_store,
        mstr_audit_store=mstr_audit_store,
        ledger_polling_gate=ledger_polling_gate,
        public_polling_gate=public_polling_gate,
        notification_store=notification_store,
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
        if profile_store is not None:
            profile_store.close()
        notification_store.close()
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
