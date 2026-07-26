from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cbr_trading.mstr_btc.contracts import (
    MstrBtcDocumentCandidate,
    MstrBtcProvider,
)
from cbr_trading.mstr_btc.parser import MSTR_CIK, MSTR_TICKER
from cbr_trading.sec_filings.contracts import (
    SecFilingEnvelope,
    normalize_sec_filing,
)


MSTR_JUL21_27_SCOPE_ID = "mstr-btc:2026-07-21:2026-07-27"
MSTR_JUL21_27_WINDOW_START = datetime(
    2026,
    7,
    21,
    4,
    tzinfo=timezone.utc,
)
MSTR_JUL21_27_WINDOW_END = datetime(
    2026,
    7,
    28,
    4,
    tzinfo=timezone.utc,
)


@dataclass(frozen=True)
class MstrBtcSecWatch:
    scope_id: str
    ticker: str
    cik: str
    window_start: datetime
    window_end: datetime

    def __post_init__(self) -> None:
        scope_id = str(self.scope_id or "").strip()
        ticker = str(self.ticker or "").strip().upper()
        cik = _normalize_cik(self.cik)
        window_start = _as_utc(self.window_start, "window_start")
        window_end = _as_utc(self.window_end, "window_end")
        if not scope_id:
            raise ValueError("scope_id is required")
        if not ticker:
            raise ValueError("ticker is required")
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")
        object.__setattr__(self, "scope_id", scope_id)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "cik", cik)
        object.__setattr__(self, "window_start", window_start)
        object.__setattr__(self, "window_end", window_end)


@dataclass(frozen=True)
class MstrBtcFilingDecision:
    accepted: bool
    reason: str
    candidate: MstrBtcDocumentCandidate | None = None

    def __post_init__(self) -> None:
        reason = str(self.reason or "").strip()
        if not reason:
            raise ValueError("reason is required")
        object.__setattr__(self, "reason", reason)
        if self.accepted != isinstance(
            self.candidate,
            MstrBtcDocumentCandidate,
        ):
            raise ValueError("accepted decision and candidate disagree")


class MstrBtcRouter:
    """Route MSTR initial 8-K primary documents for one weekly scope."""

    def __init__(self, watch: MstrBtcSecWatch):
        self.watch = watch

    def route(
        self,
        filing: Mapping[str, Any] | SecFilingEnvelope,
        *,
        received_at: datetime | None = None,
    ) -> MstrBtcFilingDecision:
        return evaluate_mstr_btc_filing(
            filing,
            watch=self.watch,
            received_at=received_at,
        )


def mstr_jul21_27_shadow_watch() -> MstrBtcSecWatch:
    return MstrBtcSecWatch(
        scope_id=MSTR_JUL21_27_SCOPE_ID,
        ticker=MSTR_TICKER,
        cik=MSTR_CIK,
        window_start=MSTR_JUL21_27_WINDOW_START,
        window_end=MSTR_JUL21_27_WINDOW_END,
    )


def evaluate_mstr_btc_filing(
    filing: Mapping[str, Any] | SecFilingEnvelope,
    *,
    watch: MstrBtcSecWatch,
    received_at: datetime | None = None,
) -> MstrBtcFilingDecision:
    envelope = _as_envelope(filing, received_at=received_at)
    if not envelope.cik:
        return MstrBtcFilingDecision(False, "cik_missing")
    if envelope.ticker and envelope.ticker != watch.ticker:
        return MstrBtcFilingDecision(False, "ticker_mismatch")
    if envelope.cik != watch.cik:
        return MstrBtcFilingDecision(False, "cik_mismatch")
    if envelope.form_type != "8-K":
        return MstrBtcFilingDecision(False, "not_initial_8k")
    if envelope.filed_at is None:
        return MstrBtcFilingDecision(False, "filed_at_invalid")
    if not (
        watch.window_start
        <= envelope.filed_at
        < watch.window_end
    ):
        return MstrBtcFilingDecision(False, "outside_event_window")
    if not envelope.accession:
        return MstrBtcFilingDecision(False, "accession_missing")
    if not _is_https_url(envelope.filing_url):
        return MstrBtcFilingDecision(False, "filing_url_missing")

    primary_documents = tuple(
        document
        for document in envelope.documents
        if document.document_type == "8-K"
    )
    if not primary_documents:
        return MstrBtcFilingDecision(
            False,
            "primary_8k_document_missing",
        )
    if len(primary_documents) > 1:
        return MstrBtcFilingDecision(
            False,
            "primary_8k_document_ambiguous",
        )
    primary = primary_documents[0]
    if not _is_https_url(primary.document_url):
        return MstrBtcFilingDecision(
            False,
            "primary_8k_url_missing",
        )

    fingerprint = hashlib.sha256(
        (
            f"{MstrBtcProvider.SEC.value}|{watch.scope_id}|"
            f"{envelope.accession}|{primary.document_url}"
        ).encode("utf-8")
    ).hexdigest()
    metadata = {
        "company_name": envelope.company_name,
        "description": envelope.description,
        "document_description": primary.description,
        "document_sequence": primary.sequence,
        "items": envelope.items,
    }
    return MstrBtcFilingDecision(
        True,
        "official_mstr_initial_8k",
        MstrBtcDocumentCandidate(
            scope_id=watch.scope_id,
            provider=MstrBtcProvider.SEC,
            provider_event_id=envelope.accession,
            ticker=watch.ticker,
            cik=watch.cik,
            form_type=envelope.form_type,
            source_url=primary.document_url,
            filing_url=envelope.filing_url or "",
            filed_at=envelope.filed_at,
            received_at=envelope.received_at,
            transport_fingerprint=fingerprint,
            metadata={
                key: value
                for key, value in metadata.items()
                if value is not None
            },
        ),
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
        received_at=_as_utc(received_at, "received_at"),
    )


def _normalize_cik(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        raise ValueError("cik must contain only digits")
    return normalized.lstrip("0") or "0"


def _is_https_url(value: str | None) -> bool:
    return str(value or "").lower().startswith("https://")


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
