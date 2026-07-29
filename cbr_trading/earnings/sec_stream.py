from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    EarningsTransport,
    SourceAuthority,
)
from cbr_trading.sec_filings.contracts import (
    SecDocumentReference,
    SecFilingEnvelope,
    normalize_sec_filing,
)
from cbr_trading.sec_filings.stream import (
    SEC_STREAM_ENDPOINT,
    ConnectFactory,
    SecStreamTransport,
    SecStreamTransportError,
    _stream_error_code,
    decode_sec_stream_message,
)


@dataclass(frozen=True)
class SecEarningsWatch:
    scope_id: str
    ticker: str
    cik: str

    def __post_init__(self) -> None:
        scope_id = str(self.scope_id or "").strip()
        ticker = str(self.ticker or "").strip().upper()
        cik = _normalize_cik(self.cik)
        if not scope_id:
            raise ValueError("scope_id is required")
        if not ticker:
            raise ValueError("ticker is required")
        object.__setattr__(self, "scope_id", scope_id)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "cik", cik)


@dataclass(frozen=True)
class SecFilingDecision:
    accepted: bool
    reason: str
    candidate: EarningsDocumentCandidate | None = None

    def __post_init__(self) -> None:
        reason = str(self.reason or "").strip()
        if not reason:
            raise ValueError("reason is required")
        object.__setattr__(self, "reason", reason)
        if self.accepted != isinstance(
            self.candidate,
            EarningsDocumentCandidate,
        ):
            raise ValueError("accepted decision and candidate disagree")


class SecStreamFilingRouter:
    """Route normalized initial earnings 8-K exhibits to event scopes."""

    def __init__(self, watches: Sequence[SecEarningsWatch]):
        rows = tuple(watches)
        if not rows:
            raise ValueError("at least one SEC earnings watch is required")
        scope_ids = [row.scope_id for row in rows]
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("SEC earnings watch scope_ids must be unique")
        self._watches = rows

    def route(
        self,
        filing: Mapping[str, Any] | SecFilingEnvelope,
        *,
        received_at: datetime | None = None,
    ) -> tuple[SecFilingDecision, ...]:
        envelope = _as_envelope(filing, received_at=received_at)
        matching = tuple(
            watch
            for watch in self._watches
            if (
                (
                    envelope.ticker
                    and envelope.ticker == watch.ticker
                )
                or (envelope.cik and envelope.cik == watch.cik)
            )
        )
        if not matching:
            return (SecFilingDecision(False, "unwatched_issuer"),)
        return tuple(
            evaluate_sec_earnings_filing(
                envelope,
                watch=watch,
            )
            for watch in matching
        )


class SecStreamEarningsTransport:
    """Compatibility adapter over the source-neutral SEC transport."""

    def __init__(
        self,
        *,
        api_key: str,
        watches: Sequence[SecEarningsWatch],
        connect_factory: ConnectFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._transport = SecStreamTransport(
            api_key=api_key,
            connect_factory=connect_factory,
            clock=clock,
        )
        self._router = SecStreamFilingRouter(watches)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            "credential=[REDACTED], source_neutral=True)"
        )

    async def stream_once(
        self,
    ) -> AsyncIterator[EarningsDocumentCandidate]:
        async for envelope in self._transport.stream_once():
            for decision in self._router.route(envelope):
                if decision.candidate is not None:
                    yield decision.candidate


def evaluate_sec_earnings_filing(
    filing: Mapping[str, Any] | SecFilingEnvelope,
    *,
    watch: SecEarningsWatch,
    received_at: datetime | None = None,
) -> SecFilingDecision:
    envelope = _as_envelope(filing, received_at=received_at)
    if not envelope.cik:
        return SecFilingDecision(False, "cik_missing")
    if envelope.ticker and envelope.ticker != watch.ticker:
        return SecFilingDecision(False, "ticker_mismatch")
    if envelope.cik != watch.cik:
        return SecFilingDecision(False, "cik_mismatch")

    if envelope.form_type != "8-K":
        return SecFilingDecision(False, "not_initial_8k")
    if not _has_item_202(
        envelope.items,
        envelope.description or "",
    ):
        return SecFilingDecision(False, "item_202_missing")
    if not envelope.accession:
        return SecFilingDecision(False, "accession_missing")
    if not _is_https_url(envelope.filing_url):
        return SecFilingDecision(False, "filing_url_missing")

    exhibits = tuple(
        document
        for document in envelope.documents
        if document.document_type == "EX-99.1"
    )
    if not exhibits:
        return SecFilingDecision(False, "exhibit_991_missing")
    if len(exhibits) > 1:
        return SecFilingDecision(False, "exhibit_991_ambiguous")
    exhibit = exhibits[0]
    if not _is_https_url(exhibit.document_url):
        return SecFilingDecision(False, "exhibit_url_missing")
    if envelope.filed_at is None:
        return SecFilingDecision(False, "filed_at_invalid")

    fingerprint = hashlib.sha256(
        (
            f"{EarningsProvider.SEC.value}|{watch.scope_id}|"
            f"{envelope.accession}|{exhibit.document_url}"
        ).encode("utf-8")
    ).hexdigest()
    metadata = {
        **dict(envelope.metadata),
        "company_name": envelope.company_name,
        "description": envelope.description,
        "exhibit_description": exhibit.description,
        "exhibit_sequence": exhibit.sequence,
    }
    transport_value = str(
        envelope.metadata.get("transport") or ""
    ).strip()
    try:
        transport = EarningsTransport(transport_value)
    except ValueError:
        transport = EarningsTransport.LEGACY_UNKNOWN
    candidate = EarningsDocumentCandidate(
        scope_id=watch.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=envelope.accession,
        ticker=watch.ticker,
        cik=watch.cik,
        form_type=envelope.form_type,
        items=envelope.items,
        document_type="EX-99.1",
        source_url=exhibit.document_url,
        filing_url=envelope.filing_url or "",
        filed_at=envelope.filed_at,
        received_at=envelope.received_at,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint=fingerprint,
        transport=transport,
        metadata={
            key: value
            for key, value in metadata.items()
            if value is not None
        },
    )
    return SecFilingDecision(
        True,
        "official_earnings_exhibit",
        candidate,
    )


def _as_envelope(
    filing: Mapping[str, Any] | SecFilingEnvelope,
    *,
    received_at: datetime | None,
) -> SecFilingEnvelope:
    if isinstance(filing, SecFilingEnvelope):
        return filing
    if received_at is None:
        raise ValueError(
            "received_at is required for unnormalized SEC filings"
        )
    return normalize_sec_filing(
        filing,
        received_at=_as_utc(received_at),
    )


def _has_item_202(
    items: Sequence[str],
    description: str,
) -> bool:
    values = tuple(items) + (description,)
    return any(
        "item 2.02" in str(value).casefold()
        for value in values
    )


def _normalize_cik(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        raise ValueError("cik must contain only digits")
    return normalized.lstrip("0") or "0"


def _is_https_url(value: str | None) -> bool:
    return str(value or "").lower().startswith("https://")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "SEC_STREAM_ENDPOINT",
    "SecDocumentReference",
    "SecEarningsWatch",
    "SecFilingDecision",
    "SecStreamEarningsTransport",
    "SecStreamFilingRouter",
    "SecStreamTransportError",
    "_stream_error_code",
    "decode_sec_stream_message",
    "evaluate_sec_earnings_filing",
]
