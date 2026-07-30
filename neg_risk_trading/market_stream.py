from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from neg_risk_trading.stream import (
    LocalBookRegistry,
    StreamContractError,
    StreamStatus,
    StreamUpdate,
)


MARKET_STREAM_URL = (
    "wss://ws-subscriptions-clob.polymarket.com/ws/market"
)


class MarketStreamTransportError(RuntimeError):
    """A sanitized public WebSocket transport failure."""

    def __init__(self, reason_code: str):
        normalized = str(reason_code or "").strip()
        if not normalized:
            raise ValueError("reason_code is required")
        super().__init__(normalized)
        self.reason_code = normalized


@dataclass(frozen=True)
class MarketStreamRun:
    epoch: int
    message_count: int
    update_count: int
    reached_ready: bool
    status_at_exit: StreamStatus


UpdateHandler = Callable[
    [StreamUpdate],
    None | Awaitable[None],
]


class PolymarketMarketStream:
    """One bounded public market-channel connection."""

    def __init__(
        self,
        *,
        heartbeat_seconds: float = 10.0,
        bootstrap_timeout_seconds: float = 15.0,
        maximum_message_bytes: int = 8 * 1024 * 1024,
        connector: Callable[..., Any] | None = None,
    ):
        if heartbeat_seconds <= 0:
            raise ValueError(
                "heartbeat_seconds must be positive"
            )
        if bootstrap_timeout_seconds <= 0:
            raise ValueError(
                "bootstrap_timeout_seconds must be positive"
            )
        if maximum_message_bytes <= 0:
            raise ValueError(
                "maximum_message_bytes must be positive"
            )
        self._heartbeat_seconds = float(heartbeat_seconds)
        self._bootstrap_timeout_seconds = float(
            bootstrap_timeout_seconds
        )
        self._maximum_message_bytes = int(
            maximum_message_bytes
        )
        self._connector = connector

    async def run_once(
        self,
        registry: LocalBookRegistry,
        *,
        on_update: UpdateHandler | None = None,
        maximum_messages: int | None = None,
        stop_when_ready: bool = False,
    ) -> MarketStreamRun:
        if (
            maximum_messages is not None
            and maximum_messages <= 0
        ):
            raise ValueError("maximum_messages must be positive")
        epoch = registry.begin_epoch()
        message_count = 0
        update_count = 0
        reached_ready = False
        status_at_exit = registry.status
        heartbeat: asyncio.Task[None] | None = None
        try:
            connector = self._connector or _default_connector()
            async with connector(
                MARKET_STREAM_URL,
                open_timeout=self._bootstrap_timeout_seconds,
                ping_interval=None,
                max_size=self._maximum_message_bytes,
                compression=None,
            ) as socket:
                await socket.send(
                    json.dumps(
                        {
                            "assets_ids": list(
                                registry.asset_ids
                            ),
                            "type": "market",
                            "custom_feature_enabled": True,
                            "initial_dump": True,
                        },
                        separators=(",", ":"),
                    )
                )
                heartbeat = asyncio.create_task(
                    self._heartbeat(socket)
                )
                loop = asyncio.get_running_loop()
                bootstrap_deadline = (
                    loop.time()
                    + self._bootstrap_timeout_seconds
                )

                while True:
                    timeout: float | None = None
                    if not registry.ready:
                        timeout = max(
                            0.001,
                            bootstrap_deadline - loop.time(),
                        )
                    else:
                        timeout = self._heartbeat_seconds * 2.5
                    try:
                        raw_message = await asyncio.wait_for(
                            socket.recv(),
                            timeout=timeout,
                        )
                    except TimeoutError as exc:
                        raise MarketStreamTransportError(
                            (
                                "market_stream_bootstrap_timeout"
                                if not registry.ready
                                else "market_stream_heartbeat_timeout"
                            )
                        ) from exc
                    if raw_message == "PONG":
                        continue
                    payload = _decode_message(
                        raw_message,
                        maximum_message_bytes=(
                            self._maximum_message_bytes
                        ),
                    )
                    updates = registry.apply_message(payload)
                    message_count += 1
                    update_count += len(updates)
                    reached_ready = (
                        reached_ready or registry.ready
                    )
                    if on_update is not None:
                        for update in updates:
                            result = on_update(update)
                            if inspect.isawaitable(result):
                                await result
                    if (
                        stop_when_ready
                        and registry.ready
                    ) or (
                        maximum_messages is not None
                        and message_count >= maximum_messages
                    ):
                        status_at_exit = registry.status
                        return MarketStreamRun(
                            epoch=epoch,
                            message_count=message_count,
                            update_count=update_count,
                            reached_ready=reached_ready,
                            status_at_exit=status_at_exit,
                        )
        except asyncio.CancelledError:
            raise
        except StreamContractError as exc:
            registry.mark_suspect(str(exc))
            raise
        except MarketStreamTransportError:
            raise
        except Exception as exc:
            raise MarketStreamTransportError(
                "market_stream_transport_failed"
            ) from exc
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            if registry.status not in {
                StreamStatus.SUSPECT,
                StreamStatus.HALTED,
            }:
                registry.disconnect()

        status_at_exit = registry.status
        return MarketStreamRun(
            epoch=epoch,
            message_count=message_count,
            update_count=update_count,
            reached_ready=reached_ready,
            status_at_exit=status_at_exit,
        )

    async def _heartbeat(self, socket: Any) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            await socket.send("PING")


def _default_connector() -> Callable[..., Any]:
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise MarketStreamTransportError(
            "market_stream_requires_websockets"
        ) from exc
    return connect


def _decode_message(
    value: object,
    *,
    maximum_message_bytes: int,
) -> object:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raise StreamContractError(
            "market_stream_message_type_invalid"
        )
    if len(raw) > maximum_message_bytes:
        raise StreamContractError(
            "market_stream_message_too_large"
        )
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise StreamContractError(
            "market_stream_json_invalid"
        ) from exc
