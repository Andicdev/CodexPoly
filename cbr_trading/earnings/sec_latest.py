from __future__ import annotations

import gzip
import logging
import re
import time
import xml.etree.ElementTree as ElementTree
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from cbr_trading.earnings.contracts import EarningsMarketRule
from cbr_trading.earnings.sec_current import (
    SecFilingIndexCandidate,
    fetch_sec_filing_index,
)
from cbr_trading.earnings.sec_stream import SecEarningsWatch
from cbr_trading.sec_filings.contracts import SecFilingEnvelope


SEC_LATEST_FILINGS_ATOM_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=8-K&count=100&output=atom"
)
_SEC_HOST = "www.sec.gov"
_ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
_DEFAULT_LOOKBACK_HOURS = 48
_ACCESSION_PATTERN = re.compile(
    r"accession-number=(\d{10}-\d{2}-\d{6})$"
)
_TITLE_PATTERN = re.compile(
    r"^8-K\s+-\s+(.+?)\s+\((\d{1,10})\)\s+\(Filer\)\s*$",
    re.IGNORECASE,
)
_ITEM_PATTERN = re.compile(r"\bItem\s+(\d+\.\d+)\b", re.IGNORECASE)


class SecLatestFilingsError(RuntimeError):
    """Sanitized failure while polling the SEC Latest Filings feed."""


@dataclass(frozen=True)
class SecLatestEarningsWatch:
    routing_watch: SecEarningsWatch
    filed_not_before: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.routing_watch, SecEarningsWatch):
            raise TypeError("routing_watch must be SecEarningsWatch")
        object.__setattr__(
            self,
            "filed_not_before",
            _as_utc(self.filed_not_before, "filed_not_before"),
        )


@dataclass(frozen=True)
class SecLatestPollResult:
    envelopes: tuple[SecFilingEnvelope, ...]
    watch_count: int
    success_count: int
    not_modified_count: int
    error_count: int
    deferred_count: int


@dataclass
class _PendingFiling:
    filing: SecFilingIndexCandidate
    attempts: int = 0
    retry_after: float = 0.0


