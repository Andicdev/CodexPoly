from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

from cbr_trading.fed.contracts import (
    FedDecisionSpec,
    FedRateDecision,
)
from cbr_trading.fed.parser import (
    FedDecisionParseError,
    html_visible_text,
    parse_fomc_target_range,
)


class FedDocumentKind(str, Enum):
    HTML = "html"
    PDF = "pdf"
    RSS = "rss"


@dataclass(frozen=True)
class FedDocumentRoute:
    name: str
    url: str
    kind: FedDocumentKind
    allowed_host: str
    cache_bust: bool = False

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise ValueError("route name is required")
        object.__setattr__(self, "name", name)
        _validate_url(self.url, allowed_host=self.allowed_host)


@dataclass(frozen=True)
class FedRouteResponse:
    status_code: int
    content_type: str
    body: bytes
    final_url: str


@dataclass(frozen=True)
class FedOfficialObservation:
    provider: str
    source_url: str
    decision: FedRateDecision
    detected_at: datetime
    document_fingerprint: str
    excerpt: str

    def __post_init__(self) -> None:
        for name in (
            "provider",
            "source_url",
            "document_fingerprint",
            "excerpt",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        if not self.source_url.startswith("https://"):
            raise ValueError("source_url must use HTTPS")
        if (
            self.detected_at.tzinfo is None
            or self.detected_at.utcoffset() is None
        ):
            raise ValueError("detected_at must be timezone-aware")
        object.__setattr__(
            self,
            "detected_at",
            self.detected_at.astimezone(timezone.utc),
        )


class FedRouteTransport(Protocol):
    def fetch(
        self,
        route: FedDocumentRoute,
        *,
        timeout: tuple[float, float],
        max_bytes: int,
    ) -> FedRouteResponse: ...

    def close(self) -> None: ...


class FedOfficialSourceError(RuntimeError):
    """Sanitized official-source transport or parsing failure."""


class RequestsFedRouteTransport:
    """Bounded allowlisted HTTP transport with one session per route."""

    def __init__(self) -> None:
        try:
            import requests
        except ImportError:
            raise FedOfficialSourceError(
                "Federal Reserve HTTP source requires requests"
            ) from None
        self._requests = requests
        self._sessions: dict[str, Any] = {}
        self._locks: dict[str, Lock] = {}

    def fetch(
        self,
        route: FedDocumentRoute,
        *,
        timeout: tuple[float, float],
        max_bytes: int,
    ) -> FedRouteResponse:
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        session = self._sessions.setdefault(
            route.name,
            self._requests.Session(),
        )
        lock = self._locks.setdefault(route.name, Lock())
        request_url = (
            _cache_busted_url(route.url)
            if route.cache_bust
            else route.url
        )
        headers = {
            "User-Agent": "CodexPoly/1.0 fed-decision-source",
            "Accept": _accept_header(route.kind),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        with lock:
            with session.get(
                request_url,
                headers=headers,
                timeout=timeout,
                stream=True,
                allow_redirects=True,
            ) as response:
                final_url = str(response.url or request_url)
                _validate_url(
                    final_url,
                    allowed_host=route.allowed_host,
                )
                status_code = int(response.status_code)
                content_type = str(
                    response.headers.get("Content-Type") or ""
                ).split(";", 1)[0].strip().casefold()
                if status_code != 200:
                    return FedRouteResponse(
                        status_code=status_code,
                        content_type=content_type,
                        body=b"",
                        final_url=final_url,
                    )
                raw_length = str(
                    response.headers.get("Content-Length") or ""
                ).strip()
                if raw_length:
                    try:
                        content_length = int(raw_length)
                    except ValueError:
                        raise FedOfficialSourceError(
                            "official source has invalid content length"
                        ) from None
                    if content_length > max_bytes:
                        raise FedOfficialSourceError(
                            "official source exceeds the size limit"
                        )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=16 * 1024):
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > max_bytes:
                        raise FedOfficialSourceError(
                            "official source exceeds the size limit"
                        )
                return FedRouteResponse(
                    status_code=status_code,
                    content_type=content_type,
                    body=b"".join(chunks),
                    final_url=final_url,
                )

    def close(self) -> None:
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        self._locks.clear()


class FedOfficialDocumentPoller:
    """Race official FOMC documents and return the first valid decision."""

    def __init__(
        self,
        spec: FedDecisionSpec,
        *,
        transport: FedRouteTransport | None = None,
        pdf_text_extractor: Callable[[bytes], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        connect_timeout: float = 0.35,
        read_timeout: float = 0.65,
        max_html_bytes: int = 1024 * 1024,
        max_pdf_bytes: int = 2 * 1024 * 1024,
        rss_interval: float = 2.0,
        logger: logging.Logger | None = None,
    ):
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("HTTP timeouts must be positive")
        if rss_interval <= 0:
            raise ValueError("rss_interval must be positive")
        self.spec = spec
        self._transport = transport or RequestsFedRouteTransport()
        self._pdf_text_extractor = (
            pdf_text_extractor or _extract_pdf_text
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock
        self._timeout = (
            float(connect_timeout),
            float(read_timeout),
        )
        self._max_html_bytes = int(max_html_bytes)
        self._max_pdf_bytes = int(max_pdf_bytes)
        self._rss_interval = float(rss_interval)
        self._last_rss_poll = float("-inf")
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="fed-official-source",
        )
        self._logger = logger or logging.getLogger(
            "cbr_trading.fed.source"
        )
        self._closed = False
        self._winner: FedOfficialObservation | None = None
        self._routes = _routes_from_spec(spec)

    @property
    def winner(self) -> FedOfficialObservation | None:
        return self._winner

    def poll_once(self) -> FedOfficialObservation | None:
        if self._closed:
            raise RuntimeError("Federal Reserve source poller is closed")
        if self._winner is not None:
            return self._winner
        routes = list(self._routes[:3])
        now = self._monotonic_clock()
        if now - self._last_rss_poll >= self._rss_interval:
            routes.append(self._routes[3])
            self._last_rss_poll = now
        futures: set[Future[FedOfficialObservation | None]] = {
            self._executor.submit(self._fetch_and_parse, route)
            for route in routes
        }
        try:
            for future in as_completed(futures):
                try:
                    observation = future.result()
                except Exception as exc:
                    self._logger.debug(
                        "FED source route failed error_type=%s",
                        type(exc).__name__,
                    )
                    continue
                if observation is None:
                    continue
                self._winner = observation
                for pending in futures:
                    if pending is not future:
                        pending.cancel()
                self._logger.info(
                    "FED decision source confirmed provider=%s "
                    "lower=%s upper=%s",
                    observation.provider,
                    observation.decision.lower,
                    observation.decision.upper,
                )
                return observation
        finally:
            for pending in futures:
                if not pending.done():
                    pending.cancel()
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._transport.close()

    def _fetch_and_parse(
        self,
        route: FedDocumentRoute,
    ) -> FedOfficialObservation | None:
        max_bytes = (
            self._max_pdf_bytes
            if route.kind is FedDocumentKind.PDF
            else self._max_html_bytes
        )
        response = self._transport.fetch(
            route,
            timeout=self._timeout,
            max_bytes=max_bytes,
        )
        if response.status_code != 200 or not response.body:
            return None
        if route.kind is FedDocumentKind.RSS:
            discovered = _statement_url_from_rss(
                response.body,
                expected_url=self.spec.board_statement_url,
            )
            if discovered is None:
                return None
            route = FedDocumentRoute(
                name="board_statement_rss_discovered",
                url=discovered,
                kind=FedDocumentKind.HTML,
                allowed_host="www.federalreserve.gov",
                cache_bust=True,
            )
            response = self._transport.fetch(
                route,
                timeout=self._timeout,
                max_bytes=self._max_html_bytes,
            )
            if response.status_code != 200 or not response.body:
                return None
        _validate_content_type(route.kind, response.content_type)
        text = (
            self._pdf_text_extractor(response.body)
            if route.kind is FedDocumentKind.PDF
            else html_visible_text(response.body)
        )
        try:
            decision = parse_fomc_target_range(
                text,
                expected_release_date=self.spec.release_at.date(),
            )
        except FedDecisionParseError:
            return None
        detected_at = self._clock()
        if (
            detected_at.tzinfo is None
            or detected_at.utcoffset() is None
        ):
            raise ValueError("FED source clock must be timezone-aware")
        excerpt = _decision_excerpt(text)
        return FedOfficialObservation(
            provider=route.name,
            source_url=route.url,
            decision=decision,
            detected_at=detected_at,
            document_fingerprint=hashlib.sha256(
                response.body
            ).hexdigest(),
            excerpt=excerpt,
        )


def _routes_from_spec(
    spec: FedDecisionSpec,
) -> tuple[FedDocumentRoute, ...]:
    return (
        FedDocumentRoute(
            name="fed_board_statement_html",
            url=spec.board_statement_url,
            kind=FedDocumentKind.HTML,
            allowed_host="www.federalreserve.gov",
            cache_bust=True,
        ),
        FedDocumentRoute(
            name="fed_board_implementation_html",
            url=spec.board_implementation_url,
            kind=FedDocumentKind.HTML,
            allowed_host="www.federalreserve.gov",
            cache_bust=True,
        ),
        FedDocumentRoute(
            name="new_york_fed_statement_pdf",
            url=spec.new_york_fed_pdf_url,
            kind=FedDocumentKind.PDF,
            allowed_host="www.newyorkfed.org",
        ),
        FedDocumentRoute(
            name="fed_monetary_policy_rss",
            url=spec.monetary_policy_rss_url,
            kind=FedDocumentKind.RSS,
            allowed_host="www.federalreserve.gov",
            cache_bust=True,
        ),
    )


def _extract_pdf_text(document: bytes) -> str:
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError:
        raise FedOfficialSourceError(
            "Federal Reserve PDF source requires pypdf"
        ) from None
    try:
        reader = PdfReader(BytesIO(document))
        return "\n".join(
            page.extract_text() or ""
            for page in reader.pages[:4]
        )
    except Exception as exc:
        raise FedOfficialSourceError(
            "Federal Reserve PDF could not be parsed: "
            f"{type(exc).__name__}"
        ) from None


def _statement_url_from_rss(
    document: bytes,
    *,
    expected_url: str,
) -> str | None:
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError:
        return None
    normalized_expected = expected_url.rstrip("/").casefold()
    for item in root.iter():
        if str(item.tag).rsplit("}", 1)[-1].casefold() != "item":
            continue
        title = ""
        link = ""
        guid = ""
        for child in item:
            local_name = str(child.tag).rsplit("}", 1)[-1].casefold()
            if local_name == "title":
                title = str(child.text or "").strip()
            elif local_name == "link":
                link = str(child.text or "").strip()
            elif local_name == "guid":
                guid = str(child.text or "").strip()
        discovered_url = link or guid
        if (
            title.casefold() == "federal reserve issues fomc statement"
            and discovered_url.rstrip("/").casefold()
            == normalized_expected
        ):
            return expected_url
    return None


def _validate_content_type(
    kind: FedDocumentKind,
    content_type: str,
) -> None:
    expected = {
        FedDocumentKind.HTML: {
            "text/html",
            "application/xhtml+xml",
        },
        FedDocumentKind.PDF: {"application/pdf"},
        FedDocumentKind.RSS: {
            "application/rss+xml",
            "application/xml",
            "text/xml",
        },
    }[kind]
    if content_type and content_type not in expected:
        raise FedOfficialSourceError(
            "official source returned an unsupported content type"
        )


def _decision_excerpt(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    marker = "target range for the federal funds rate"
    index = normalized.casefold().find(marker)
    if index < 0:
        return normalized[:500]
    start = max(0, index - 120)
    return normalized[start : index + 380]


def _accept_header(kind: FedDocumentKind) -> str:
    return {
        FedDocumentKind.HTML: (
            "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"
        ),
        FedDocumentKind.PDF: "application/pdf,*/*;q=0.1",
        FedDocumentKind.RSS: (
            "application/rss+xml,application/xml,text/xml;q=0.9,"
            "*/*;q=0.1"
        ),
    }[kind]


def _cache_busted_url(value: str) -> str:
    parsed = urlparse(value)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("_ts", str(time.time_ns())))
    return urlunparse(
        parsed._replace(query=urlencode(query))
    )


def _validate_url(value: str, *, allowed_host: str) -> None:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme.casefold() != "https":
        raise FedOfficialSourceError(
            "official source URL must use HTTPS"
        )
    if str(parsed.hostname or "").casefold() != allowed_host.casefold():
        raise FedOfficialSourceError(
            "official source URL left the allowlisted host"
        )
    if parsed.username or parsed.password:
        raise FedOfficialSourceError(
            "official source URL cannot contain credentials"
        )
    if parsed.port not in {None, 443}:
        raise FedOfficialSourceError(
            "official source URL cannot use a custom port"
        )
    if parsed.fragment:
        raise FedOfficialSourceError(
            "official source URL cannot contain a fragment"
        )
