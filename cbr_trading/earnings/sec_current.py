from __future__ import annotations

import gzip
import json
import logging
import time
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from cbr_trading.earnings.contracts import EarningsMarketRule
from cbr_trading.earnings.sec_stream import SecEarningsWatch
from cbr_trading.sec_filings.contracts import (
    SecDocumentReference,
    SecFilingEnvelope,
)


SEC_SUBMISSIONS_URL = (
    "https://data.sec.gov/submissions/CIK{cik_padded}.json"
)
SEC_ARCHIVE_FILING_URL = (
    "https://www.sec.gov/Archives/edgar/data/"
    "{cik}/{accession_compact}/{accession}-index.html"
)
_SEC_DATA_HOST = "data.sec.gov"
_SEC_ARCHIVE_HOST = "www.sec.gov"
_DEFAULT_LOOKBACK_HOURS = 48


class SecCurrentFilingsError(RuntimeError):
    """Sanitized failure while polling the official SEC submissions API."""


@dataclass(frozen=True)
class SecCurrentEarningsWatch:
    routing_watch: SecEarningsWatch
    filed_not_before: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.routing_watch, SecEarningsWatch):
            raise TypeError("routing_watch must be SecEarningsWatch")
        threshold = _as_utc(
            self.filed_not_before,
            "filed_not_before",
        )
        object.__setattr__(self, "filed_not_before", threshold)


@dataclass(frozen=True)
class SecCurrentPollResult:
    envelopes: tuple[SecFilingEnvelope, ...]
    watch_count: int
    success_count: int
    not_modified_count: int
    error_count: int
    deferred_count: int


@dataclass(frozen=True)
class _SubmissionFiling:
    ticker: str
    cik: str
    company_name: str | None
    accession: str
    form_type: str
    filed_at: datetime
    items: tuple[str, ...]
    description: str | None
    primary_document: str | None


@dataclass
class _PendingFiling:
    filing: _SubmissionFiling
    attempts: int = 0
    retry_after: float = 0.0


@dataclass(frozen=True)
class _DocumentCell:
    text: str
    href: str | None


class _FilingDocumentTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.documents: list[tuple[_DocumentCell, ...]] = []
        self._table_depth = 0
        self._in_documents_table = False
        self._row: list[_DocumentCell] | None = None
        self._cell_text: list[str] | None = None
        self._cell_href: str | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.casefold()
        attributes = {
            str(name).casefold(): str(value or "")
            for name, value in attrs
        }
        if normalized == "table":
            if self._in_documents_table:
                self._table_depth += 1
            else:
                classes = {
                    value.casefold()
                    for value in attributes.get("class", "").split()
                }
                if "tablefile" in classes:
                    self._in_documents_table = True
                    self._table_depth = 1
            return
        if not self._in_documents_table:
            return
        if normalized == "tr":
            self._row = []
        elif normalized in {"td", "th"} and self._row is not None:
            self._cell_text = []
            self._cell_href = None
        elif (
            normalized == "a"
            and self._cell_text is not None
            and not self._cell_href
        ):
            self._cell_href = attributes.get("href") or None

    def handle_data(self, data: str) -> None:
        if self._cell_text is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if not self._in_documents_table:
            return
        if (
            normalized in {"td", "th"}
            and self._row is not None
            and self._cell_text is not None
        ):
            self._row.append(
                _DocumentCell(
                    text=" ".join(
                        " ".join(self._cell_text).split()
                    ),
                    href=self._cell_href,
                )
            )
            self._cell_text = None
            self._cell_href = None
        elif normalized == "tr":
            if self._row:
                self.documents.append(tuple(self._row))
            self._row = None
            self._cell_text = None
            self._cell_href = None
        elif normalized == "table":
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_documents_table = False
                self._table_depth = 0


