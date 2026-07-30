from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsDocumentFetchResult,
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsParseResult,
    EarningsSourceTiming,
    ParseStatus,
)
from cbr_trading.earnings.repository import StoredEarningsRecord
from cbr_trading.sources.earnings import EarningsResolutionSource


class ShadowProcessingStatus(str, Enum):
    SIGNAL = "signal"
    OBSERVED = "observed"
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
        timing: EarningsSourceTiming | None = None,
    ) -> None: ...

    def claim_no_match_retry(
        self,
        *,
        source_event_id: int,
        parser_name: str,
        parser_version: str,
    ) -> bool: ...

    def record_parse_attempt(
        self,
        *,
        source_event_id: int,
        parser_name: str,
        parser_version: str,
        status: str,
        reason: str | None = None,
    ) -> None: ...

    def record_fact(
        self,
        *,
        source_event_id: int,
        candidate: EarningsFactCandidate,
        reason: str,
        status: str = "VALIDATED",
    ) -> StoredEarningsRecord: ...

    def promote_observed_fact(
        self,
        *,
        source_event_id: int,
    ) -> StoredEarningsRecord | None: ...

    def load_validated_facts(
        self,
        *,
        scope_id: str | None = None,
    ) -> Sequence[EarningsFactCandidate]: ...


class DocumentFetcher(Protocol):
    def fetch(self, candidate: EarningsDocumentCandidate) -> bytes: ...


class EarningsParser(Protocol):
    parser_name: str
    parser_version: str

    def parse(
        self,
        document: str | bytes,
        *,
        source: EarningsDocumentCandidate,
        rule: EarningsMarketRule,
        detected_at: datetime,
    ) -> EarningsParseResult: ...


