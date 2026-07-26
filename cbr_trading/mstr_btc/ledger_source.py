from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any

import requests

from cbr_trading.mstr_btc.contracts import (
    MstrBtcDocumentCandidate,
    MstrBtcFactCandidate,
    MstrBtcHoldingsBaseline,
    MstrBtcParseResult,
    MstrBtcParseStatus,
    MstrBtcProvider,
    MstrBtcValueDerivation,
)
from cbr_trading.mstr_btc.parser import MSTR_CIK, MSTR_TICKER
from cbr_trading.mstr_btc.sec_router import (
    MSTR_JUL21_27_SCOPE_ID,
    MSTR_JUL21_27_WINDOW_END,
    MSTR_JUL21_27_WINDOW_START,
)


STRATEGY_LEDGER_URL = "https://www.strategy.com/ledger"
MSTR_BTC_LEDGER_PARSER_NAME = "mstr_btc_strategy_ledger"
MSTR_BTC_LEDGER_PARSER_VERSION = "1"
MSTR_JUL21_27_BASELINE_ROW_INDEX = 116
MSTR_JUL21_27_BASELINE_HOLDINGS_BTC = 843_775

_MAX_LEDGER_DOCUMENT_BYTES = 2 * 1024 * 1024
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0 Safari/537.36"
)
_LEDGER_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": _BROWSER_USER_AGENT,
}


class StrategyLedgerFetchError(RuntimeError):
    """Sanitized failure while reading the public Strategy Ledger."""


@dataclass(frozen=True)
class MstrBtcLedgerWatch:
    scope_id: str
    window_start: datetime
    window_end: datetime
    baseline_row_index: int
    baseline_holdings_btc: int
    source_url: str = STRATEGY_LEDGER_URL
    ticker: str = MSTR_TICKER
    cik: str = MSTR_CIK

    def __post_init__(self) -> None:
        scope_id = str(self.scope_id or "").strip()
        if not scope_id:
            raise ValueError("scope_id is required")
        window_start = _as_utc(self.window_start, "window_start")
        window_end = _as_utc(self.window_end, "window_end")
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")
        if (
            isinstance(self.baseline_row_index, bool)
            or int(self.baseline_row_index) < 1
        ):
            raise ValueError("baseline_row_index must be positive")
        if (
            isinstance(self.baseline_holdings_btc, bool)
            or int(self.baseline_holdings_btc) < 0
        ):
            raise ValueError(
                "baseline_holdings_btc must be non-negative"
            )
        source_url = str(self.source_url or "").strip()
        if not source_url.lower().startswith("https://"):
            raise ValueError("source_url must use HTTPS")
        ticker = str(self.ticker or "").strip().upper()
        cik = str(self.cik or "").strip().lstrip("0") or "0"
        if not ticker or not cik.isdigit():
            raise ValueError("ticker and numeric CIK are required")
        object.__setattr__(self, "scope_id", scope_id)
        object.__setattr__(self, "window_start", window_start)
        object.__setattr__(self, "window_end", window_end)
        object.__setattr__(
            self,
            "baseline_row_index",
            int(self.baseline_row_index),
        )
        object.__setattr__(
            self,
            "baseline_holdings_btc",
            int(self.baseline_holdings_btc),
        )
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "cik", cik)


@dataclass(frozen=True)
class StrategyLedgerRow:
    uid: str
    row_index: int
    reported_date: date
    btc_change: int
    holdings_btc: int
    filing_url: str | None

    def __post_init__(self) -> None:
        uid = str(self.uid or "").strip()
        if not uid:
            raise ValueError("ledger row uid is required")
        if isinstance(self.row_index, bool) or int(self.row_index) < 1:
            raise ValueError("ledger row_index must be positive")
        if not isinstance(self.reported_date, date):
            raise TypeError("reported_date must be a date")
        if isinstance(self.btc_change, bool):
            raise TypeError("btc_change must be an integer")
        if (
            isinstance(self.holdings_btc, bool)
            or int(self.holdings_btc) < 0
        ):
            raise ValueError("holdings_btc must be non-negative")
        filing_url = str(self.filing_url or "").strip() or None
        if (
            filing_url is not None
            and not filing_url.lower().startswith("https://")
        ):
            raise ValueError("ledger filing_url must use HTTPS")
        object.__setattr__(self, "uid", uid)
        object.__setattr__(self, "row_index", int(self.row_index))
        object.__setattr__(self, "btc_change", int(self.btc_change))
        object.__setattr__(
            self,
            "holdings_btc",
            int(self.holdings_btc),
        )
        object.__setattr__(self, "filing_url", filing_url)


