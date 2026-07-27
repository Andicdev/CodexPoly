from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class EarningsProvider(str, Enum):
    SEC = "sec"
    COMPANY_IR = "company_ir"
    PRESS_RELEASE_RSS = "press_release_rss"
    GLOBE_NEWSWIRE = "globenewswire"
    BUSINESS_WIRE = "businesswire"
    PR_NEWSWIRE = "prnewswire"
    SEEKING_ALPHA = "seeking_alpha"


class SourceAuthority(str, Enum):
    OFFICIAL_COMPANY = "official_company"
    SECONDARY = "secondary"


class EarningsMetric(str, Enum):
    NON_GAAP_EPS = "non_gaap_eps"
    GAAP_EPS = "gaap_eps"


class EpsBasis(str, Enum):
    DILUTED = "diluted"
    BASIC = "basic"
    BASIC_AND_DILUTED = "basic_and_diluted"


class ParseStatus(str, Enum):
    ACCEPTED = "accepted"
    NO_MATCH = "no_match"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class EarningsMarketRule:
    """Resolution semantics known before an earnings publication."""

    rule_key: str
    scope_id: str
    ticker: str
    cik: str
    fiscal_year: int
    fiscal_quarter: int
    period_end: date
    estimated_release_at: datetime
    metric: EarningsMetric
    primary_basis: EpsBasis
    fallback_basis: EpsBasis
    comparison_op: str
    strike: Decimal
    rounding_places: int = 2
    currency: str = "USD"
    market_slug: str | None = None
    condition_id: str | None = None
    source_policy: Mapping[str, Any] = field(default_factory=dict)
    fallback_policy: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rule_key",
            _required_text(self.rule_key, "rule_key"),
        )
        object.__setattr__(
            self,
            "scope_id",
            _required_text(self.scope_id, "scope_id"),
        )
        ticker = _required_text(self.ticker, "ticker").upper()
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "cik", _normalized_cik(self.cik))
        if self.scope_id != earnings_scope_id(
            ticker,
            self.fiscal_year,
            self.fiscal_quarter,
        ):
            raise ValueError("scope_id does not match ticker and fiscal period")
        if not 1 <= int(self.fiscal_quarter) <= 4:
            raise ValueError("fiscal_quarter must be between 1 and 4")
        if self.period_end.year not in {
            int(self.fiscal_year) - 1,
            int(self.fiscal_year),
        }:
            raise ValueError("period_end is inconsistent with fiscal_year")
        object.__setattr__(
            self,
            "estimated_release_at",
            _as_utc(self.estimated_release_at, "estimated_release_at"),
        )
        if not isinstance(self.metric, EarningsMetric):
            raise TypeError("metric must be EarningsMetric")
        if not isinstance(self.primary_basis, EpsBasis):
            raise TypeError("primary_basis must be EpsBasis")
        if not isinstance(self.fallback_basis, EpsBasis):
            raise TypeError("fallback_basis must be EpsBasis")
        if self.comparison_op not in {">", ">=", "<", "<=", "=="}:
            raise ValueError("unsupported comparison_op")
        object.__setattr__(self, "strike", Decimal(str(self.strike)))
        if not 0 <= int(self.rounding_places) <= 6:
            raise ValueError("rounding_places must be between 0 and 6")
        object.__setattr__(
            self,
            "currency",
            _required_text(self.currency, "currency").upper(),
        )
        object.__setattr__(
            self,
            "market_slug",
            _optional_text(self.market_slug),
        )
        object.__setattr__(
            self,
            "condition_id",
            _optional_text(self.condition_id),
        )
        object.__setattr__(
            self,
            "source_policy",
            MappingProxyType(dict(self.source_policy)),
        )
        object.__setattr__(
            self,
            "fallback_policy",
            MappingProxyType(dict(self.fallback_policy)),
        )


