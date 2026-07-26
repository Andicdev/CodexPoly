from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

from cbr_trading.sec_filings.contracts import (
    SecFilingEnvelope,
    normalize_sec_filing,
)


SEC_STREAM_ENDPOINT = "wss://stream.sec-api.io"


class SecStreamTransportError(RuntimeError):
    """Sanitized SEC transport failure that cannot reveal its credential."""

    def __init__(
        self,
        message: str,
        *,
        diagnostic_code: str | None = None,
    ):
        super().__init__(message)
        self.diagnostic_code = (
            str(diagnostic_code or "").strip()
            or type(self).__name__
        )


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


class SecStreamTransport:
    """Yield source-neutral filing envelopes from one SEC WebSocket."""

    def __init__(
        self,
        *,
        api_key: str,
        connect_factory: ConnectFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        normalized_key = str(api_key or "").strip()
        if not normalized_key:
            raise ValueError("SEC API credential is required")
        self._api_key = normalized_key
        self._connect_factory = connect_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            "credential=[REDACTED], "
            f"custom_connector={self._connect_factory is not None})"
        )

    async def stream_once(self) -> AsyncIterator[SecFilingEnvelope]:
        """Consume one connection; reconnect policy belongs to the worker."""

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
                        yield normalize_sec_filing(
                            filing,
                            received_at=received_at,
                        )
        except asyncio.CancelledError:
            raise
        except SecStreamTransportError:
            raise
        except Exception as exc:
            diagnostic_code = _stream_error_code(exc)
            raise SecStreamTransportError(
                "SEC filing stream failed: "
                f"{diagnostic_code}",
                diagnostic_code=diagnostic_code,
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


def _default_connect_factory() -> ConnectFactory:
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise SecStreamTransportError(
            "SEC stream support requires the websockets package"
        ) from exc
    return connect


def _stream_error_code(exc: BaseException) -> str:
    error_type = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if isinstance(status, int) and 100 <= status <= 599:
        return f"{error_type}:http_{status}"
    return error_type


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)
