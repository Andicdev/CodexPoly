from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from cbr_trading.release import (
    DEFAULT_RELEASE_TIME_SUFFIX,
    build_predicted_release_url,
    extract_title,
    looks_like_key_rate_release,
    parse_release_rate_from_title,
)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class FetchResult:
    request_url: str
    status_code: int
    content_type: str
    text: str


class Transport(Protocol):
    def fetch_prefix(
        self,
        url: str,
        *,
        connect_timeout: float,
        read_timeout: float,
        max_bytes: int,
        chunk_size: int,
    ) -> FetchResult: ...

@dataclass(frozen=True)
class CbrClientConfig:
    release_time_suffix: str = DEFAULT_RELEASE_TIME_SUFFIX
    connect_timeout: float = 0.5
    read_timeout: float = 0.5
    prefix_max_bytes: int = 32768
    prefix_chunk_size: int = 2048
    cache_bust: bool = True


@dataclass(frozen=True)
class DiscoveryResult:
    ok: bool
    reason: str
    url: str
    request_url: str
    status_code: int | None = None
    content_type: str = ""
    title: str = ""
    new_rate: float | None = None
    raw_text: str = ""
    raw_preview: str = ""
    detected_from: str = "predicted_release_url"
    published_at: str | None = None
    error: str | None = None


class RequestsTransport:
    """Requests-based transport, imported lazily when instantiated."""

    def __init__(self, session: Any | None = None):
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "The 'requests' package is required for live CBR fetching."
            ) from exc

        self._requests = requests
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Connection": "keep-alive",
            }
        )

    def fetch_prefix(
        self,
        url: str,
        *,
        connect_timeout: float,
        read_timeout: float,
        max_bytes: int,
        chunk_size: int,
    ) -> FetchResult:
        with self._session.get(
            url,
            timeout=(connect_timeout, read_timeout),
            stream=True,
        ) as response:
            status_code = int(response.status_code)
            content_type = (
                response.headers.get("content-type") or ""
            ).lower()
            if status_code == 404:
                return FetchResult(url, status_code, content_type, "")
            response.raise_for_status()

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(
                chunk_size=chunk_size,
                decode_unicode=False,
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    break

            encoding = (
                response.encoding
                or response.apparent_encoding
                or "utf-8"
            )
            text = _decode_prefix(
                b"".join(chunks)[:max_bytes],
                declared_encoding=encoding,
            )
            return FetchResult(
                url,
                status_code,
                content_type,
                text,
            )

class CbrClient:
    def __init__(
        self,
        transport: Transport,
        config: CbrClientConfig | None = None,
    ):
        self.transport = transport
        self.config = config or CbrClientConfig()

    def discover_predicted_release(
        self,
        *,
        now: datetime | None = None,
        release_date: str | None = None,
    ) -> DiscoveryResult:
        url = build_predicted_release_url(
            now=now,
            release_date=release_date,
            release_time_suffix=self.config.release_time_suffix,
        )
        request_url = (
            _append_cache_buster(url)
            if self.config.cache_bust
            else url
        )

        try:
            prefix = self.transport.fetch_prefix(
                request_url,
                connect_timeout=self.config.connect_timeout,
                read_timeout=self.config.read_timeout,
                max_bytes=self.config.prefix_max_bytes,
                chunk_size=self.config.prefix_chunk_size,
            )
            if prefix.status_code == 404:
                return DiscoveryResult(
                    ok=False,
                    reason="not_published_yet",
                    url=url,
                    request_url=request_url,
                    status_code=404,
                    content_type=prefix.content_type,
                    published_at=release_date,
                )

            title = extract_title(prefix.text)
            new_rate = parse_release_rate_from_title(title)
            raw_preview = title[:4000]

            if (
                new_rate is None
                or not looks_like_key_rate_release(title)
            ):
                return DiscoveryResult(
                    ok=False,
                    reason="not_published_yet",
                    url=url,
                    request_url=request_url,
                    status_code=prefix.status_code,
                    content_type=prefix.content_type,
                    title=title,
                    raw_preview=raw_preview,
                    published_at=release_date,
                )

            return DiscoveryResult(
                ok=True,
                reason="published",
                url=url,
                request_url=request_url,
                status_code=prefix.status_code,
                content_type=prefix.content_type,
                title=title,
                new_rate=new_rate,
                raw_preview=raw_preview,
                published_at=release_date,
            )
        except Exception as exc:
            response = getattr(exc, "response", None)
            raw_status = getattr(response, "status_code", None)
            try:
                status_code = (
                    int(raw_status)
                    if raw_status is not None
                    else None
                )
            except (TypeError, ValueError):
                status_code = None
            return DiscoveryResult(
                ok=False,
                reason="fetch_failed",
                url=url,
                request_url=request_url,
                status_code=status_code,
                published_at=release_date,
                error=f"{type(exc).__name__}: {exc}",
            )


def _append_cache_buster(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}_ts={int(time.time() * 1000)}"


def _decode_prefix(
    payload: bytes,
    *,
    declared_encoding: str,
) -> str:
    """Decode CBR HTML, correcting its occasional false UTF-8 header."""
    encoding = declared_encoding or "utf-8"
    primary = payload.decode(encoding, errors="replace")
    if "\ufffd" not in primary:
        return primary

    cp1251 = payload.decode("cp1251", errors="replace")
    if cp1251.count("\ufffd") < primary.count("\ufffd"):
        return cp1251
    return primary
