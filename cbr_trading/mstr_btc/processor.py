from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.mstr_btc.contracts import (
    MstrBtcAuditStatus,
    MstrBtcDocumentCandidate,
    MstrBtcFactCandidate,
    MstrBtcHoldingsBaseline,
    MstrBtcParseStatus,
    MstrBtcResolutionRule,
)
from cbr_trading.mstr_btc.audit_repository import (
    StoredMstrBtcAuditRecord,
    StoredMstrBtcTerminalResult,
)
from cbr_trading.mstr_btc.parser import MstrBtc8KParser
from cbr_trading.mstr_btc.sec_router import MstrBtcSecWatch
from cbr_trading.mstr_btc.resolution_rules import (
    mstr_jul21_27_resolution_rules,
)


class MstrBtcShadowStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    NO_MATCH = "no_match"
    QUARANTINED = "quarantined"
    ERROR = "error"


@dataclass(frozen=True)
class MstrBtcShadowResult:
    status: MstrBtcShadowStatus
    reason: str
    scope_id: str
    baseline_state_id: str | None = None
    source_event_id: int | None = None
    fact_candidate_id: int | None = None
    processing_result_id: int | None = None
    fact: MstrBtcFactCandidate | None = None
    signals: tuple[ResolutionSignal, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.status is MstrBtcShadowStatus.ACCEPTED
        ) != isinstance(self.fact, MstrBtcFactCandidate):
            raise ValueError("accepted status and fact disagree")
        signals = tuple(self.signals)
        if any(
            not isinstance(signal, ResolutionSignal)
            for signal in signals
        ):
            raise TypeError(
                "signals must contain only ResolutionSignal objects"
            )
        if (
            self.status is not MstrBtcShadowStatus.ACCEPTED
            and signals
        ):
            raise ValueError("only accepted results may contain signals")
        object.__setattr__(self, "signals", signals)


class MstrBtcBaselineStore(Protocol):
    def pin_baseline(
        self,
        *,
        before: datetime,
    ) -> MstrBtcHoldingsBaseline: ...


class MstrBtcAuditStore(Protocol):
    def record_source_event(
        self,
        candidate: MstrBtcDocumentCandidate,
    ) -> StoredMstrBtcAuditRecord: ...

    def load_terminal_result(
        self,
        *,
        source_event_id: int,
    ) -> StoredMstrBtcTerminalResult | None: ...

    def record_fact(
        self,
        *,
        source_event_id: int,
        candidate: MstrBtcFactCandidate,
        reason: str,
    ) -> StoredMstrBtcAuditRecord: ...

    def record_processing_result(
        self,
        *,
        source_event_id: int,
        status: MstrBtcAuditStatus,
        reason: str,
        baseline_state_id: str | int | None = None,
        fact_candidate_id: int | None = None,
    ) -> StoredMstrBtcAuditRecord: ...

    def load_validated_facts(
        self,
        *,
        scope_id: str | None = None,
    ) -> tuple[MstrBtcFactCandidate, ...]: ...


class MstrBtcDocumentFetcher(Protocol):
    def fetch(self, candidate: MstrBtcDocumentCandidate) -> bytes: ...


