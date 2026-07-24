from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias


SignalValue: TypeAlias = Decimal | str | bool


@dataclass(frozen=True)
class SignalEvidence:
    """Auditable evidence supporting a resolution signal."""

    source_url: str
    title: str | None = None
    fingerprint: str | None = None
    excerpt: str | None = None

    def __post_init__(self) -> None:
        source_url = self.source_url.strip()
        if not source_url:
            raise ValueError("source_url is required")
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "title", _optional_text(self.title))
        object.__setattr__(self, "fingerprint", _optional_text(self.fingerprint))
        object.__setattr__(self, "excerpt", _optional_text(self.excerpt))


@dataclass(frozen=True)
class ResolutionSignal:
    """Source-neutral fact that can be evaluated by one or more strategies."""

    signal_id: str
    source: str
    subject: str
    metric: str
    value: SignalValue
    detected_at: datetime
    published_at: datetime | None = None
    previous_value: SignalValue | None = None
    unit: str | None = None
    direction: str | None = None
    confidence: Decimal = Decimal("1")
    evidence: tuple[SignalEvidence, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "signal_id", _required_text(self.signal_id, "signal_id"))
        object.__setattr__(self, "source", _required_text(self.source, "source"))
        object.__setattr__(self, "subject", _required_text(self.subject, "subject"))
        object.__setattr__(self, "metric", _required_text(self.metric, "metric"))
        object.__setattr__(self, "detected_at", _as_utc(self.detected_at, "detected_at"))
        if self.published_at is not None:
            object.__setattr__(
                self,
                "published_at",
                _as_utc(self.published_at, "published_at"),
            )

        confidence = Decimal(str(self.confidence))
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)

        _validate_signal_value(self.value, "value")
        if self.previous_value is not None:
            _validate_signal_value(self.previous_value, "previous_value")

        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")

        object.__setattr__(self, "unit", _optional_text(self.unit))
        object.__setattr__(self, "direction", _optional_text(self.direction))
        evidence = tuple(self.evidence)
        if any(not isinstance(item, SignalEvidence) for item in evidence):
            raise TypeError("evidence must contain only SignalEvidence objects")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(self.attributes)),
        )


def _required_text(value: str, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _optional_text(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _validate_signal_value(value: SignalValue, name: str) -> None:
    if not isinstance(value, (Decimal, str, bool)):
        raise TypeError(f"{name} must be Decimal, str, or bool")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"string {name} must not be empty")


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
