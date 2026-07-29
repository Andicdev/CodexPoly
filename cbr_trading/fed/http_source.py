from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
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


@dataclass(frozen=True)
class FedRouteTelemetry:
    route_name: str
    attempts: int
    http_successes: int
    decisions: int
    last_status_code: int | None
    last_response_bytes: int
    last_fetch_ms: float
    last_parse_ms: float
    last_total_ms: float
    last_error_type: str | None


@dataclass
class _FedRouteTelemetryState:
    attempts: int = 0
    http_successes: int = 0
    decisions: int = 0
    last_status_code: int | None = None
    last_response_bytes: int = 0
    last_fetch_ms: float = 0.0
    last_parse_ms: float = 0.0
    last_total_ms: float = 0.0
    last_error_type: str | None = None


@dataclass
class _FedAttemptTrace:
    status_code: int | None = None
    response_bytes: int = 0
    fetch_ms: float = 0.0
    parse_ms: float = 0.0


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
    """Independently poll official documents and return the first decision."""

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
        primary_interval: float = 0.05,
        secondary_interval: float = 0.15,
        poll_wait: float = 0.05,
        logger: logging.Logger | None = None,
    ):
        if connect_timeout <= 0 or read_timeout <= 0:
            raise ValueError("HTTP timeouts must be positive")
        for name, value in (
            ("rss_interval", rss_interval),
            ("primary_interval", primary_interval),
            ("secondary_interval", secondary_interval),
            ("poll_wait", poll_wait),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        self.spec = spec
        self._transport = transport or RequestsFedRouteTransport()
        self._pdf_text_extractor = pdf_text_extractor
        if pdf_text_extractor is None:
            _warm_pdf_parser()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock
        self._timeout = (
            float(connect_timeout),
            float(read_timeout),
        )
        self._max_html_bytes = int(max_html_bytes)
        self._max_pdf_bytes = int(max_pdf_bytes)
        self._poll_wait = float(poll_wait)
        self._routes = _routes_from_spec(spec)
        self._route_intervals = {
            "fed_board_statement_html": float(primary_interval),
            "fed_board_statement_pdf": float(primary_interval),
            "fed_board_implementation_html": float(
                secondary_interval
            ),
            "new_york_fed_statement_pdf": float(
                secondary_interval
            ),
            "fed_monetary_policy_rss": float(rss_interval),
        }
        self._next_due = {
            route.name: float("-inf")
            for route in self._routes
        }
        self._inflight: dict[
            Future[FedOfficialObservation | None],
            FedDocumentRoute,
        ] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=len(self._routes),
            thread_name_prefix="fed-official-source",
        )
        self._logger = logger or logging.getLogger(
            "cbr_trading.fed.source"
        )
        self._telemetry_lock = Lock()
        self._telemetry = {
            route.name: _FedRouteTelemetryState()
            for route in self._routes
        }
        self._closed = False
        self._winner: FedOfficialObservation | None = None

    @property
    def winner(self) -> FedOfficialObservation | None:
        return self._winner

    @property
    def route_telemetry(self) -> tuple[FedRouteTelemetry, ...]:
        with self._telemetry_lock:
            return tuple(
                FedRouteTelemetry(
                    route_name=route.name,
                    attempts=state.attempts,
                    http_successes=state.http_successes,
                    decisions=state.decisions,
                    last_status_code=state.last_status_code,
                    last_response_bytes=state.last_response_bytes,
                    last_fetch_ms=state.last_fetch_ms,
                    last_parse_ms=state.last_parse_ms,
                    last_total_ms=state.last_total_ms,
                    last_error_type=state.last_error_type,
                )
                for route in self._routes
                for state in (self._telemetry[route.name],)
            )

    def poll_once(self) -> FedOfficialObservation | None:
        if self._closed:
            raise RuntimeError("Federal Reserve source poller is closed")
        if self._winner is not None:
            return self._winner

        observation = self._collect_completed()
        if observation is not None:
            return observation

        now = self._monotonic_clock()
        active_route_names = {
            route.name for route in self._inflight.values()
        }
        for route in self._routes:
            if route.name in active_route_names:
                continue
            if now < self._next_due[route.name]:
                continue
            future = self._executor.submit(
                self._fetch_and_parse,
                route,
            )
            self._inflight[future] = route
            self._next_due[route.name] = (
                now + self._route_intervals[route.name]
            )

        deadline = time.monotonic() + self._poll_wait
        while self._inflight:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            done, _pending = wait(
                tuple(self._inflight),
                timeout=remaining,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                break
            observation = self._collect_completed()
            if observation is not None:
                return observation
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for future in self._inflight:
            future.cancel()
        self._inflight.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._transport.close()

    def _collect_completed(
        self,
    ) -> FedOfficialObservation | None:
        for future, route in tuple(self._inflight.items()):
            if not future.done():
                continue
            del self._inflight[future]
            try:
                observation = future.result()
            except Exception as exc:
                self._logger.debug(
                    "FED source route failed route=%s error_type=%s",
                    route.name,
                    type(exc).__name__,
                )
                continue
            if observation is None:
                continue
            self._winner = observation
            for pending in self._inflight:
                pending.cancel()
            self._logger.info(
                "FED decision source confirmed provider=%s "
                "lower=%s upper=%s",
                observation.provider,
                observation.decision.lower,
                observation.decision.upper,
            )
            return observation
        return None

    def _fetch_and_parse(
        self,
        route: FedDocumentRoute,
    ) -> FedOfficialObservation | None:
        started = self._monotonic_clock()
        trace = _FedAttemptTrace()
        observation: FedOfficialObservation | None = None
        error_type: str | None = None
        try:
            observation = self._fetch_and_parse_route(route, trace)
            return observation
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            self._record_route_attempt(
                route=route,
                trace=trace,
                total_ms=max(
                    0.0,
                    (
                        self._monotonic_clock() - started
                    )
                    * 1000,
                ),
                decision_found=observation is not None,
                error_type=error_type,
            )

    def _fetch_and_parse_route(
        self,
        route: FedDocumentRoute,
        trace: _FedAttemptTrace,
    ) -> FedOfficialObservation | None:
        max_bytes = (
            self._max_pdf_bytes
            if route.kind is FedDocumentKind.PDF
            else self._max_html_bytes
        )
        fetch_started = self._monotonic_clock()
        response = self._transport.fetch(
            route,
            timeout=self._timeout,
            max_bytes=max_bytes,
        )
        trace.fetch_ms += max(
            0.0,
            (
                self._monotonic_clock() - fetch_started
            )
            * 1000,
        )
        trace.status_code = response.status_code
        trace.response_bytes += len(response.body)
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
            fetch_started = self._monotonic_clock()
            response = self._transport.fetch(
                route,
                timeout=self._timeout,
                max_bytes=self._max_html_bytes,
            )
            trace.fetch_ms += max(
                0.0,
                (
                    self._monotonic_clock() - fetch_started
                )
                * 1000,
            )
            trace.status_code = response.status_code
            trace.response_bytes += len(response.body)
            if response.status_code != 200 or not response.body:
                return None
        parse_started = self._monotonic_clock()
        try:
            _validate_content_type(route.kind, response.content_type)
            if route.kind is FedDocumentKind.PDF:
                return self._observation_from_pdf(route, response)
            text = html_visible_text(response.body)
            return self._observation_from_text(
                route,
                response,
                text,
            )
        finally:
            trace.parse_ms = max(
                0.0,
                (
                    self._monotonic_clock() - parse_started
                )
                * 1000,
            )

    def _record_route_attempt(
        self,
        *,
        route: FedDocumentRoute,
        trace: _FedAttemptTrace,
        total_ms: float,
        decision_found: bool,
        error_type: str | None,
    ) -> None:
        with self._telemetry_lock:
            state = self._telemetry[route.name]
            state.attempts += 1
            if (
                trace.status_code == 200
                and trace.response_bytes > 0
            ):
                state.http_successes += 1
            if decision_found:
                state.decisions += 1
            state.last_status_code = trace.status_code
            state.last_response_bytes = trace.response_bytes
            state.last_fetch_ms = round(trace.fetch_ms, 3)
            state.last_parse_ms = round(trace.parse_ms, 3)
            state.last_total_ms = round(total_ms, 3)
            state.last_error_type = error_type

    def _observation_from_pdf(
        self,
        route: FedDocumentRoute,
        response: FedRouteResponse,
    ) -> FedOfficialObservation | None:
        if self._pdf_text_extractor is not None:
            text = self._pdf_text_extractor(response.body)
            return self._observation_from_text(route, response, text)

        first_page = _extract_pdf_text(
            response.body,
            max_pages=1,
        )
        observation = self._observation_from_text(
            route,
            response,
            first_page,
        )
        if observation is not None:
            return observation
        full_text = _extract_pdf_text(
            response.body,
            max_pages=4,
        )
        return self._observation_from_text(
            route,
            response,
            full_text,
        )

    def _observation_from_text(
        self,
        route: FedDocumentRoute,
        response: FedRouteResponse,
        text: str,
    ) -> FedOfficialObservation | None:
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
        return FedOfficialObservation(
            provider=route.name,
            source_url=route.url,
            decision=decision,
            detected_at=detected_at,
            document_fingerprint=hashlib.sha256(
                response.body
            ).hexdigest(),
            excerpt=_decision_excerpt(text),
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
            name="fed_board_statement_pdf",
            url=spec.board_statement_pdf_url,
            kind=FedDocumentKind.PDF,
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


def _warm_pdf_parser() -> None:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        raise FedOfficialSourceError(
            "Federal Reserve PDF source requires pypdf"
        ) from None


def _extract_pdf_text(
    document: bytes,
    *,
    max_pages: int = 4,
) -> str:
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
            for page in reader.pages[:max_pages]
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
