from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class MstrBtcProvider(str, Enum):
    SEC = "sec"
    STRATEGY_LEDGER = "strategy_ledger"


class MstrBtcParseStatus(str, Enum):
    ACCEPTED = "accepted"
    NO_MATCH = "no_match"
    QUARANTINED = "quarantined"


class MstrBtcValueDerivation(str, Enum):
    EXPLICIT = "explicit"
    HOLDINGS_DELTA = "holdings_delta"
    NOT_CONFIRMED = "not_confirmed"


class MstrBtcHoldingsValidationStatus(str, Enum):
    VALIDATED = "VALIDATED"
    QUARANTINED = "QUARANTINED"


@dataclass(frozen=True)
class MstrBtcHoldingsObservation:
    """Append-only holdings observation before it receives a database id."""

    holdings_btc: int
    as_of: datetime
    observed_at: datetime
    provider: MstrBtcProvider
    provider_event_id: str
    source_url: str
    document_fingerprint: str
    validation_status: MstrBtcHoldingsValidationStatus
    predecessor_state_id: int | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "holdings_btc",
            _non_negative_int(self.holdings_btc, "holdings_btc"),
        )
        as_of = _as_utc(self.as_of, "as_of")
        observed_at = _as_utc(self.observed_at, "observed_at")
        if as_of > observed_at:
            raise ValueError("as_of cannot be later than observed_at")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "observed_at", observed_at)
        if not isinstance(self.provider, MstrBtcProvider):
            raise TypeError("provider must be MstrBtcProvider")
        object.__setattr__(
            self,
            "provider_event_id",
            _required_text(self.provider_event_id, "provider_event_id"),
        )
        object.__setattr__(
            self,
            "source_url",
            _required_https_url(self.source_url, "source_url"),
        )
        object.__setattr__(
            self,
            "document_fingerprint",
            _required_text(
                self.document_fingerprint,
                "document_fingerprint",
            ),
        )
        if not isinstance(
            self.validation_status,
            MstrBtcHoldingsValidationStatus,
        ):
            raise TypeError(
                "validation_status must be "
                "MstrBtcHoldingsValidationStatus"
            )
        if self.predecessor_state_id is not None:
            predecessor = _int_value(
                self.predecessor_state_id,
                "predecessor_state_id",
            )
            if predecessor < 1:
                raise ValueError(
                    "predecessor_state_id must be positive"
                )
            object.__setattr__(
                self,
                "predecessor_state_id",
                predecessor,
            )
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(self.attributes)),
        )


@dataclass(frozen=True)
class MstrBtcHoldingsBaseline:
    """Immutable holdings state pinned before an announcement window."""

    state_id: str
    holdings_btc: int
    as_of: datetime
    provider: MstrBtcProvider
    provider_event_id: str
    source_url: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state_id",
            _required_text(self.state_id, "state_id"),
        )
        object.__setattr__(
            self,
            "holdings_btc",
            _non_negative_int(self.holdings_btc, "holdings_btc"),
        )
        object.__setattr__(self, "as_of", _as_utc(self.as_of, "as_of"))
        if not isinstance(self.provider, MstrBtcProvider):
            raise TypeError("provider must be MstrBtcProvider")
        object.__setattr__(
            self,
            "provider_event_id",
            _required_text(self.provider_event_id, "provider_event_id"),
        )
        object.__setattr__(
            self,
            "source_url",
            _required_https_url(self.source_url, "source_url"),
        )


