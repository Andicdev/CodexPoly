from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsParseResult,
    ParseStatus,
)
from cbr_trading.earnings.repository import StoredEarningsRecord
from cbr_trading.sources.earnings import EarningsResolutionSource


class ShadowProcessingStatus(str, Enum):
    SIGNAL = "signal"
    DUPLICATE = "duplicate"
    NO_MATCH = "no_match"
    QUARANTINED = "quarantined"
    ERROR = "error"


@dataclass(frozen=True)
class ShadowProcessingResult:
    status: ShadowProcessingStatus
    reason: str
    scope_id: str
    event_id: int | None = None
    fact_id: int | None = None
    signal: ResolutionSignal | None = None

    def __post_init__(self) -> None:
        if (
            self.status is ShadowProcessingStatus.SIGNAL
        ) != isinstance(self.signal, ResolutionSignal):
            raise ValueError("signal status and signal disagree")


class EarningsStore(Protocol):
    def record_source_event(
        self,
        candidate: EarningsDocumentCandidate,
    ) -> StoredEarningsRecord: ...

    def update_source_event_status(
        self,
        event_id: int,
        *,
        status: str,
        error: str | None = None,
    ) -> None: ...

    def record_fact(
        self,
        *,
        source_event_id: int,
        candidate: EarningsFactCandidate,
        reason: str,
    ) -> StoredEarningsRecord: ...

    def load_validated_facts(
        self,
        *,
        scope_id: str | None = None,
    ) -> Sequence[EarningsFactCandidate]: ...


class DocumentFetcher(Protocol):
    def fetch(self, candidate: EarningsDocumentCandidate) -> bytes: ...


class EarningsParser(Protocol):
    def parse(
        self,
        document: str | bytes,
        *,
        source: EarningsDocumentCandidate,
        rule: EarningsMarketRule,
        detected_at: datetime,
    ) -> EarningsParseResult: ...


