from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class SecDocumentReference:
    """One document listed in an SEC filing event."""

    document_type: str
    document_url: str
    description: str | None = None
    sequence: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "document_type",
            str(self.document_type or "").strip().upper(),
        )
        object.__setattr__(
            self,
            "document_url",
            str(self.document_url or "").strip(),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description),
        )
        object.__setattr__(
            self,
            "sequence",
            _optional_text(self.sequence),
        )


@dataclass(frozen=True)
class SecFilingEnvelope:
    """Transport-level SEC metadata before business-specific routing."""

    ticker: str | None
    cik: str | None
    company_name: str | None
    accession: str | None
    form_type: str | None
    filed_at: datetime | None
    received_at: datetime
    items: tuple[str, ...]
    description: str | None
    filing_url: str | None
    documents: tuple[SecDocumentReference, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ticker",
            (
                normalized.upper()
                if (normalized := _optional_text(self.ticker))
                else None
            ),
        )
        object.__setattr__(self, "cik", _optional_cik(self.cik))
        object.__setattr__(
            self,
            "company_name",
            _optional_text(self.company_name),
        )
        object.__setattr__(
            self,
            "accession",
            _optional_text(self.accession),
        )
        object.__setattr__(
            self,
            "form_type",
            (
                normalized.upper()
                if (normalized := _optional_text(self.form_type))
                else None
            ),
        )
        if self.filed_at is not None:
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
            "items",
            tuple(
                normalized
                for item in self.items
                if (normalized := str(item or "").strip())
            ),
        )
        object.__setattr__(
            self,
            "description",
            _optional_text(self.description),
        )
        object.__setattr__(
            self,
            "filing_url",
            _optional_text(self.filing_url),
        )
        object.__setattr__(self, "documents", tuple(self.documents))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


def normalize_sec_filing(
    filing: Mapping[str, Any],
    *,
    received_at: datetime,
) -> SecFilingEnvelope:
    """Normalize transport syntax without applying event semantics."""

    if not isinstance(filing, Mapping):
        raise TypeError("filing must be a mapping")
    return SecFilingEnvelope(
        ticker=filing.get("ticker") or filing.get("symbol"),
        cik=filing.get("cik"),
        company_name=filing.get("companyName"),
        accession=filing.get("accessionNo"),
        form_type=filing.get("formType"),
        filed_at=_parse_timestamp(filing.get("filedAt")),
        received_at=received_at,
        items=_normalized_items(filing.get("items")),
        description=filing.get("description"),
        filing_url=filing.get("linkToFilingDetails"),
        documents=_normalize_documents(
            filing.get("documentFormatFiles")
        ),
        metadata={"transport": "sec_api_websocket"},
    )


def _normalize_documents(
    value: object,
) -> tuple[SecDocumentReference, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
    ):
        return ()
    documents: list[SecDocumentReference] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        documents.append(
            SecDocumentReference(
                document_type=str(item.get("type") or ""),
                document_url=str(item.get("documentUrl") or ""),
                description=_optional_text(item.get("description")),
                sequence=_optional_text(item.get("sequence")),
            )
        )
    return tuple(documents)


def _normalized_items(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values: Sequence[object] = (value,)
    elif isinstance(value, Sequence):
        values = value
    else:
        values = ()
    return tuple(
        normalized
        for item in values
        if (normalized := str(item or "").strip())
    )


def _parse_timestamp(value: object) -> datetime | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(
            normalized.replace("Z", "+00:00")
        )
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _optional_cik(value: object) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        return None
    return normalized.lstrip("0") or "0"


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