@dataclass(frozen=True)
class MstrBtcDocumentCandidate:
    """Normalized MSTR document emitted by a shared source transport."""

    scope_id: str
    provider: MstrBtcProvider
    provider_event_id: str
    ticker: str
    cik: str
    form_type: str
    source_url: str
    filing_url: str
    filed_at: datetime
    received_at: datetime
    transport_fingerprint: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_id",
            _required_text(self.scope_id, "scope_id"),
        )
        if not isinstance(self.provider, MstrBtcProvider):
            raise TypeError("provider must be MstrBtcProvider")
        object.__setattr__(
            self,
            "provider_event_id",
            _required_text(self.provider_event_id, "provider_event_id"),
        )
        object.__setattr__(
            self,
            "ticker",
            _required_text(self.ticker, "ticker").upper(),
        )
        object.__setattr__(self, "cik", _normalized_cik(self.cik))
        object.__setattr__(
            self,
            "form_type",
            _required_text(self.form_type, "form_type").upper(),
        )
        object.__setattr__(
            self,
            "source_url",
            _required_https_url(self.source_url, "source_url"),
        )
        object.__setattr__(
            self,
            "filing_url",
            _required_https_url(self.filing_url, "filing_url"),
        )
        object.__setattr__(
            self,
            "filed_at",
            _as_utc(self.filed_at, "filed_at"),
        )
        object.__setattr__(
            self,
            "received_at",
            _as_utc(self.received_at, "received_at"),
        )
        object.__setattr__(
            self,
            "transport_fingerprint",
            _required_text(
                self.transport_fingerprint,
                "transport_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True)
class MstrBtcFactCandidate:
    """A holdings-first fact extracted from an official BTC update."""

    scope_id: str
    provider: MstrBtcProvider
    provider_event_id: str
    baseline_state_id: str
    holdings_before_btc: int
    holdings_after_btc: int
    net_change_btc: int
    acquired_btc: int | None
    sold_btc: int | None
    acquired_derivation: MstrBtcValueDerivation
    sold_derivation: MstrBtcValueDerivation
    holdings_crosscheck_difference_btc: int
    source_url: str
    filing_url: str
    published_at: datetime
    detected_at: datetime
    parser_name: str
    parser_version: str
    document_fingerprint: str
    evidence_excerpts: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_id",
            _required_text(self.scope_id, "scope_id"),
        )
        if not isinstance(self.provider, MstrBtcProvider):
            raise TypeError("provider must be MstrBtcProvider")
        object.__setattr__(
            self,
            "provider_event_id",
            _required_text(self.provider_event_id, "provider_event_id"),
        )
        object.__setattr__(
            self,
            "baseline_state_id",
            _required_text(self.baseline_state_id, "baseline_state_id"),
        )
        before = _non_negative_int(
            self.holdings_before_btc,
            "holdings_before_btc",
        )
        after = _non_negative_int(
            self.holdings_after_btc,
            "holdings_after_btc",
        )
        object.__setattr__(self, "holdings_before_btc", before)
        object.__setattr__(self, "holdings_after_btc", after)
        net_change = _int_value(self.net_change_btc, "net_change_btc")
        if net_change != after - before:
            raise ValueError(
                "net_change_btc must equal holdings_after_btc "
                "minus holdings_before_btc"
            )
        object.__setattr__(self, "net_change_btc", net_change)
        object.__setattr__(
            self,
            "acquired_btc",
            _optional_non_negative_int(self.acquired_btc, "acquired_btc"),
        )
        object.__setattr__(
            self,
            "sold_btc",
            _optional_non_negative_int(self.sold_btc, "sold_btc"),
        )
        _validate_derivation(
            self.acquired_btc,
            self.acquired_derivation,
            "acquired",
        )
        _validate_derivation(
            self.sold_btc,
            self.sold_derivation,
            "sold",
        )
        object.__setattr__(
            self,
            "holdings_crosscheck_difference_btc",
            _int_value(
                self.holdings_crosscheck_difference_btc,
                "holdings_crosscheck_difference_btc",
            ),
        )
        object.__setattr__(
            self,
            "source_url",
            _required_https_url(self.source_url, "source_url"),
        )
        object.__setattr__(
            self,
            "filing_url",
            _required_https_url(self.filing_url, "filing_url"),
        )
        object.__setattr__(
            self,
            "published_at",
            _as_utc(self.published_at, "published_at"),
        )
        object.__setattr__(
            self,
            "detected_at",
            _as_utc(self.detected_at, "detected_at"),
        )
        object.__setattr__(
            self,
            "parser_name",
            _required_text(self.parser_name, "parser_name"),
        )
        object.__setattr__(
            self,
            "parser_version",
            _required_text(self.parser_version, "parser_version"),
        )
        object.__setattr__(
            self,
            "document_fingerprint",
            _required_text(
                self.document_fingerprint,
                "document_fingerprint",
            ),
        )
        excerpts = tuple(
            excerpt
            for value in self.evidence_excerpts
            if (excerpt := str(value or "").strip())
        )
        object.__setattr__(self, "evidence_excerpts", excerpts)
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(self.attributes)),
        )


@dataclass(frozen=True)
class MstrBtcParseResult:
    status: MstrBtcParseStatus
    reason: str
    candidate: MstrBtcFactCandidate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, MstrBtcParseStatus):
            raise TypeError("status must be MstrBtcParseStatus")
        object.__setattr__(
            self,
            "reason",
            _required_text(self.reason, "reason"),
        )
        if self.status is MstrBtcParseStatus.ACCEPTED:
            if not isinstance(self.candidate, MstrBtcFactCandidate):
                raise ValueError("accepted parse result requires candidate")
        elif self.candidate is not None:
            raise ValueError("non-accepted parse result cannot have candidate")


def _validate_derivation(
    value: int | None,
    derivation: MstrBtcValueDerivation,
    name: str,
) -> None:
    if not isinstance(derivation, MstrBtcValueDerivation):
        raise TypeError(f"{name}_derivation must be MstrBtcValueDerivation")
    if value is None and derivation is not MstrBtcValueDerivation.NOT_CONFIRMED:
        raise ValueError(
            f"{name}_derivation must be not_confirmed when value is absent"
        )
    if value is not None and derivation is MstrBtcValueDerivation.NOT_CONFIRMED:
        raise ValueError(
            f"{name}_derivation cannot be not_confirmed when value is present"
        )


def _required_text(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _required_https_url(value: object, name: str) -> str:
    normalized = _required_text(value, name)
    if not normalized.lower().startswith("https://"):
        raise ValueError(f"{name} must use https")
    return normalized


def _normalized_cik(value: str | int) -> str:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        raise ValueError("cik must contain only digits")
    return normalized.lstrip("0") or "0"


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _int_value(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _non_negative_int(value: object, name: str) -> int:
    parsed = _int_value(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


def _optional_non_negative_int(
    value: object | None,
    name: str,
) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, name)
