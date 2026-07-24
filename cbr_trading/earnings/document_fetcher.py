from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
)


class SecDocumentFetchError(RuntimeError):
    """Sanitized failure while downloading a public SEC exhibit."""


class SecDocumentFetcher:
    """Download a bounded public SEC exhibit without forwarding credentials."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float,
        max_bytes: int,
        opener: Callable[..., Any] | None = None,
    ):
        normalized_agent = str(user_agent or "").strip()
        if not normalized_agent:
            raise ValueError("user_agent is required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        self._user_agent = normalized_agent
        self._timeout = float(timeout)
        self._max_bytes = int(max_bytes)
        self._opener = opener or urlopen

    def fetch(self, candidate: EarningsDocumentCandidate) -> bytes:
        if candidate.provider is not EarningsProvider.SEC:
            raise SecDocumentFetchError(
                "SEC document fetcher received a non-SEC candidate"
            )
        _require_sec_url(candidate.source_url)
        request = Request(
            candidate.source_url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "text/plain;q=0.9,*/*;q=0.1"
                ),
            },
            method="GET",
        )
        try:
            with self._opener(
                request,
                timeout=self._timeout,
            ) as response:
                final_url = str(
                    response.geturl()
                    if hasattr(response, "geturl")
                    else candidate.source_url
                )
                _require_sec_url(final_url)
                content_type = _content_type(response)
                if content_type and content_type not in {
                    "text/html",
                    "text/plain",
                    "application/xhtml+xml",
                    "application/xml",
                }:
                    raise SecDocumentFetchError(
                        "SEC exhibit has an unsupported content type"
                    )
                document = response.read(self._max_bytes + 1)
        except SecDocumentFetchError:
            raise
        except Exception as exc:
            raise SecDocumentFetchError(
                "SEC exhibit fetch failed: "
                f"{type(exc).__name__}"
            ) from None
        if not document:
            raise SecDocumentFetchError("SEC exhibit is empty")
        if len(document) > self._max_bytes:
            raise SecDocumentFetchError(
                "SEC exhibit exceeds the configured size limit"
            )
        return document


def _require_sec_url(value: str) -> None:
    parsed = urlparse(str(value or "").strip())
    hostname = str(parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https":
        raise SecDocumentFetchError(
            "SEC exhibit URL must use HTTPS"
        )
    if hostname != "sec.gov" and not hostname.endswith(".sec.gov"):
        raise SecDocumentFetchError(
            "SEC exhibit URL must use an SEC domain"
        )
    if parsed.username or parsed.password:
        raise SecDocumentFetchError(
            "SEC exhibit URL cannot contain credentials"
        )


def _content_type(response: Any) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    if hasattr(headers, "get_content_type"):
        return str(headers.get_content_type() or "").casefold() or None
    raw = str(headers.get("Content-Type") or "").split(";", 1)[0]
    return raw.strip().casefold() or None