class EarningsShadowProcessor:
    """Persist, parse, and resolve one document without any trading layer."""

    _TERMINAL_EVENT_STATUSES = frozenset(
        {"PARSED", "NO_MATCH", "QUARANTINED"}
    )

    def __init__(
        self,
        *,
        store: EarningsStore,
        rules: Sequence[EarningsMarketRule],
        parsers: Mapping[str, EarningsParser],
        document_fetcher: DocumentFetcher,
        max_fetch_attempts: int = 3,
        fetch_retry_delay: float = 0.5,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        rule_rows = tuple(rules)
        self._rules = {
            rule.scope_id: rule
            for rule in rule_rows
        }
        if len(self._rules) != len(rule_rows):
            raise ValueError("earnings rule scopes must be unique")
        self._parsers = {
            str(ticker or "").strip().upper(): parser
            for ticker, parser in parsers.items()
        }
        self._store = store
        self._document_fetcher = document_fetcher
        self._max_fetch_attempts = int(max_fetch_attempts)
        self._fetch_retry_delay = float(fetch_retry_delay)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep
        if self._max_fetch_attempts < 1:
            raise ValueError("max_fetch_attempts must be positive")
        if self._fetch_retry_delay < 0:
            raise ValueError("fetch_retry_delay cannot be negative")

    def process(
        self,
        candidate: EarningsDocumentCandidate,
    ) -> ShadowProcessingResult:
        stored_event = self._store.record_source_event(candidate)
        existing_status = str(stored_event.status or "").upper()
        if (
            not stored_event.created
            and existing_status in self._TERMINAL_EVENT_STATUSES
        ):
            return ShadowProcessingResult(
                status=ShadowProcessingStatus.DUPLICATE,
                reason=f"already_{existing_status.lower()}",
                scope_id=candidate.scope_id,
                event_id=stored_event.row_id,
            )

        rule = self._rules.get(candidate.scope_id)
        if rule is None:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.QUARANTINED,
                reason="active_rule_not_loaded",
            )
        parser = self._parsers.get(rule.ticker)
        if parser is None:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.QUARANTINED,
                reason="company_parser_not_configured",
            )

        document = self._fetch_document(
            candidate,
            event_id=stored_event.row_id,
        )
        if document is None:
            return ShadowProcessingResult(
                status=ShadowProcessingStatus.ERROR,
                reason="document_fetch_failed",
                scope_id=candidate.scope_id,
                event_id=stored_event.row_id,
            )
        self._store.update_source_event_status(
            stored_event.row_id,
            status="FETCHED",
        )

        try:
            parsed = parser.parse(
                document,
                source=candidate,
                rule=rule,
                detected_at=self._clock(),
            )
        except Exception as exc:
            error = f"parser_failed:{type(exc).__name__}"
            self._store.update_source_event_status(
                stored_event.row_id,
                status="ERROR",
                error=error,
            )
            return ShadowProcessingResult(
                status=ShadowProcessingStatus.ERROR,
                reason=error,
                scope_id=candidate.scope_id,
                event_id=stored_event.row_id,
            )

        if parsed.status is ParseStatus.NO_MATCH:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.NO_MATCH,
                reason=parsed.reason,
            )
        if parsed.status is ParseStatus.QUARANTINED:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.QUARANTINED,
                reason=parsed.reason,
            )
        fact = parsed.candidate
        if fact is None:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.ERROR,
                reason="accepted_parse_without_fact",
            )

        stored_fact = self._store.record_fact(
            source_event_id=stored_event.row_id,
            candidate=fact,
            reason=parsed.reason,
        )
        resolver = EarningsResolutionSource(
            candidate_provider=lambda: tuple(
                self._store.load_validated_facts(
                    scope_id=rule.scope_id
                )
            ),
            rules=(rule,),
        )
        signals = resolver.poll_once()
        if len(signals) != 1:
            reason = (
                resolver.quarantine_reasons.get(rule.scope_id)
                or "canonical_signal_not_unique"
            )
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                fact_id=stored_fact.row_id,
                status=ShadowProcessingStatus.QUARANTINED,
                reason=reason,
            )
        self._store.update_source_event_status(
            stored_event.row_id,
            status="PARSED",
        )
        return ShadowProcessingResult(
            status=ShadowProcessingStatus.SIGNAL,
            reason="shadow_resolution_signal",
            scope_id=candidate.scope_id,
            event_id=stored_event.row_id,
            fact_id=stored_fact.row_id,
            signal=signals[0],
        )

    def _fetch_document(
        self,
        candidate: EarningsDocumentCandidate,
        *,
        event_id: int,
    ) -> bytes | None:
        for attempt in range(1, self._max_fetch_attempts + 1):
            try:
                return self._document_fetcher.fetch(candidate)
            except Exception as exc:
                if attempt >= self._max_fetch_attempts:
                    self._store.update_source_event_status(
                        event_id,
                        status="ERROR",
                        error=(
                            "document_fetch_failed:"
                            f"{type(exc).__name__}"
                        ),
                    )
                    return None
                if self._fetch_retry_delay:
                    self._sleep(self._fetch_retry_delay)
        return None

    def _finish_without_signal(
        self,
        *,
        candidate: EarningsDocumentCandidate,
        event_id: int,
        status: ShadowProcessingStatus,
        reason: str,
        fact_id: int | None = None,
    ) -> ShadowProcessingResult:
        database_status = {
            ShadowProcessingStatus.NO_MATCH: "NO_MATCH",
            ShadowProcessingStatus.QUARANTINED: "QUARANTINED",
            ShadowProcessingStatus.ERROR: "ERROR",
        }.get(status)
        if database_status is None:
            raise ValueError("unsupported non-signal status")
        self._store.update_source_event_status(
            event_id,
            status=database_status,
            error=reason,
        )
        return ShadowProcessingResult(
            status=status,
            reason=reason,
            scope_id=candidate.scope_id,
            event_id=event_id,
            fact_id=fact_id,
        )