class MstrBtcShadowProcessor:
    """Fetch and parse MSTR filings against an immutable pre-window baseline."""

    def __init__(
        self,
        *,
        store: MstrBtcBaselineStore,
        audit_store: MstrBtcAuditStore,
        watch: MstrBtcSecWatch,
        document_fetcher: MstrBtcDocumentFetcher,
        parser: MstrBtc8KParser | None = None,
        resolution_rules: (
            tuple[MstrBtcResolutionRule, ...] | None
        ) = None,
        max_fetch_attempts: int = 3,
        fetch_retry_delay: float = 0.5,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if max_fetch_attempts < 1:
            raise ValueError("max_fetch_attempts must be positive")
        if fetch_retry_delay < 0:
            raise ValueError("fetch_retry_delay cannot be negative")
        self._store = store
        self._audit_store = audit_store
        self._watch = watch
        self._document_fetcher = document_fetcher
        self._parser = parser or MstrBtc8KParser()
        self._resolution_rules = (
            tuple(resolution_rules)
            if resolution_rules is not None
            else mstr_jul21_27_resolution_rules()
        )
        self._max_fetch_attempts = int(max_fetch_attempts)
        self._fetch_retry_delay = float(fetch_retry_delay)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep

    def process(
        self,
        candidate: MstrBtcDocumentCandidate,
    ) -> MstrBtcShadowResult:
        if candidate.scope_id != self._watch.scope_id:
            return self._result(
                candidate,
                MstrBtcShadowStatus.QUARANTINED,
                "watch_scope_mismatch",
            )
        try:
            stored_event = self._audit_store.record_source_event(
                candidate
            )
            terminal = self._audit_store.load_terminal_result(
                source_event_id=stored_event.row_id,
            )
        except Exception as exc:
            return self._result(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"audit_event_failed:{type(exc).__name__}",
            )
        if terminal is not None:
            return MstrBtcShadowResult(
                status=MstrBtcShadowStatus.DUPLICATE,
                reason=f"already_{terminal.status.value.lower()}",
                scope_id=candidate.scope_id,
                baseline_state_id=terminal.baseline_state_id,
                source_event_id=stored_event.row_id,
                fact_candidate_id=terminal.fact_candidate_id,
                processing_result_id=terminal.row_id,
            )
        try:
            baseline = self._store.pin_baseline(
                before=self._watch.window_start,
            )
        except Exception as exc:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"baseline_pin_failed:{type(exc).__name__}",
                source_event_id=stored_event.row_id,
            )
        document = self._fetch_document(candidate)
        if document is None:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.ERROR,
                "document_fetch_failed",
                source_event_id=stored_event.row_id,
                baseline=baseline,
            )
        try:
            parsed = self._parser.parse(
                document,
                source=candidate,
                baseline=baseline,
                detected_at=self._clock(),
            )
        except Exception as exc:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"parser_failed:{type(exc).__name__}",
                source_event_id=stored_event.row_id,
                baseline=baseline,
            )
        if parsed.status is MstrBtcParseStatus.NO_MATCH:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.NO_MATCH,
                parsed.reason,
                source_event_id=stored_event.row_id,
                baseline=baseline,
            )
        if parsed.status is MstrBtcParseStatus.QUARANTINED:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.QUARANTINED,
                parsed.reason,
                source_event_id=stored_event.row_id,
                baseline=baseline,
            )
        if parsed.candidate is None:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.ERROR,
                "accepted_parse_without_fact",
                source_event_id=stored_event.row_id,
                baseline=baseline,
            )
        try:
            stored_fact = self._audit_store.record_fact(
                source_event_id=stored_event.row_id,
                candidate=parsed.candidate,
                reason=parsed.reason,
            )
        except Exception as exc:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"audit_fact_failed:{type(exc).__name__}",
                source_event_id=stored_event.row_id,
                baseline=baseline,
            )
        try:
            from cbr_trading.sources.mstr_btc import (
                MstrBtcResolutionSource,
            )

            source = MstrBtcResolutionSource(
                candidate_provider=lambda: (
                    self._audit_store.load_validated_facts(
                        scope_id=candidate.scope_id,
                    )
                ),
                rules=self._resolution_rules,
            )
            signals = source.poll_once()
        except Exception as exc:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"signal_build_failed:{type(exc).__name__}",
                source_event_id=stored_event.row_id,
                baseline=baseline,
            )
        try:
            stored_result = (
                self._audit_store.record_processing_result(
                    source_event_id=stored_event.row_id,
                    status=MstrBtcAuditStatus.ACCEPTED,
                    reason=parsed.reason,
                    baseline_state_id=baseline.state_id,
                    fact_candidate_id=stored_fact.row_id,
                )
            )
        except Exception as exc:
            return self._finish(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"audit_accept_failed:{type(exc).__name__}",
                source_event_id=stored_event.row_id,
                baseline=baseline,
            )
        return MstrBtcShadowResult(
            status=MstrBtcShadowStatus.ACCEPTED,
            reason=parsed.reason,
            scope_id=candidate.scope_id,
            baseline_state_id=baseline.state_id,
            source_event_id=stored_event.row_id,
            fact_candidate_id=stored_fact.row_id,
            processing_result_id=stored_result.row_id,
            fact=parsed.candidate,
            signals=signals,
        )

    def _fetch_document(
        self,
        candidate: MstrBtcDocumentCandidate,
    ) -> bytes | None:
        for attempt in range(1, self._max_fetch_attempts + 1):
            try:
                return self._document_fetcher.fetch(candidate)
            except Exception:
                if attempt >= self._max_fetch_attempts:
                    return None
                self._sleep(self._fetch_retry_delay)
        return None

    @staticmethod
    def _result(
        candidate: MstrBtcDocumentCandidate,
        status: MstrBtcShadowStatus,
        reason: str,
        *,
        baseline: MstrBtcHoldingsBaseline | None = None,
        source_event_id: int | None = None,
        processing_result_id: int | None = None,
    ) -> MstrBtcShadowResult:
        return MstrBtcShadowResult(
            status=status,
            reason=reason,
            scope_id=candidate.scope_id,
            baseline_state_id=(
                baseline.state_id
                if baseline is not None
                else None
            ),
            source_event_id=source_event_id,
            processing_result_id=processing_result_id,
        )

    def _finish(
        self,
        candidate: MstrBtcDocumentCandidate,
        status: MstrBtcShadowStatus,
        reason: str,
        *,
        source_event_id: int,
        baseline: MstrBtcHoldingsBaseline | None = None,
    ) -> MstrBtcShadowResult:
        audit_status = {
            MstrBtcShadowStatus.NO_MATCH: MstrBtcAuditStatus.NO_MATCH,
            MstrBtcShadowStatus.QUARANTINED: (
                MstrBtcAuditStatus.QUARANTINED
            ),
            MstrBtcShadowStatus.ERROR: MstrBtcAuditStatus.ERROR,
        }.get(status)
        if audit_status is None:
            raise ValueError("unsupported terminal shadow status")
        try:
            stored_result = self._audit_store.record_processing_result(
                source_event_id=source_event_id,
                status=audit_status,
                reason=reason,
                baseline_state_id=(
                    baseline.state_id
                    if baseline is not None
                    else None
                ),
            )
        except Exception as exc:
            return self._result(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"audit_result_failed:{type(exc).__name__}",
                baseline=baseline,
                source_event_id=source_event_id,
            )
        return self._result(
            candidate,
            status,
            reason,
            baseline=baseline,
            source_event_id=source_event_id,
            processing_result_id=stored_result.row_id,
        )
