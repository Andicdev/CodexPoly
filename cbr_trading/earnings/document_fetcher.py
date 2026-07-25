from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
)


SEC_API_ARCHIVE_HOST = "archive.sec-api.io"
_SEC_ARCHIVE_PATH_PREFIX = "/archives/edgar/data/"
_SUPPORTED_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "text/plain",
        "application/xhtml+xml",
        "application/xml",
    }
)
_ACCESS_BLOCK_MARKERS = (
    b"your request originates from an undeclared automated tool",
    b"request rate threshold exceeded",
)


class SecDocumentFetchError(RuntimeError):
    """Sanitized failure while downloading a public SEC exhibit."""


@dataclass(frozen=True)
class _RouteOutcome:
    route: str
    completed_at: float
    elapsed_ms: int
    document: bytes | None = None
    error_type: str | None = None

class SecDocumentFetcher:
    """Race SEC and SEC-API, returning the first valid bounded exhibit."""

    def __init__(
        self,
        *,
        api_key: str,
        user_agent: str,
        timeout: float,
        max_bytes: int,
        direct_opener: Callable[..., Any] | None = None,
        archive_opener: Callable[..., Any] | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ):
        normalized_key = str(api_key or "").strip()
        normalized_agent = str(user_agent or "").strip()
        if not normalized_key:
            raise ValueError("api_key is required")
        if not normalized_agent:
            raise ValueError("user_agent is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        self._api_key = normalized_key
        self._user_agent = normalized_agent
        self._timeout = float(timeout)
        self._max_bytes = int(max_bytes)
        self._direct_opener = direct_opener or _no_redirect_opener()
        self._archive_opener = archive_opener or _no_redirect_opener()
        self._logger = logger or logging.getLogger(
            "cbr_trading.earnings.fetch"
        )
        self._clock = clock

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            "credential=[REDACTED], routes=('sec_direct', "
            "'sec_api_archive'))"
        )

    def fetch(self, candidate: EarningsDocumentCandidate) -> bytes:
        if candidate.provider is not EarningsProvider.SEC:
            raise SecDocumentFetchError(
                "SEC document fetcher received a non-SEC candidate"
            )
        direct_url = _direct_document_url(candidate.source_url)
        archive_url = _sec_api_archive_url(direct_url)
        requests = {
            "sec_direct": (
                Request(
                    direct_url,
                    headers={
                        "User-Agent": self._user_agent,
                        "Accept": (
                            "text/html,application/xhtml+xml,"
                            "text/plain;q=0.9,*/*;q=0.1"
                        ),
                    },
                    method="GET",
                ),
                self._direct_opener,
                _require_sec_url,
            ),
            "sec_api_archive": (
                Request(
                    archive_url,
                    headers={
                        "Authorization": self._api_key,
                        "User-Agent": "CodexPoly/1.0 earnings-source",
                        "Accept": (
                            "text/html,application/xhtml+xml,"
                            "text/plain;q=0.9,*/*;q=0.1"
                        ),
                    },
                    method="GET",
                ),
                self._archive_opener,
                _require_sec_api_archive_url,
            ),
        }
        executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="sec-document-fetch",
        )
        started_at = self._clock()
        futures: set[Future[_RouteOutcome]] = {
            executor.submit(
                self._fetch_route,
                route=route,
                request=request,
                opener=opener,
                final_url_validator=validator,
                candidate=candidate,
                started_at=started_at,
            )
            for route, (request, opener, validator) in requests.items()
        }
        pending = set(futures)
        try:
            while pending:
                completed, pending = wait(
                    pending,
                    return_when=FIRST_COMPLETED,
                )
                outcomes = sorted(
                    (future.result() for future in completed),
                    key=lambda outcome: outcome.completed_at,
                )
                for outcome in outcomes:
                    if outcome.document is None:
                        continue
                    self._logger.info(
                        "SEC exhibit fetch winner route=%s "
                        "elapsed_ms=%s scope=%s ticker=%s",
                        outcome.route,
                        outcome.elapsed_ms,
                        candidate.scope_id,
                        candidate.ticker,
                    )
                    return outcome.document
        finally:
            # A running loser is intentionally allowed to finish so its
            # aggregate latency remains observable. It cannot delay parsing.
            executor.shutdown(wait=False, cancel_futures=False)
        raise SecDocumentFetchError(
            "SEC exhibit fetch failed via all configured routes"
        )

    def _fetch_route(
        self,
        *,
        route: str,
        request: Request,
        opener: Callable[..., Any],
        final_url_validator: Callable[[str], None],
        candidate: EarningsDocumentCandidate,
        started_at: float,
    ) -> _RouteOutcome:
        try:
            with opener(
                request,
                timeout=self._timeout,
            ) as response:
                final_url = str(
                    response.geturl()
                    if hasattr(response, "geturl")
                    else request.full_url
                )
                final_url_validator(final_url)
                content_type = _content_type(response)
                if (
                    content_type
                    and content_type not in _SUPPORTED_CONTENT_TYPES
                ):
                    raise SecDocumentFetchError(
                        "SEC exhibit has an unsupported content type"
                    )
                document = response.read(self._max_bytes + 1)
            if not document:
                raise SecDocumentFetchError("SEC exhibit is empty")
            if len(document) > self._max_bytes:
                raise SecDocumentFetchError(
                    "SEC exhibit exceeds the configured size limit"
                )
            _reject_access_block(document)
        except Exception as exc:
            completed_at = self._clock()
            outcome = _RouteOutcome(
                route=route,
                completed_at=completed_at,
                elapsed_ms=_elapsed_ms(started_at, completed_at),
                error_type=type(exc).__name__,
            )
            self._logger.warning(
                "SEC exhibit fetch route completed route=%s "
                "status=error elapsed_ms=%s error_type=%s "
                "scope=%s ticker=%s",
                route,
                outcome.elapsed_ms,
                outcome.error_type,
                candidate.scope_id,
                candidate.ticker,
            )
            return outcome
        completed_at = self._clock()
        outcome = _RouteOutcome(
            route=route,
            completed_at=completed_at,
            elapsed_ms=_elapsed_ms(started_at, completed_at),
            document=document,
        )
        self._logger.info(
            "SEC exhibit fetch route completed route=%s "
            "status=success elapsed_ms=%s scope=%s ticker=%s",
            route,
            outcome.elapsed_ms,
            candidate.scope_id,
            candidate.ticker,
        )
        return outcome