@dataclass(frozen=True)
class StrategyLedgerSnapshot:
    build_id: str
    fetched_at: datetime
    source_url: str
    rows: tuple[StrategyLedgerRow, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        build_id = str(self.build_id or "").strip()
        if not build_id:
            raise ValueError("build_id is required")
        fetched_at = _as_utc(self.fetched_at, "fetched_at")
        source_url = str(self.source_url or "").strip()
        if not source_url.lower().startswith("https://"):
            raise ValueError("source_url must use HTTPS")
        rows = tuple(self.rows)
        if not rows:
            raise ValueError("ledger snapshot must contain rows")
        if len({row.row_index for row in rows}) != len(rows):
            raise ValueError("ledger row indexes must be unique")
        fingerprint = str(self.fingerprint or "").strip()
        if not fingerprint:
            raise ValueError("fingerprint is required")
        object.__setattr__(self, "build_id", build_id)
        object.__setattr__(self, "fetched_at", fetched_at)
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(
            self,
            "rows",
            tuple(sorted(rows, key=lambda row: row.row_index)),
        )
        object.__setattr__(self, "fingerprint", fingerprint)


@dataclass(frozen=True)
class MstrBtcLedgerDecision:
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


class StrategyLedgerClient:
    """Conditional HTTP reader for the public Next.js Ledger page."""

    def __init__(
        self,
        *,
        url: str = STRATEGY_LEDGER_URL,
        timeout: float = 10.0,
        max_bytes: int = _MAX_LEDGER_DOCUMENT_BYTES,
        session: requests.Session | None = None,
    ):
        normalized_url = str(url or "").strip()
        if not normalized_url.lower().startswith("https://"):
            raise ValueError("Strategy Ledger URL must use HTTPS")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 1024 <= int(max_bytes) <= 8 * 1024 * 1024:
            raise ValueError("max_bytes is outside the safe range")
        self._url = normalized_url
        self._timeout = float(timeout)
        self._max_bytes = int(max_bytes)
        self._session = session or requests.Session()
        self._etag: str | None = None
        self._last_fingerprint: str | None = None

    def fetch_snapshot(
        self,
        *,
        fetched_at: datetime | None = None,
    ) -> StrategyLedgerSnapshot | None:
        headers = dict(_LEDGER_HEADERS)
        if self._etag:
            headers["If-None-Match"] = self._etag
        try:
            response = self._session.get(
                self._url,
                headers=headers,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise StrategyLedgerFetchError(
                "Strategy Ledger request failed: "
                f"{type(exc).__name__}"
            ) from None
        if response.status_code == 304:
            return None
        if response.status_code != 200:
            raise StrategyLedgerFetchError(
                "Strategy Ledger returned HTTP "
                f"{int(response.status_code)}"
            )
        document = bytes(response.content)
        if len(document) > self._max_bytes:
            raise StrategyLedgerFetchError(
                "Strategy Ledger response exceeded the byte limit"
            )
        try:
            snapshot = parse_strategy_ledger_html(
                document,
                source_url=self._url,
                fetched_at=(
                    fetched_at
                    if fetched_at is not None
                    else datetime.now(timezone.utc)
                ),
            )
        except Exception as exc:
            raise StrategyLedgerFetchError(
                "Strategy Ledger response was invalid: "
                f"{type(exc).__name__}"
            ) from None
        self._etag = str(response.headers.get("ETag") or "").strip() or None
        if snapshot.fingerprint == self._last_fingerprint:
            return None
        self._last_fingerprint = snapshot.fingerprint
        return snapshot

    def close(self) -> None:
        self._session.close()


class MstrBtcLedgerDocumentFetcher:
    """Serialize already-normalized Ledger evidence for the shared processor."""

    def fetch(self, candidate: MstrBtcDocumentCandidate) -> bytes:
        if candidate.provider is not MstrBtcProvider.STRATEGY_LEDGER:
            raise ValueError("candidate is not a Strategy Ledger event")
        rows = candidate.metadata.get("ledger_rows")
        if not isinstance(rows, Sequence) or isinstance(
            rows,
            (str, bytes, bytearray),
        ):
            raise ValueError("candidate has no normalized ledger rows")
        payload = {
            "baseline_row_index": candidate.metadata.get(
                "baseline_row_index"
            ),
            "ledger_rows": list(rows),
        }
        return _canonical_json(payload)


class MstrBtcLedgerParser:
    """Build a holdings-first fact from signed Strategy Ledger rows."""

    parser_name = MSTR_BTC_LEDGER_PARSER_NAME
    parser_version = MSTR_BTC_LEDGER_PARSER_VERSION

    def parse(
        self,
        document: str | bytes,
        *,
        source: MstrBtcDocumentCandidate,
        baseline: MstrBtcHoldingsBaseline,
        detected_at: datetime,
    ) -> MstrBtcParseResult:
        if source.provider is not MstrBtcProvider.STRATEGY_LEDGER:
            return _parse_result(
                MstrBtcParseStatus.QUARANTINED,
                "unsupported_document_provider",
            )
        if source.ticker != MSTR_TICKER or source.cik != MSTR_CIK:
            return _parse_result(
                MstrBtcParseStatus.QUARANTINED,
                "unsupported_mstr_issuer",
            )
        if source.form_type != "STRATEGY_LEDGER":
            return _parse_result(
                MstrBtcParseStatus.QUARANTINED,
                "unsupported_ledger_form_type",
            )
        try:
            payload = json.loads(_decode_json_document(document))
            rows = _rows_from_normalized_payload(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return _parse_result(
                MstrBtcParseStatus.QUARANTINED,
                "ledger_evidence_invalid",
            )
        if not rows:
            return _parse_result(
                MstrBtcParseStatus.NO_MATCH,
                "ledger_has_no_new_rows",
            )

        holdings_before = baseline.holdings_btc
        holdings_after = rows[-1].holdings_btc
        acquired_btc = sum(
            row.btc_change
            for row in rows
            if row.btc_change > 0
        )
        sold_btc = sum(
            -row.btc_change
            for row in rows
            if row.btc_change < 0
        )
        net_change = holdings_after - holdings_before
        crosscheck_difference = (
            net_change - (acquired_btc - sold_btc)
        )
        if crosscheck_difference != 0:
            return _parse_result(
                MstrBtcParseStatus.QUARANTINED,
                "ledger_holdings_crosscheck_failed",
            )

        raw_document = (
            document.encode("utf-8")
            if isinstance(document, str)
            else bytes(document)
        )
        evidence = (
            "Strategy Ledger rows "
            f"{rows[0].row_index}-{rows[-1].row_index}: "
            f"acquired {acquired_btc} BTC, sold {sold_btc} BTC, "
            f"holdings {holdings_after} BTC.",
        )
        candidate = MstrBtcFactCandidate(
            scope_id=source.scope_id,
            provider=source.provider,
            provider_event_id=source.provider_event_id,
            baseline_state_id=baseline.state_id,
            holdings_before_btc=holdings_before,
            holdings_after_btc=holdings_after,
            net_change_btc=net_change,
            acquired_btc=acquired_btc,
            sold_btc=sold_btc,
            acquired_derivation=MstrBtcValueDerivation.EXPLICIT,
            sold_derivation=MstrBtcValueDerivation.EXPLICIT,
            holdings_crosscheck_difference_btc=(
                crosscheck_difference
            ),
            source_url=source.source_url,
            filing_url=source.filing_url,
            published_at=source.filed_at,
            detected_at=_as_utc(detected_at, "detected_at"),
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            document_fingerprint=hashlib.sha256(
                raw_document
            ).hexdigest(),
            evidence_excerpts=evidence,
            attributes={
                "ticker": source.ticker,
                "cik": source.cik,
                "form_type": source.form_type,
                "transport_fingerprint": (
                    source.transport_fingerprint
                ),
                "ledger_build_id": source.metadata.get(
                    "ledger_build_id"
                ),
                "ledger_row_indexes": [
                    row.row_index for row in rows
                ],
            },
        )
        return MstrBtcParseResult(
            status=MstrBtcParseStatus.ACCEPTED,
            reason="official_strategy_ledger_update",
            candidate=candidate,
        )


def mstr_jul21_27_ledger_watch() -> MstrBtcLedgerWatch:
    return MstrBtcLedgerWatch(
        scope_id=MSTR_JUL21_27_SCOPE_ID,
        window_start=MSTR_JUL21_27_WINDOW_START,
        window_end=MSTR_JUL21_27_WINDOW_END,
        baseline_row_index=MSTR_JUL21_27_BASELINE_ROW_INDEX,
        baseline_holdings_btc=MSTR_JUL21_27_BASELINE_HOLDINGS_BTC,
    )


def parse_strategy_ledger_html(
    document: str | bytes,
    *,
    source_url: str = STRATEGY_LEDGER_URL,
    fetched_at: datetime,
) -> StrategyLedgerSnapshot:
    if isinstance(document, bytes):
        text = document.decode("utf-8")
    elif isinstance(document, str):
        text = document
    else:
        raise TypeError("document must be str or bytes")
    parser = _NextDataParser()
    parser.feed(text)
    parser.close()
    raw_next_data = parser.next_data
    if not raw_next_data:
        raise ValueError("__NEXT_DATA__ was not found")
    decoded = json.loads(raw_next_data)
    if not isinstance(decoded, Mapping):
        raise ValueError("__NEXT_DATA__ must be an object")
    build_id = str(decoded.get("buildId") or "").strip()
    page_props = (
        decoded.get("props", {}).get("pageProps", {})
        if isinstance(decoded.get("props"), Mapping)
        else {}
    )
    raw_rows = (
        page_props.get("bitcoinData")
        if isinstance(page_props, Mapping)
        else None
    )
    if not isinstance(raw_rows, Sequence) or isinstance(
        raw_rows,
        (str, bytes, bytearray),
    ):
        raise ValueError("bitcoinData must be an array")
    rows = tuple(_ledger_row_from_mapping(row) for row in raw_rows)
    fingerprint = hashlib.sha256(
        _canonical_json(
            {
                "build_id": build_id,
                "rows": [
                    _normalized_row_mapping(row)
                    for row in sorted(
                        rows,
                        key=lambda item: item.row_index,
                    )
                ],
            }
        )
    ).hexdigest()
    return StrategyLedgerSnapshot(
        build_id=build_id,
        fetched_at=fetched_at,
        source_url=source_url,
        rows=rows,
        fingerprint=fingerprint,
    )


def evaluate_mstr_btc_ledger(
    snapshot: StrategyLedgerSnapshot,
    *,
    watch: MstrBtcLedgerWatch,
) -> MstrBtcLedgerDecision:
    if not (
        watch.window_start
        <= snapshot.fetched_at
        < watch.window_end
    ):
        return MstrBtcLedgerDecision(False, "outside_event_window")
    rows_by_index = {row.row_index: row for row in snapshot.rows}
    baseline = rows_by_index.get(watch.baseline_row_index)
    if baseline is None:
        return MstrBtcLedgerDecision(
            False,
            "ledger_baseline_row_missing",
        )
    if baseline.holdings_btc != watch.baseline_holdings_btc:
        return MstrBtcLedgerDecision(
            False,
            "ledger_baseline_holdings_changed",
        )
    new_rows = tuple(
        row
        for row in snapshot.rows
        if row.row_index > watch.baseline_row_index
    )
    if not new_rows:
        return MstrBtcLedgerDecision(False, "no_new_ledger_rows")
    expected_indexes = tuple(
        range(
            watch.baseline_row_index + 1,
            new_rows[-1].row_index + 1,
        )
    )
    if tuple(row.row_index for row in new_rows) != expected_indexes:
        return MstrBtcLedgerDecision(
            False,
            "ledger_row_sequence_invalid",
        )

    running_holdings = watch.baseline_holdings_btc
    for row in new_rows:
        running_holdings += row.btc_change
        if running_holdings != row.holdings_btc:
            return MstrBtcLedgerDecision(
                False,
                "ledger_running_holdings_mismatch",
            )

    normalized_rows = [
        _normalized_row_mapping(row) for row in new_rows
    ]
    event_payload = {
        "scope_id": watch.scope_id,
        "baseline_row_index": watch.baseline_row_index,
        "ledger_rows": normalized_rows,
    }
    event_fingerprint = hashlib.sha256(
        _canonical_json(event_payload)
    ).hexdigest()
    first_index = new_rows[0].row_index
    last_row = new_rows[-1]
    provider_event_id = (
        f"ledger:{first_index}-{last_row.row_index}:{last_row.uid}"
    )
    return MstrBtcLedgerDecision(
        True,
        "official_strategy_ledger_rows",
        MstrBtcDocumentCandidate(
            scope_id=watch.scope_id,
            provider=MstrBtcProvider.STRATEGY_LEDGER,
            provider_event_id=provider_event_id,
            ticker=watch.ticker,
            cik=watch.cik,
            form_type="STRATEGY_LEDGER",
            source_url=snapshot.source_url,
            filing_url=last_row.filing_url or snapshot.source_url,
            filed_at=snapshot.fetched_at,
            received_at=snapshot.fetched_at,
            transport_fingerprint=event_fingerprint,
            metadata={
                "ledger_build_id": snapshot.build_id,
                "baseline_row_index": watch.baseline_row_index,
                "ledger_rows": normalized_rows,
            },
        ),
    )


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_next_data = False
        self._parts: list[str] = []

    @property
    def next_data(self) -> str:
        return "".join(self._parts).strip()

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "script":
            return
        attributes = {
            str(name).casefold(): str(value or "")
            for name, value in attrs
        }
        if attributes.get("id") == "__NEXT_DATA__":
            self._inside_next_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._inside_next_data:
            self._inside_next_data = False

    def handle_data(self, data: str) -> None:
        if self._inside_next_data:
            self._parts.append(data)


def _ledger_row_from_mapping(value: object) -> StrategyLedgerRow:
    if not isinstance(value, Mapping):
        raise ValueError("ledger row must be an object")
    sec = value.get("sec")
    return StrategyLedgerRow(
        uid=str(value.get("uid") or ""),
        row_index=_required_int(value.get("row_index"), "row_index"),
        reported_date=date.fromisoformat(
            str(value.get("date_of_purchase") or "")
        ),
        btc_change=_required_int(value.get("count"), "count"),
        holdings_btc=_required_int(
            value.get("btc_holdings"),
            "btc_holdings",
        ),
        filing_url=(
            str(sec.get("url") or "")
            if isinstance(sec, Mapping)
            else None
        ),
    )


def _rows_from_normalized_payload(
    payload: object,
) -> tuple[StrategyLedgerRow, ...]:
    if not isinstance(payload, Mapping):
        raise ValueError("ledger evidence must be an object")
    raw_rows = payload.get("ledger_rows")
    if not isinstance(raw_rows, Sequence) or isinstance(
        raw_rows,
        (str, bytes, bytearray),
    ):
        raise ValueError("ledger_rows must be an array")
    rows = tuple(_ledger_row_from_normalized(row) for row in raw_rows)
    if len({row.row_index for row in rows}) != len(rows):
        raise ValueError("ledger row indexes must be unique")
    return tuple(sorted(rows, key=lambda row: row.row_index))


def _ledger_row_from_normalized(value: object) -> StrategyLedgerRow:
    if not isinstance(value, Mapping):
        raise ValueError("normalized ledger row must be an object")
    return StrategyLedgerRow(
        uid=str(value.get("uid") or ""),
        row_index=_required_int(value.get("row_index"), "row_index"),
        reported_date=date.fromisoformat(
            str(value.get("reported_date") or "")
        ),
        btc_change=_required_int(
            value.get("btc_change"),
            "btc_change",
        ),
        holdings_btc=_required_int(
            value.get("holdings_btc"),
            "holdings_btc",
        ),
        filing_url=str(value.get("filing_url") or "") or None,
    )


def _normalized_row_mapping(
    row: StrategyLedgerRow,
) -> dict[str, object]:
    return {
        "uid": row.uid,
        "row_index": row.row_index,
        "reported_date": row.reported_date.isoformat(),
        "btc_change": row.btc_change,
        "holdings_btc": row.holdings_btc,
        "filing_url": row.filing_url,
    }


def _parse_result(
    status: MstrBtcParseStatus,
    reason: str,
) -> MstrBtcParseResult:
    return MstrBtcParseResult(status=status, reason=reason)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _decode_json_document(document: str | bytes) -> str:
    if isinstance(document, str):
        return document
    if isinstance(document, bytes):
        return document.decode("utf-8")
    raise TypeError("document must be str or bytes")


def _required_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    parsed = int(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer")
    return parsed


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