@dataclass(frozen=True)
class _DocumentFetchAttempt:
    document: bytes | None
    route: str | None
    completed_at: datetime
    error: str | None = None


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
        observation_only: bool = False,
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
        self._observation_only = bool(observation_only)
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
        timing = EarningsSourceTiming(
            transport=candidate.transport,
            transport_observed_at=candidate.received_at,
        )
        existing_status = str(stored_event.status or "").upper()
        if (
            not stored_event.created
            and existing_status in self._TERMINAL_EVENT_STATUSES
        ):
            if (
                not self._observation_only
                and existing_status == "PARSED"
                and (rule := self._rules.get(candidate.scope_id))
                is not None
            ):
                promoted = self._store.promote_observed_fact(
                    source_event_id=stored_event.row_id,
                )
                if promoted is not None:
                    signal, reason = self._resolve_signal(rule)
                    if signal is None:
                        return self._finish_without_signal(
                            candidate=candidate,
                            event_id=stored_event.row_id,
                            fact_id=promoted.row_id,
                            status=(
                                ShadowProcessingStatus.QUARANTINED
                            ),
                            reason=reason,
                            timing=timing,
                        )
                    return ShadowProcessingResult(
                        status=ShadowProcessingStatus.SIGNAL,
                        reason="promoted_observation_signal",
                        scope_id=candidate.scope_id,
                        event_id=stored_event.row_id,
                        fact_id=promoted.row_id,
                        signal=signal,
                    )
            if existing_status == "NO_MATCH":
                rule = self._rules.get(candidate.scope_id)
                parser = (
                    self._parsers.get(rule.ticker)
                    if rule is not None
                    else None
                )
                if parser is not None:
                    parser_name, parser_version = _parser_identity(
                        parser
                    )
                    if self._store.claim_no_match_retry(
                        source_event_id=stored_event.row_id,
                        parser_name=parser_name,
                        parser_version=parser_version,
                    ):
                        existing_status = "RECEIVED"
                    else:
                        return ShadowProcessingResult(
                            status=ShadowProcessingStatus.DUPLICATE,
                            reason="parser_version_already_attempted",
                            scope_id=candidate.scope_id,
                            event_id=stored_event.row_id,
                        )
                else:
                    return ShadowProcessingResult(
                        status=ShadowProcessingStatus.DUPLICATE,
                        reason="already_no_match",
                        scope_id=candidate.scope_id,
                        event_id=stored_event.row_id,
                    )
            else:
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
                timing=timing,
            )
        parser = self._parsers.get(rule.ticker)
        if parser is None:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.QUARANTINED,
                reason="company_parser_not_configured",
                timing=timing,
            )
        parser_name, parser_version = _parser_identity(parser)

        fetch_started_at = self._clock()
        fetched = self._fetch_document(candidate)
        timing = replace(
            timing,
            document_fetch_started_at=fetch_started_at,
            document_fetch_completed_at=fetched.completed_at,
            document_fetch_route=fetched.route,
        )
        if fetched.document is None:
            self._store.update_source_event_status(
                stored_event.row_id,
                status="ERROR",
                error=fetched.error or "document_fetch_failed",
                timing=timing,
            )
            return ShadowProcessingResult(
                status=ShadowProcessingStatus.ERROR,
                reason="document_fetch_failed",
                scope_id=candidate.scope_id,
                event_id=stored_event.row_id,
            )
        self._store.update_source_event_status(
            stored_event.row_id,
            status="FETCHED",
            timing=timing,
        )

        parse_started_at = self._clock()
        try:
            parsed = parser.parse(
                fetched.document,
                source=candidate,
                rule=rule,
                detected_at=parse_started_at,
            )
        except Exception as exc:
            timing = replace(
                timing,
                parse_started_at=parse_started_at,
                parse_completed_at=self._clock(),
            )
            error = f"parser_failed:{type(exc).__name__}"
            self._store.record_parse_attempt(
                source_event_id=stored_event.row_id,
                parser_name=parser_name,
                parser_version=parser_version,
                status="ERROR",
                reason=error,
            )
            self._store.update_source_event_status(
                stored_event.row_id,
                status="ERROR",
                error=error,
                timing=timing,
            )
            return ShadowProcessingResult(
                status=ShadowProcessingStatus.ERROR,
                reason=error,
                scope_id=candidate.scope_id,
                event_id=stored_event.row_id,
            )
        parse_completed_at = self._clock()
        timing = replace(
            timing,
            parse_started_at=parse_started_at,
            parse_completed_at=parse_completed_at,
        )

        if parsed.status is ParseStatus.NO_MATCH:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.NO_MATCH,
                reason=parsed.reason,
                timing=timing,
                parser_name=parser_name,
                parser_version=parser_version,
            )
        if parsed.status is ParseStatus.QUARANTINED:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.QUARANTINED,
                reason=parsed.reason,
                timing=timing,
                parser_name=parser_name,
                parser_version=parser_version,
            )
        fact = parsed.candidate
        if fact is None:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                status=ShadowProcessingStatus.ERROR,
                reason="accepted_parse_without_fact",
                timing=timing,
                parser_name=parser_name,
                parser_version=parser_version,
            )
        fact = replace(fact, detected_at=parse_completed_at)
        self._store.record_parse_attempt(
            source_event_id=stored_event.row_id,
            parser_name=parser_name,
            parser_version=parser_version,
            status="ACCEPTED",
            reason=parsed.reason,
        )

        if self._observation_only:
            stored_fact = self._store.record_fact(
                source_event_id=stored_event.row_id,
                candidate=fact,
                reason=parsed.reason,
                status="OBSERVED",
            )
        else:
            stored_fact = self._store.record_fact(
                source_event_id=stored_event.row_id,
                candidate=fact,
                reason=parsed.reason,
            )
        timing = replace(
            timing,
            fact_persisted_at=self._clock(),
        )
        if self._observation_only:
            self._store.update_source_event_status(
                stored_event.row_id,
                status="PARSED",
                timing=timing,
            )
            return ShadowProcessingResult(
                status=ShadowProcessingStatus.OBSERVED,
                reason="observation_tail_fact",
                scope_id=candidate.scope_id,
                event_id=stored_event.row_id,
                fact_id=stored_fact.row_id,
            )
        signal, reason = self._resolve_signal(rule)
        if signal is None:
            return self._finish_without_signal(
                candidate=candidate,
                event_id=stored_event.row_id,
                fact_id=stored_fact.row_id,
                status=ShadowProcessingStatus.QUARANTINED,
                reason=reason,
                timing=timing,
            )
        self._store.update_source_event_status(
            stored_event.row_id,
            status="PARSED",
            timing=timing,
        )
        return ShadowProcessingResult(
            status=ShadowProcessingStatus.SIGNAL,
            reason="shadow_resolution_signal",
            scope_id=candidate.scope_id,
            event_id=stored_event.row_id,
            fact_id=stored_fact.row_id,
            signal=signal,
        )

    def _resolve_signal(
        self,
        rule: EarningsMarketRule,
    ) -> tuple[ResolutionSignal | None, str]:
        resolver = EarningsResolutionSource(
            candidate_provider=lambda: tuple(
                self._store.load_validated_facts(
                    scope_id=rule.scope_id
                )
            ),
            rules=(rule,),
        )
        signals = resolver.poll_once()
        if len(signals) == 1:
            return signals[0], "shadow_resolution_signal"
        return (
            None,
            resolver.quarantine_reasons.get(rule.scope_id)
            or "canonical_signal_not_unique",
        )

    def _fetch_document(
        self,
        candidate: EarningsDocumentCandidate,
    ) -> _DocumentFetchAttempt:
        for attempt in range(1, self._max_fetch_attempts + 1):
            try:
                fetch_with_result = getattr(
                    self._document_fetcher,
                    "fetch_with_result",
                    None,
                )
                if callable(fetch_with_result):
                    result = fetch_with_result(candidate)
                    if not isinstance(
                        result,
                        EarningsDocumentFetchResult,
                    ):
                        raise TypeError(
                            "fetch_with_result returned an invalid result"
                        )
                else:
                    result = EarningsDocumentFetchResult(
                        document=self._document_fetcher.fetch(candidate),
                        route="legacy_fetch",
                    )
                return _DocumentFetchAttempt(
                    document=result.document,
                    route=result.route,
                    completed_at=self._clock(),
                )
            except Exception as exc:
                if attempt >= self._max_fetch_attempts:
                    return _DocumentFetchAttempt(
                        document=None,
                        route=None,
                        completed_at=self._clock(),
                        error=(
                            "document_fetch_failed:"
                            f"{type(exc).__name__}"
                        ),
                    )
                if self._fetch_retry_delay:
                    self._sleep(self._fetch_retry_delay)
        raise AssertionError("fetch attempt loop exited unexpectedly")

    def _finish_without_signal(
        self,
        *,
        candidate: EarningsDocumentCandidate,
        event_id: int,
        status: ShadowProcessingStatus,
        reason: str,
        fact_id: int | None = None,
        timing: EarningsSourceTiming | None = None,
        parser_name: str | None = None,
        parser_version: str | None = None,
    ) -> ShadowProcessingResult:
        database_status = {
            ShadowProcessingStatus.NO_MATCH: "NO_MATCH",
            ShadowProcessingStatus.QUARANTINED: "QUARANTINED",
            ShadowProcessingStatus.ERROR: "ERROR",
        }.get(status)
        if database_status is None:
            raise ValueError("unsupported non-signal status")
        if parser_name is not None or parser_version is not None:
            if parser_name is None or parser_version is None:
                raise ValueError("partial parser identity")
            self._store.record_parse_attempt(
                source_event_id=event_id,
                parser_name=parser_name,
                parser_version=parser_version,
                status=database_status,
                reason=reason,
            )
        self._store.update_source_event_status(
            event_id,
            status=database_status,
            error=reason,
            timing=timing,
        )
        return ShadowProcessingResult(
            status=status,
            reason=reason,
            scope_id=candidate.scope_id,
            event_id=event_id,
            fact_id=fact_id,
        )


def _parser_identity(parser: EarningsParser) -> tuple[str, str]:
    parser_name = str(getattr(parser, "parser_name", "") or "").strip()
    parser_version = str(
        getattr(parser, "parser_version", "") or ""
    ).strip()
    if not parser_name or not parser_version:
        raise ValueError("earnings parser identity is required")
    return parser_name, parser_version