def _direct_document_url(value: str) -> str:
    _require_sec_url(value)
    parsed = urlparse(str(value or "").strip())
    if parsed.path.casefold().rstrip("/") != "/ix":
        return value
    document_values = parse_qs(parsed.query).get("doc", ())
    if len(document_values) != 1:
        raise SecDocumentFetchError(
            "SEC inline viewer URL must identify one document"
        )
    document_path = str(document_values[0] or "").strip()
    if not document_path.startswith("/"):
        raise SecDocumentFetchError(
            "SEC inline viewer document path is invalid"
        )
    direct_url = urlunparse(
        ("https", parsed.netloc, document_path, "", "", "")
    )
    _require_sec_url(direct_url)
    return direct_url


def _sec_api_archive_url(sec_url: str) -> str:
    _require_sec_url(sec_url)
    parsed = urlparse(sec_url)
    normalized_path = parsed.path.casefold()
    if not normalized_path.startswith(_SEC_ARCHIVE_PATH_PREFIX):
        raise SecDocumentFetchError(
            "SEC exhibit URL is outside the EDGAR archive"
        )
    archive_path = (
        "/"
        + parsed.path[len(_SEC_ARCHIVE_PATH_PREFIX) :]
    )
    archive_url = urlunparse(
        ("https", SEC_API_ARCHIVE_HOST, archive_path, "", "", "")
    )
    _require_sec_api_archive_url(archive_url)
    return archive_url


def _require_sec_url(value: str) -> None:
    parsed = urlparse(str(value or "").strip())
    hostname = str(parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https":
        raise SecDocumentFetchError("SEC exhibit URL must use HTTPS")
    if hostname != "sec.gov" and not hostname.endswith(".sec.gov"):
        raise SecDocumentFetchError(
            "SEC exhibit URL must use an SEC domain"
        )
    if parsed.username or parsed.password:
        raise SecDocumentFetchError(
            "SEC exhibit URL cannot contain credentials"
        )
    if parsed.fragment:
        raise SecDocumentFetchError(
            "SEC exhibit URL cannot contain a fragment"
        )


def _require_sec_api_archive_url(value: str) -> None:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme.casefold() != "https":
        raise SecDocumentFetchError(
            "SEC-API archive URL must use HTTPS"
        )
    if str(parsed.hostname or "").casefold() != SEC_API_ARCHIVE_HOST:
        raise SecDocumentFetchError(
            "SEC-API archive redirect left the approved domain"
        )
    if parsed.username or parsed.password:
        raise SecDocumentFetchError(
            "SEC-API archive URL cannot contain credentials"
        )
    if parsed.query or parsed.fragment:
        raise SecDocumentFetchError(
            "SEC-API archive URL cannot contain query or fragment data"
        )


def _elapsed_ms(started_at: float, completed_at: float) -> int:
    return max(0, round((completed_at - started_at) * 1000))


def _reject_access_block(document: bytes) -> None:
    sample = document[:128 * 1024].lower()
    if any(marker in sample for marker in _ACCESS_BLOCK_MARKERS):
        raise SecDocumentFetchError(
            "SEC exhibit returned an access-control page"
        )


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any):
        raise SecDocumentFetchError(
            "SEC exhibit redirects are not permitted"
        )


def _no_redirect_opener() -> Callable[..., Any]:
    return build_opener(_RejectRedirects()).open


def _content_type(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    if hasattr(headers, "get_content_type"):
        return str(headers.get_content_type() or "").casefold() or None
    raw = str(headers.get("Content-Type") or "").split(";", 1)[0]
    return raw.strip().casefold() or None