@dataclass(frozen=True)
class EarningsDocumentCandidate:
    """Normalized document metadata emitted by an upstream transport."""

    scope_id: str
    provider: EarningsProvider
    provider_event_id: str
    ticker: str
    cik: str
    form_type: str
    items: tuple[str, ...]
    document_type: str
    source_url: str
    filing_url: str
    filed_at: datetime
    received_at: datetime
    authority: SourceAuthority
    transport_fingerprint: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_id",
            _required_text(self.scope_id, "scope_id"),
        )
        if not isinstance(self.provider, EarningsProvider):
            raise TypeError("provider must be EarningsProvider")
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
        items = tuple(
            normalized
            for item in self.items
            if (normalized := str(item or "").strip())
        )
        object.__setattr__(self, "items", items)
        object.__setattr__(
            self,
            "document_type",
            _required_text(self.document_type, "document_type").upper(),
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
        if not isinstance(self.authority, SourceAuthority):
            raise TypeError("authority must be SourceAuthority")
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
class EarningsFactCandidate:
    """Validated EPS fact that may be promoted to a resolution signal."""

    scope_id: str
    provider: EarningsProvider
    provider_event_id: str
    ticker: str
    cik: str
    period_end: date
    metric: EarningsMetric
    basis: EpsBasis
    currency: str
    raw_value: Decimal
    value: Decimal
    authority: SourceAuthority
    source_url: str
    filing_url: str
    published_at: datetime
    detected_at: datetime
    parser_name: str
    parser_version: str
    confidence: Decimal
    document_fingerprint: str
    evidence_title: str | None = None
    excerpt: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_id",
            _required_text(self.scope_id, "scope_id"),
        )
        if not isinstance(self.provider, EarningsProvider):
            raise TypeError("provider must be EarningsProvider")
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
        if not isinstance(self.metric, EarningsMetric):
            raise TypeError("metric must be EarningsMetric")
        if not isinstance(self.basis, EpsBasis):
            raise TypeError("basis must be EpsBasis")
        object.__setattr__(
            self,
            "currency",
            _required_text(self.currency, "currency").upper(),
        )
        object.__setattr__(
            self,
            "raw_value",
            Decimal(str(self.raw_value)),
        )
        object.__setattr__(self, "value", Decimal(str(self.value)))
        if not isinstance(self.authority, SourceAuthority):
            raise TypeError("authority must be SourceAuthority")
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
        confidence = Decimal(str(self.confidence))
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "document_fingerprint",
            _required_text(
                self.document_fingerprint,
                "document_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "evidence_title",
            _optional_text(self.evidence_title),
        )
        object.__setattr__(self, "excerpt", _optional_text(self.excerpt))
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(self.attributes)),
        )


@dataclass(frozen=True)
class EarningsParseResult:
    status: ParseStatus
    reason: str
    candidate: EarningsFactCandidate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ParseStatus):
            raise TypeError("status must be ParseStatus")
        object.__setattr__(
            self,
            "reason",
            _required_text(self.reason, "reason"),
        )
        if self.status is ParseStatus.ACCEPTED:
            if not isinstance(self.candidate, EarningsFactCandidate):
                raise ValueError("accepted parse result requires candidate")
        elif self.candidate is not None:
            raise ValueError("non-accepted parse result cannot have candidate")


def earnings_scope_id(
    ticker: str,
    fiscal_year: int,
    fiscal_quarter: int,
) -> str:
    normalized_ticker = _required_text(ticker, "ticker").upper()
    quarter = int(fiscal_quarter)
    if quarter not in {1, 2, 3, 4}:
        raise ValueError("fiscal_quarter must be between 1 and 4")
    return f"earnings:{normalized_ticker}:{int(fiscal_year)}Q{quarter}"


def _normalized_cik(value: str | int) -> str:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        raise ValueError("cik must contain only digits")
    return normalized.lstrip("0") or "0"


def _required_text(value: object, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _optional_text(value: object | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _required_https_url(value: object, name: str) -> str:
    normalized = _required_text(value, name)
    if not normalized.lower().startswith("https://"):
        raise ValueError(f"{name} must use https")
    return normalized


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
