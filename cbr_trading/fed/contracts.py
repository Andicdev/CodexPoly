from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum


class FedRateBucket(str, Enum):
    DECREASE_50_PLUS = "decrease_50_plus"
    DECREASE_25 = "decrease_25"
    NO_CHANGE = "no_change"
    INCREASE_25 = "increase_25"
    INCREASE_50_PLUS = "increase_50_plus"


@dataclass(frozen=True)
class FedDecisionSpec:
    """One scheduled FOMC decision and its pre-decision baseline."""

    decision_id: str
    release_at: datetime
    previous_lower: Decimal
    previous_upper: Decimal
    board_statement_url: str
    board_statement_pdf_url: str
    board_implementation_url: str
    new_york_fed_pdf_url: str
    monetary_policy_rss_url: str

    def __post_init__(self) -> None:
        decision_id = str(self.decision_id or "").strip()
        if not decision_id:
            raise ValueError("decision_id is required")
        object.__setattr__(self, "decision_id", decision_id)
        release_at = self.release_at
        if release_at.tzinfo is None or release_at.utcoffset() is None:
            raise ValueError("release_at must be timezone-aware")
        object.__setattr__(
            self,
            "release_at",
            release_at.astimezone(timezone.utc),
        )
        lower = _rate(self.previous_lower, "previous_lower")
        upper = _rate(self.previous_upper, "previous_upper")
        if upper < lower:
            raise ValueError("previous_upper cannot be below previous_lower")
        object.__setattr__(self, "previous_lower", lower)
        object.__setattr__(self, "previous_upper", upper)
        for name in (
            "board_statement_url",
            "board_statement_pdf_url",
            "board_implementation_url",
            "new_york_fed_pdf_url",
            "monetary_policy_rss_url",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value.startswith("https://"):
                raise ValueError(f"{name} must use HTTPS")
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class FedRateDecision:
    """Canonical target range parsed from an official FOMC document."""

    lower: Decimal
    upper: Decimal

    def __post_init__(self) -> None:
        lower = _rate(self.lower, "lower")
        upper = _rate(self.upper, "upper")
        if upper < lower:
            raise ValueError("upper cannot be below lower")
        if upper - lower > Decimal("5"):
            raise ValueError("target range width is implausible")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)


@dataclass(frozen=True)
class FedMarketBinding:
    """One Polymarket binary market bound to a normalized rate bucket."""

    rule_key: str
    scope_id: str
    bucket: FedRateBucket
    comparison_op: str
    strike_bps: Decimal
    market_slug: str
    condition_id: str
    source_reference: str

    def __post_init__(self) -> None:
        for name in (
            "rule_key",
            "scope_id",
            "market_slug",
            "condition_id",
            "source_reference",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        if self.comparison_op not in {"==", ">=", "<="}:
            raise ValueError("unsupported comparison_op")
        strike = Decimal(str(self.strike_bps))
        if not strike.is_finite():
            raise ValueError("strike_bps must be finite")
        object.__setattr__(self, "strike_bps", strike)
        if not self.condition_id.startswith("0x"):
            raise ValueError("condition_id must be a hex identifier")
        if not self.source_reference.startswith("https://"):
            raise ValueError("source_reference must use HTTPS")


def _rate(value: Decimal, name: str) -> Decimal:
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed < 0 or parsed > 25:
        raise ValueError(f"{name} must be a plausible percentage rate")
    return parsed