class SecCurrentFilingsClient:
    """Poll official per-issuer SEC submissions with global pacing."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float,
        max_bytes: int = 4 * 1024 * 1024,
        max_requests_per_second: float = 5.0,
        opener: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: logging.Logger | None = None,
    ):
        normalized_agent = str(user_agent or "").strip()
        if not normalized_agent:
            raise ValueError("user_agent is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 1024 <= int(max_bytes) <= 8 * 1024 * 1024:
            raise ValueError(
                "max_bytes must be between 1024 and 8388608"
            )
        request_rate = float(max_requests_per_second)
        if not 0.5 <= request_rate <= 5.0:
            raise ValueError(
                "max_requests_per_second must be between 0.5 and 5"
            )
        self._user_agent = normalized_agent
        self._timeout = float(timeout)
        self._max_bytes = int(max_bytes)
        self._request_interval = 1.0 / request_rate
        self._opener = opener or urlopen
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep
        self._logger = logger or logging.getLogger(
            "cbr_trading.earnings.sec_current"
        )
        self._last_request_started: float | None = None
        self._validators: dict[
            str,
            tuple[str | None, str | None],
        ] = {}
        self._pending: dict[
            tuple[str, str],
            _PendingFiling,
        ] = {}
        self._resolved: dict[
            tuple[str, str],
            SecFilingEnvelope,
        ] = {}

    def poll(
        self,
        watches: Sequence[SecCurrentEarningsWatch],
    ) -> SecCurrentPollResult:
        watch_rows = tuple(watches)
        if any(
            not isinstance(watch, SecCurrentEarningsWatch)
            for watch in watch_rows
        ):
            raise TypeError(
                "watches must contain SecCurrentEarningsWatch objects"
            )
        successes = 0
        not_modified = 0
        errors = 0
        deferred = 0
        now = _as_utc(self._clock(), "clock")

        active_keys = {
            (
                watch.routing_watch.cik,
                watch.routing_watch.scope_id,
            )
            for watch in watch_rows
        }
        for watch in watch_rows:
            try:
                payload = self._fetch_submissions(
                    watch.routing_watch.cik
                )
                if payload is None:
                    not_modified += 1
                    continue
                successes += 1
                for filing in _submission_filings(
                    payload,
                    watch=watch,
                ):
                    key = (filing.cik, filing.accession)
                    if key in self._resolved:
                        continue
                    self._pending.setdefault(
                        key,
                        _PendingFiling(filing=filing),
                    )
            except Exception as exc:
                errors += 1
                self._logger.warning(
                    "SEC submissions poll failed cik=%s "
                    "error_code=%s",
                    watch.routing_watch.cik,
                    type(exc).__name__,
                )

        watch_by_cik = {
            watch.routing_watch.cik: watch
            for watch in watch_rows
        }
        envelopes: list[SecFilingEnvelope] = [
            envelope
            for (cik, _), envelope in self._resolved.items()
            if cik in watch_by_cik
        ]
        monotonic_now = float(self._monotonic())
        for key, pending in tuple(self._pending.items()):
            watch = watch_by_cik.get(pending.filing.cik)
            if watch is None:
                continue
            if (
                pending.filing.cik,
                watch.routing_watch.scope_id,
            ) not in active_keys:
                continue
            if pending.retry_after > monotonic_now:
                deferred += 1
                continue
            try:
                envelope = self._fetch_filing_envelope(
                    pending.filing,
                    received_at=now,
                )
                successes += 1
            except Exception as exc:
                errors += 1
                pending.attempts += 1
                pending.retry_after = (
                    monotonic_now
                    + min(2 ** min(pending.attempts - 1, 4), 15)
                )
                self._logger.warning(
                    "SEC filing detail poll failed accession=%s "
                    "error_code=%s",
                    pending.filing.accession,
                    type(exc).__name__,
                )
                continue
            exhibit_count = sum(
                document.document_type == "EX-99.1"
                for document in envelope.documents
            )
            if exhibit_count == 0:
                pending.attempts += 1
                if pending.attempts < 10:
                    pending.retry_after = (
                        monotonic_now
                        + min(
                            2 ** min(pending.attempts - 1, 4),
                            15,
                        )
                    )
                    deferred += 1
                    continue
            envelopes.append(envelope)
            self._resolved[key] = envelope
            self._pending.pop(key, None)

        return SecCurrentPollResult(
            envelopes=tuple(envelopes),
            watch_count=len(watch_rows),
            success_count=successes,
            not_modified_count=not_modified,
            error_count=errors,
            deferred_count=deferred,
        )

    def _fetch_submissions(
        self,
        cik: str,
    ) -> Mapping[str, Any] | None:
        normalized_cik = _normalize_cik(cik)
        url = SEC_SUBMISSIONS_URL.format(
            cik_padded=normalized_cik.zfill(10)
        )
        etag, modified = self._validators.get(
            url,
            (None, None),
        )
        headers = self._headers(
            accept="application/json,*/*;q=0.1"
        )
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        request = Request(url, headers=headers, method="GET")
        try:
            response_context = self._open(request)
        except HTTPError as exc:
            if exc.code == 304:
                return None
            raise SecCurrentFilingsError(
                "SEC submissions request failed"
            ) from None
        with response_context as response:
            status = int(getattr(response, "status", 200))
            if status == 304:
                return None
            if status != 200:
                raise SecCurrentFilingsError(
                    "SEC submissions returned a non-success status"
                )
            final_url = _response_url(response, url)
            _require_sec_url(
                final_url,
                host=_SEC_DATA_HOST,
                path_prefix="/submissions/",
            )
            body = _read_bounded_body(
                response,
                max_bytes=self._max_bytes,
            )
            response_headers = getattr(response, "headers", None)
            next_etag = _header(response_headers, "ETag")
            next_modified = _header(
                response_headers,
                "Last-Modified",
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SecCurrentFilingsError(
                "SEC submissions response is invalid JSON"
            ) from None
        if not isinstance(payload, Mapping):
            raise SecCurrentFilingsError(
                "SEC submissions response must be an object"
            )
        response_cik = _normalize_cik(payload.get("cik"))
        if response_cik != normalized_cik:
            raise SecCurrentFilingsError(
                "SEC submissions response CIK mismatch"
            )
        self._validators[url] = (
            next_etag or etag,
            next_modified or modified,
        )
        return payload

    def _fetch_filing_envelope(
        self,
        filing: _SubmissionFiling,
        *,
        received_at: datetime,
    ) -> SecFilingEnvelope:
        compact = filing.accession.replace("-", "")
        url = SEC_ARCHIVE_FILING_URL.format(
            cik=filing.cik,
            accession_compact=compact,
            accession=filing.accession,
        )
        request = Request(
            url,
            headers=self._headers(
                accept=(
                    "text/html,application/xhtml+xml;q=0.9,"
                    "*/*;q=0.1"
                )
            ),
            method="GET",
        )
        try:
            response_context = self._open(request)
        except HTTPError:
            raise SecCurrentFilingsError(
                "SEC filing detail request failed"
            ) from None
        with response_context as response:
            status = int(getattr(response, "status", 200))
            if status != 200:
                raise SecCurrentFilingsError(
                    "SEC filing detail returned a non-success status"
                )
            final_url = _response_url(response, url)
            _require_sec_url(
                final_url,
                host=_SEC_ARCHIVE_HOST,
                path_prefix="/Archives/edgar/data/",
            )
            body = _read_bounded_body(
                response,
                max_bytes=self._max_bytes,
            )
        documents = _parse_filing_documents(
            body,
            filing_url=final_url,
        )
        return SecFilingEnvelope(
            ticker=filing.ticker,
            cik=filing.cik,
            company_name=filing.company_name,
            accession=filing.accession,
            form_type=filing.form_type,
            filed_at=filing.filed_at,
            received_at=received_at,
            items=filing.items,
            description=filing.description,
            filing_url=final_url,
            documents=documents,
            metadata={
                "transport": "sec_submissions",
                "primary_document": filing.primary_document,
            },
        )

    def _headers(self, *, accept: str) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": accept,
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

    def _open(self, request: Request):
        now = float(self._monotonic())
        if self._last_request_started is not None:
            remaining = (
                self._request_interval
                - (now - self._last_request_started)
            )
            if remaining > 0:
                self._sleep(remaining)
                now = float(self._monotonic())
        self._last_request_started = now
        return self._opener(request, timeout=self._timeout)

    def close(self) -> None:
        return None


def sec_current_watches_from_rules(
    rules: Sequence[EarningsMarketRule],
) -> tuple[SecCurrentEarningsWatch, ...]:
    watches: list[SecCurrentEarningsWatch] = []
    issuer_scopes: dict[str, str] = {}
    for rule in rules:
        if not rule.source_policy.get("sec"):
            continue
        existing_scope = issuer_scopes.get(rule.cik)
        if existing_scope and existing_scope != rule.scope_id:
            raise ValueError(
                "multiple active earnings scopes for one CIK"
            )
        issuer_scopes[rule.cik] = rule.scope_id
        lookback_hours = int(
            rule.source_policy.get(
                "sec_current_lookback_hours",
                _DEFAULT_LOOKBACK_HOURS,
            )
        )
        if not 1 <= lookback_hours <= 168:
            raise ValueError(
                "sec_current_lookback_hours must be between 1 and 168"
            )
        watches.append(
            SecCurrentEarningsWatch(
                routing_watch=SecEarningsWatch(
                    scope_id=rule.scope_id,
                    ticker=rule.ticker,
                    cik=rule.cik,
                ),
                filed_not_before=(
                    rule.estimated_release_at
                    - timedelta(hours=lookback_hours)
                ),
            )
        )
    return tuple(watches)


def _submission_filings(
    payload: Mapping[str, Any],
    *,
    watch: SecCurrentEarningsWatch,
) -> tuple[_SubmissionFiling, ...]:
    filings = payload.get("filings")
    recent = (
        filings.get("recent")
        if isinstance(filings, Mapping)
        else None
    )
    if not isinstance(recent, Mapping):
        raise SecCurrentFilingsError(
            "SEC submissions response has no recent filings"
        )
    accessions = recent.get("accessionNumber")
    if not _is_array(accessions):
        raise SecCurrentFilingsError(
            "SEC submissions accession array is missing"
        )
    company_name = _optional_text(payload.get("name"))
    rows: list[_SubmissionFiling] = []
    for index, accession_value in enumerate(accessions):
        accession = str(accession_value or "").strip()
        form_type = _array_text(recent, "form", index).upper()
        if form_type != "8-K":
            continue
        items = _normalize_submission_items(
            _array_text(recent, "items", index)
        )
        if not any(
            item.casefold() == "item 2.02"
            for item in items
        ):
            continue
        filed_at = _parse_sec_timestamp(
            _array_text(
                recent,
                "acceptanceDateTime",
                index,
            )
        )
        if filed_at < watch.filed_not_before:
            continue
        if not _valid_accession(accession):
            raise SecCurrentFilingsError(
                "SEC submissions accession is invalid"
            )
        rows.append(
            _SubmissionFiling(
                ticker=watch.routing_watch.ticker,
                cik=watch.routing_watch.cik,
                company_name=company_name,
                accession=accession,
                form_type=form_type,
                filed_at=filed_at,
                items=items,
                description=(
                    _optional_text(
                        _array_text(
                            recent,
                            "primaryDocDescription",
                            index,
                        )
                    )
                    or form_type
                ),
                primary_document=_optional_text(
                    _array_text(
                        recent,
                        "primaryDocument",
                        index,
                    )
                ),
            )
        )
    return tuple(rows)


def _parse_filing_documents(
    document: bytes,
    *,
    filing_url: str,
) -> tuple[SecDocumentReference, ...]:
    try:
        html = document.decode("utf-8")
    except UnicodeDecodeError:
        html = document.decode("latin-1")
    parser = _FilingDocumentTableParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        raise SecCurrentFilingsError(
            "SEC filing detail HTML is invalid"
        ) from None
    documents: list[SecDocumentReference] = []
    for row in parser.documents:
        if len(row) < 4:
            continue
        sequence, description, document_cell, document_type = row[:4]
        href = document_cell.href
        if not href:
            continue
        document_url = urljoin(filing_url, href)
        try:
            _require_sec_url(
                document_url,
                host=_SEC_ARCHIVE_HOST,
                path_prefix="/Archives/edgar/data/",
            )
        except SecCurrentFilingsError:
            # Inline-XBRL viewer links use /ix?doc=... and are not needed
            # for the exact EX-99.1 route. Never follow or persist them.
            continue
        documents.append(
            SecDocumentReference(
                document_type=document_type.text,
                document_url=document_url,
                description=description.text,
                sequence=sequence.text,
            )
        )
    return tuple(documents)


def _read_bounded_body(
    response: Any,
    *,
    max_bytes: int,
) -> bytes:
    raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise SecCurrentFilingsError(
            "SEC response exceeds the size limit"
        )
    encoding = (
        _header(getattr(response, "headers", None), "Content-Encoding")
        or ""
    ).casefold()
    try:
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            raw = zlib.decompress(raw)
    except (OSError, zlib.error):
        raise SecCurrentFilingsError(
            "SEC response compression is invalid"
        ) from None
    if len(raw) > max_bytes:
        raise SecCurrentFilingsError(
            "SEC decoded response exceeds the size limit"
        )
    if not raw:
        raise SecCurrentFilingsError("SEC response is empty")
    return raw


def _response_url(response: Any, fallback: str) -> str:
    if hasattr(response, "geturl"):
        return str(response.geturl())
    return fallback


def _require_sec_url(
    value: str,
    *,
    host: str,
    path_prefix: str,
) -> None:
    parsed = urlparse(str(value or ""))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not parsed.path.startswith(path_prefix)
        or parsed.query
        or parsed.fragment
    ):
        raise SecCurrentFilingsError(
            "SEC response URL left the approved endpoint"
        )


def _header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    value = getter(name) if callable(getter) else None
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_submission_items(value: str) -> tuple[str, ...]:
    return tuple(
        f"Item {normalized}"
        for item in value.split(",")
        if (normalized := str(item or "").strip())
    )


def _array_text(
    recent: Mapping[str, Any],
    name: str,
    index: int,
) -> str:
    values = recent.get(name)
    if not _is_array(values) or index >= len(values):
        return ""
    return str(values[index] or "").strip()


def _is_array(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
    )


def _parse_sec_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
    except ValueError:
        raise SecCurrentFilingsError(
            "SEC filing acceptance timestamp is invalid"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SecCurrentFilingsError(
            "SEC filing acceptance timestamp has no timezone"
        )
    return parsed.astimezone(timezone.utc)


def _valid_accession(value: str) -> bool:
    parts = value.split("-")
    return (
        len(parts) == 3
        and len(parts[0]) == 10
        and len(parts[1]) == 2
        and len(parts[2]) == 6
        and all(part.isdigit() for part in parts)
    )


def _normalize_cik(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized or not normalized.isdigit():
        raise SecCurrentFilingsError("SEC CIK is invalid")
    return normalized.lstrip("0") or "0"


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "SEC_SUBMISSIONS_URL",
    "SecCurrentEarningsWatch",
    "SecCurrentFilingsClient",
    "SecCurrentFilingsError",
    "SecCurrentPollResult",
    "sec_current_watches_from_rules",
]
