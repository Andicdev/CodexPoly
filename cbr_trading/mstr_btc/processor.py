from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from cbr_trading.mstr_btc.contracts import (
    MstrBtcDocumentCandidate,
    MstrBtcFactCandidate,
    MstrBtcHoldingsBaseline,
    MstrBtcParseStatus,
)
from cbr_trading.mstr_btc.parser import MstrBtc8KParser
from cbr_trading.mstr_btc.sec_router import MstrBtcSecWatch


class MstrBtcShadowStatus(str, Enum):
    ACCEPTED = "accepted"
    NO_MATCH = "no_match"
    QUARANTINED = "quarantined"
    ERROR = "error"


@dataclass(frozen=True)
class MstrBtcShadowResult:
    status: MstrBtcShadowStatus
    reason: str
    scope_id: str
    baseline_state_id: str | None = None
    fact: MstrBtcFactCandidate | None = None

    def __post_init__(self) -> None:
        if (
            self.status is MstrBtcShadowStatus.ACCEPTED
        ) != isinstance(self.fact, MstrBtcFactCandidate):
            raise ValueError("accepted status and fact disagree")


class MstrBtcBaselineStore(Protocol):
    def pin_baseline(
        self,
        *,
        before: datetime,
    ) -> MstrBtcHoldingsBaseline: ...


class MstrBtcDocumentFetcher(Protocol):
    def fetch(self, candidate: MstrBtcDocumentCandidate) -> bytes: ...


class MstrBtcShadowProcessor:
    """Fetch and parse MSTR filings against an immutable pre-window baseline."""

    def __init__(
        self,
        *,
        store: MstrBtcBaselineStore,
        watch: MstrBtcSecWatch,
        document_fetcher: MstrBtcDocumentFetcher,
        parser: MstrBtc8KParser | None = None,
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
        self._watch = watch
        self._document_fetcher = document_fetcher
        self._parser = parser or MstrBtc8KParser()
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
            baseline = self._store.pin_baseline(
                before=self._watch.window_start,
            )
        except Exception as exc:
            return self._result(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"baseline_pin_failed:{type(exc).__name__}",
            )
        document = self._fetch_document(candidate)
        if document is None:
            return self._result(
                candidate,
                MstrBtcShadowStatus.ERROR,
                "document_fetch_failed",
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
            return self._result(
                candidate,
                MstrBtcShadowStatus.ERROR,
                f"parser_failed:{type(exc).__name__}",
                baseline=baseline,
            )
        if parsed.status is MstrBtcParseStatus.NO_MATCH:
            return self._result(
                candidate,
                MstrBtcShadowStatus.NO_MATCH,
                parsed.reason,
                baseline=baseline,
            )
        if parsed.status is MstrBtcParseStatus.QUARANTINED:
            return self._result(
                candidate,
                MstrBtcShadowStatus.QUARANTINED,
                parsed.reason,
                baseline=baseline,
            )
        if parsed.candidate is None:
            return self._result(
                candidate,
                MstrBtcShadowStatus.ERROR,
                "accepted_parse_without_fact",
                baseline=baseline,
            )
        return MstrBtcShadowResult(
            status=MstrBtcShadowStatus.ACCEPTED,
            reason=parsed.reason,
            scope_id=candidate.scope_id,
            baseline_state_id=baseline.state_id,
            fact=parsed.candidate,
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
        )
