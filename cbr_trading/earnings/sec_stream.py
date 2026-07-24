from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    SourceAuthority,
)


SEC_STREAM_ENDPOINT = "wss://stream.sec-api.io"


class SecStreamTransportError(RuntimeError):
    """Sanitized SEC transport failure that cannot reveal its credential."""


class _AsyncWebSocket(Protocol):
    def __aiter__(self) -> AsyncIterator[object]: ...


class _AsyncConnection(Protocol):
    async def __aenter__(self) -> _AsyncWebSocket: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None: ...


ConnectFactory = Callable[..., _AsyncConnection]


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
    """Strictly route initial earnings 8-K exhibits to watched event scopes."""

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
        filing: Mapping[str, Any],
        *,
        received_at: datetime,
    ) -> tuple[SecFilingDecision, ...]:
        ticker = str(
            filing.get("ticker")
            or filing.get("symbol")
            or ""
        ).strip().upper()
        cik = _normalize_optional_cik(filing.get("cik"))
        matching = tuple(
            watch
            for watch in self._watches
            if (
                (ticker and ticker == watch.ticker)
                or (cik and cik == watch.cik)
            )
        )
        if not matching:
            return (SecFilingDecision(False, "unwatched_issuer"),)
        return tuple(
            evaluate_sec_earnings_filing(
                filing,
                watch=watch,
                received_at=received_at,
            )
            for watch in matching
        )


class SecStreamEarningsTransport:
    """Read one SEC WebSocket connection and emit only strict candidates."""

    def __init__(
        self,
        *,
        api_key: str,
        watches: Sequence[SecEarningsWatch],
        connect_factory: ConnectFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        normalized_key = str(api_key or "").strip()
        if not normalized_key:
            raise ValueError("SEC API credential is required")
        self._api_key = normalized_key
        self._router = SecStreamFilingRouter(watches)
        self._connect_factory = connect_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            "credential=[REDACTED], "
            f"custom_connector={self._connect_factory is not None})"
        )

    async def stream_once(self) -> AsyncIterator[EarningsDocumentCandidate]:
        """Consume one connection; reconnect policy belongs to the host worker."""

        connector = self._connect_factory or _default_connect_factory()
        uri = (
            f"{SEC_STREAM_ENDPOINT}?apiKey="
            f"{quote(self._api_key, safe='')}"
        )
        try:
            async with connector(
                uri,
                open_timeout=20,
                close_timeout=10,
                max_size=8 * 1024 * 1024,
            ) as websocket:
                async for message in websocket:
                    received_at = _as_utc(self._clock())
                    for filing in decode_sec_stream_message(message):
                        for decision in self._router.route(
                            filing,
                            received_at=received_at,
                        ):
                            if decision.candidate is not None:
                                yield decision.candidate
        except asyncio.CancelledError:
            raise
        except SecStreamTransportError:
            raise
        except Exception as exc:
            raise SecStreamTransportError(
                "SEC earnings stream failed: "
                f"{type(exc).__name__}"
            ) from None
        finally:
            uri = ""


def decode_sec_stream_message(
    message: object,
) -> tuple[Mapping[str, Any], ...]:
    if isinstance(message, bytes):
        try:
            message = message.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecStreamTransportError(
                "SEC stream message is not valid UTF-8"
            ) from exc
    if not isinstance(message, str):
        raise SecStreamTransportError(
            "SEC stream message must be text or bytes"
        )
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as exc:
        raise SecStreamTransportError(
            "SEC stream message is not valid JSON"
        ) from exc
    if not isinstance(payload, list):
        raise SecStreamTransportError(
            "SEC stream message must contain a JSON array"
        )
    if any(not isinstance(item, Mapping) for item in payload):
        raise SecStreamTransportError(
            "SEC stream array must contain only objects"
        )
    return tuple(payload)


def evaluate_sec_earnings_filing(
    filing: Mapping[str, Any],
    *,
    watch: SecEarningsWatch,
    received_at: datetime,
) -> SecFilingDecision:
    ticker = str(
        filing.get("ticker")
        or filing.get("symbol")
        or ""
    ).strip().upper()
    cik = _normalize_optional_cik(filing.get("cik"))
    if not cik:
        return SecFilingDecision(False, "cik_missing")
    if ticker and ticker != watch.ticker:
        return SecFilingDecision(False, "ticker_mismatch")
    if cik != watch.cik:
        return SecFilingDecision(False, "cik_mismatch")

    form_type = str(filing.get("formType") or "").strip().upper()
    if form_type != "8-K":
        return SecFilingDecision(False, "not_initial_8k")

    items = _normalized_items(filing.get("items"))
    description = str(filing.get("description") or "")
    if not _has_item_202(items, description):
        return SecFilingDecision(False, "item_202_missing")

    accession = str(filing.get("accessionNo") or "").strip()
    if not accession:
        return SecFilingDecision(False, "accession_missing")

    filing_url = str(
        filing.get("linkToFilingDetails")
        or ""
    ).strip()
    if not _is_https_url(filing_url):
        return SecFilingDecision(False, "filing_url_missing")

    exhibits = _press_release_exhibits(
        filing.get("documentFormatFiles")
    )
    if not exhibits:
        return SecFilingDecision(False, "exhibit_991_missing")
    if len(exhibits) > 1:
        return SecFilingDecision(False, "exhibit_991_ambiguous")
    exhibit = exhibits[0]
    source_url = str(exhibit.get("documentUrl") or "").strip()
    if not _is_https_url(source_url):
        return SecFilingDecision(False, "exhibit_url_missing")

    filed_at = _parse_timestamp(filing.get("filedAt"))
    if filed_at is None:
        return SecFilingDecision(False, "filed_at_invalid")

    fingerprint = hashlib.sha256(
        (
            f"{EarningsProvider.SEC.value}|{watch.scope_id}|"
            f"{accession}|{source_url}"
        ).encode("utf-8")
    ).hexdigest()
    metadata = {
        "company_name": str(
            filing.get("companyName")
            or ""
        ).strip() or None,
        "description": description.strip() or None,
        "exhibit_description": str(
            exhibit.get("description")
            or ""
        ).strip() or None,
        "exhibit_sequence": str(
            exhibit.get("sequence")
            or ""
        ).strip() or None,
    }
    candidate = EarningsDocumentCandidate(
        scope_id=watch.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=accession,
        ticker=watch.ticker,
        cik=watch.cik,
        form_type=form_type,
        items=items,
        document_type="EX-99.1",
        source_url=source_url,
        filing_url=filing_url,
        filed_at=filed_at,
        received_at=_as_utc(received_at),
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint=fingerprint,
        metadata={
            key: value
            for key, value in metadata.items()
            if value is not None
        },
    )
    return SecFilingDecision(True, "official_earnings_exhibit", candidate)


def _default_connect_factory() -> ConnectFactory:
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise SecStreamTransportError(
            "SEC stream support requires the websockets package"
        ) from exc
    return connect


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


def _has_item_202(
    items: Sequence[str],
    description: str,
) -> bool:
    values = tuple(items) + (description,)
    return any(
        "item 2.02" in str(value).casefold()
        for value in values
    )


def _press_release_exhibits(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    matches: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        exhibit_type = str(item.get("type") or "").strip().upper()
        if exhibit_type != "EX-99.1":
            continue
        matches.append(item)
    return tuple(matches)


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


def _normalize_cik(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        raise ValueError("cik must contain only digits")
    return normalized.lstrip("0") or "0"


def _normalize_optional_cik(value: object) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        return None
    return normalized.lstrip("0") or "0"


def _is_https_url(value: str) -> bool:
    return value.lower().startswith("https://")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)