class SecLatestFilingsClient:
    """Poll one official Latest Filings feed for all active issuers."""

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
            "cbr_trading.earnings.sec_latest"
        )
        self._last_request_started: float | None = None
        self._etag: str | None = None
        self._modified: str | None = None
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
        watches: Sequence[SecLatestEarningsWatch],
    ) -> SecLatestPollResult:
        watch_rows = tuple(watches)
        if any(
            not isinstance(watch, SecLatestEarningsWatch)
            for watch in watch_rows
        ):
            raise TypeError(
                "watches must contain SecLatestEarningsWatch objects"
            )
        if not watch_rows:
            return SecLatestPollResult(
                envelopes=(),
                watch_count=0,
                success_count=0,
                not_modified_count=0,
                error_count=0,
                deferred_count=0,
            )

        watch_by_cik = {
            watch.routing_watch.cik: watch
            for watch in watch_rows
        }
        successes = 0
        not_modified = 0
        errors = 0
        deferred = 0
        try:
            feed_result = self._fetch_feed()
            if feed_result is None:
                not_modified = 1
            else:
                payload, feed_observed_at = feed_result
                successes = 1
                for filing in _atom_filings(
                    payload,
                    watches=watch_by_cik,
                    observed_at=feed_observed_at,
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
                "SEC Latest Filings feed poll failed error_code=%s",
                type(exc).__name__,
            )

        active_ciks = frozenset(watch_by_cik)
        envelopes: list[SecFilingEnvelope] = [
            envelope
            for (cik, _), envelope in self._resolved.items()
            if cik in active_ciks
        ]
        monotonic_now = float(self._monotonic())
        for key, pending in tuple(self._pending.items()):
            if pending.filing.cik not in active_ciks:
                continue
            if pending.retry_after > monotonic_now:
                deferred += 1
                continue
            try:
                envelope = fetch_sec_filing_index(
                    pending.filing,
                    open_request=self._open,
                    clock=self._clock,
                    max_bytes=self._max_bytes,
                    transport="sec_latest_filings_atom",
                    headers=self._headers(
                        accept=(
                            "text/html,application/xhtml+xml;q=0.9,"
                            "*/*;q=0.1"
                        )
                    ),
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
                    "SEC Latest filing detail poll failed "
                    "accession=%s error_code=%s",
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
            envelope = replace(
                envelope,
                metadata={
                    **dict(envelope.metadata),
                    "feed": "sec_latest_filings_atom",
                },
            )
            envelopes.append(envelope)
            self._resolved[key] = envelope
            self._pending.pop(key, None)

        return SecLatestPollResult(
            envelopes=tuple(envelopes),
            watch_count=len(watch_rows),
            success_count=successes,
            not_modified_count=not_modified,
            error_count=errors,
            deferred_count=deferred,
        )

    def _fetch_feed(
        self,
    ) -> tuple[bytes, datetime] | None:
        headers = self._headers(
            accept=(
                "application/atom+xml,application/xml;q=0.9,"
                "text/xml;q=0.8,*/*;q=0.1"
            )
        )
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._modified:
            headers["If-Modified-Since"] = self._modified
        request = Request(
            SEC_LATEST_FILINGS_ATOM_URL,
            headers=headers,
            method="GET",
        )
        try:
            response_context = self._open(request)
        except HTTPError as exc:
            if exc.code == 304:
                return None
            raise SecLatestFilingsError(
                "SEC Latest Filings request failed"
            ) from None
        with response_context as response:
            status = int(getattr(response, "status", 200))
            if status == 304:
                return None
            if status != 200:
                raise SecLatestFilingsError(
                    "SEC Latest Filings returned a non-success status"
                )
            final_url = (
                str(response.geturl())
                if hasattr(response, "geturl")
                else SEC_LATEST_FILINGS_ATOM_URL
            )
            _require_latest_feed_url(final_url)
            body = _read_bounded_feed(
                response,
                max_bytes=self._max_bytes,
            )
            response_headers = getattr(response, "headers", None)
            self._etag = (
                _header(response_headers, "ETag") or self._etag
            )
            self._modified = (
                _header(response_headers, "Last-Modified")
                or self._modified
            )
        return body, _as_utc(self._clock(), "clock")

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


def sec_latest_watches_from_rules(
    rules: Sequence[EarningsMarketRule],
) -> tuple[SecLatestEarningsWatch, ...]:
    watches: list[SecLatestEarningsWatch] = []
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
                "sec_latest_lookback_hours",
                _DEFAULT_LOOKBACK_HOURS,
            )
        )
        if not 1 <= lookback_hours <= 168:
            raise ValueError(
                "sec_latest_lookback_hours must be between 1 and 168"
            )
        watches.append(
            SecLatestEarningsWatch(
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


def _atom_filings(
    payload: bytes,
    *,
    watches: dict[str, SecLatestEarningsWatch],
    observed_at: datetime,
) -> tuple[SecFilingIndexCandidate, ...]:
    transport_observed_at = _as_utc(
        observed_at,
        "observed_at",
    )
    lowered = payload.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise SecLatestFilingsError(
            "SEC Latest Filings XML declarations are not allowed"
        )
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        raise SecLatestFilingsError(
            "SEC Latest Filings response is invalid XML"
        ) from None
    if root.tag != f"{{{_ATOM_NAMESPACE}}}feed":
        raise SecLatestFilingsError(
            "SEC Latest Filings response is not an Atom feed"
        )
    namespace = {"atom": _ATOM_NAMESPACE}
    filings: list[SecFilingIndexCandidate] = []
    for entry in root.findall("atom:entry", namespace):
        category = entry.find("atom:category", namespace)
        if (
            category is None
            or str(category.attrib.get("term") or "").upper() != "8-K"
        ):
            continue
        title = _element_text(entry, "title", namespace)
        title_match = _TITLE_PATTERN.match(title)
        if title_match is None:
            continue
        company_name, cik_raw = title_match.groups()
        cik = cik_raw.lstrip("0") or "0"
        watch = watches.get(cik)
        if watch is None:
            continue
        summary = _element_text(entry, "summary", namespace)
        items = tuple(
            dict.fromkeys(
                f"Item {item}"
                for item in _ITEM_PATTERN.findall(summary)
            )
        )
        if not any(
            item.casefold() == "item 2.02"
            for item in items
        ):
            continue
        filed_at = _parse_atom_timestamp(
            _element_text(entry, "updated", namespace)
        )
        if filed_at < watch.filed_not_before:
            continue
        entry_id = _element_text(entry, "id", namespace)
        accession_match = _ACCESSION_PATTERN.search(entry_id)
        if accession_match is None:
            raise SecLatestFilingsError(
                "SEC Latest Filings accession is invalid"
            )
        accession = accession_match.group(1)
        filing_url = _entry_link(entry, namespace)
        _require_filing_url(
            filing_url,
            cik=cik,
            accession=accession,
        )
        filings.append(
            SecFilingIndexCandidate(
                ticker=watch.routing_watch.ticker,
                cik=cik,
                company_name=company_name,
                accession=accession,
                form_type="8-K",
                filed_at=filed_at,
                items=items,
                description="8-K earnings release",
                primary_document=None,
                filing_url=filing_url,
                transport_observed_at=transport_observed_at,
            )
        )
    return tuple(filings)


def _element_text(
    entry: ElementTree.Element,
    name: str,
    namespace: dict[str, str],
) -> str:
    element = entry.find(f"atom:{name}", namespace)
    return str(element.text or "").strip() if element is not None else ""


def _entry_link(
    entry: ElementTree.Element,
    namespace: dict[str, str],
) -> str:
    for link in entry.findall("atom:link", namespace):
        if str(link.attrib.get("rel") or "") == "alternate":
            value = str(link.attrib.get("href") or "").strip()
            if value:
                return value
    raise SecLatestFilingsError(
        "SEC Latest Filings entry has no filing link"
    )


def _parse_atom_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")
        )
    except ValueError:
        raise SecLatestFilingsError(
            "SEC Latest Filings timestamp is invalid"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SecLatestFilingsError(
            "SEC Latest Filings timestamp has no timezone"
        )
    return parsed.astimezone(timezone.utc)


def _require_latest_feed_url(value: str) -> None:
    parsed = urlparse(str(value or ""))
    query = parse_qs(
        parsed.query,
        keep_blank_values=True,
        strict_parsing=True,
    )
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != _SEC_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path != "/cgi-bin/browse-edgar"
        or parsed.fragment
        or query
        != {
            "action": ["getcurrent"],
            "type": ["8-K"],
            "count": ["100"],
            "output": ["atom"],
        }
    ):
        raise SecLatestFilingsError(
            "SEC Latest Filings URL left the approved endpoint"
        )


def _require_filing_url(
    value: str,
    *,
    cik: str,
    accession: str,
) -> None:
    parsed = urlparse(str(value or ""))
    compact = accession.replace("-", "")
    expected_path = (
        f"/Archives/edgar/data/{cik}/{compact}/"
        f"{accession}-index.htm"
    )
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != _SEC_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise SecLatestFilingsError(
            "SEC Latest Filings entry URL is invalid"
        )


def _read_bounded_feed(
    response: Any,
    *,
    max_bytes: int,
) -> bytes:
    raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise SecLatestFilingsError(
            "SEC Latest Filings response exceeds the size limit"
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
        raise SecLatestFilingsError(
            "SEC Latest Filings compression is invalid"
        ) from None
    if not raw:
        raise SecLatestFilingsError(
            "SEC Latest Filings response is empty"
        )
    if len(raw) > max_bytes:
        raise SecLatestFilingsError(
            "SEC Latest Filings decoded response exceeds the size limit"
        )
    return raw


def _header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    value = getter(name) if callable(getter) else None
    normalized = str(value or "").strip()
    return normalized or None


def _as_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "SEC_LATEST_FILINGS_ATOM_URL",
    "SecLatestEarningsWatch",
    "SecLatestFilingsClient",
    "SecLatestFilingsError",
    "SecLatestPollResult",
    "sec_latest_watches_from_rules",
]
