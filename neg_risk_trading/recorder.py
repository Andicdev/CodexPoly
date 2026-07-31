from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from neg_risk_trading.domain import (
    MarketSnapshot,
    NegRiskContractError,
    RouteDirection,
)
from neg_risk_trading.market_stream import (
    MarketStreamTransportError,
    PolymarketMarketStream,
)
from neg_risk_trading.polymarket import (
    PolymarketPublicClient,
)
from neg_risk_trading.repository import (
    ObservationRepositoryError,
    RecordedStreamMessage,
    SqlAlchemyObservationRepository,
    StreamSessionStart,
)
from neg_risk_trading.replay import event_contract_payload
from neg_risk_trading.scanner import evaluate_snapshot
from neg_risk_trading.settings import NegRiskRecorderSettings
from neg_risk_trading.stream import (
    LocalBookRegistry,
    StreamContractError,
    StreamStatus,
    StreamUpdate,
    asset_configs_from_books,
)


_STOP = object()


class StreamObservationCollector:
    """Build immutable DB records without performing database I/O."""

    def __init__(
        self,
        *,
        registry: LocalBookRegistry,
        quantities: tuple[Decimal, ...],
        route_sample_interval_ms: int,
        queue: asyncio.Queue[RecordedStreamMessage | object],
        route_directions: tuple[RouteDirection, ...] = (
            RouteDirection.MAKER_BUY,
            RouteDirection.MAKER_SELL,
        ),
    ):
        self._registry = registry
        self._event = registry.event
        self._quantities = quantities
        self._route_directions = route_directions
        self._route_sample_interval_ms = int(
            route_sample_interval_ms
        )
        self._queue = queue
        self._sequence_by_epoch: dict[int, int] = {}
        self._last_route_at_ms: int | None = None
        self._yes_asset_ids = {
            market.yes_token_id
            for market in self._event.markets
        }

    def on_message(
        self,
        payload: object,
        updates: tuple[StreamUpdate, ...],
    ) -> None:
        if not updates:
            raise StreamContractError(
                "shadow_recorder_update_missing"
            )
        if all(
            update.event_type == "new_market"
            and not update.affected_asset_ids
            for update in updates
        ):
            return
        epoch = self._registry.epoch
        sequence = self._sequence_by_epoch.get(epoch, 0) + 1
        self._sequence_by_epoch[epoch] = sequence
        received_at_ms = max(
            update.received_at_ms
            for update in updates
        )
        route_evaluation = self._route_evaluation(
            updates=updates,
            received_at_ms=received_at_ms,
        )
        record = RecordedStreamMessage(
            connection_epoch=epoch,
            message_sequence=sequence,
            received_at=datetime.fromtimestamp(
                received_at_ms / 1000,
                tz=timezone.utc,
            ),
            payload=payload,
            updates=updates,
            route_evaluation=route_evaluation,
        )
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull as exc:
            raise StreamContractError(
                "shadow_recorder_queue_full"
            ) from exc

    def _route_evaluation(
        self,
        *,
        updates: tuple[StreamUpdate, ...],
        received_at_ms: int,
    ) -> Mapping[str, object] | None:
        if not self._registry.ready:
            return None
        affected = {
            asset_id
            for update in updates
            for asset_id in update.affected_asset_ids
        }
        if not affected.intersection(self._yes_asset_ids):
            return None
        if (
            self._last_route_at_ms is not None
            and received_at_ms - self._last_route_at_ms
            < self._route_sample_interval_ms
        ):
            return None
        books = {
            market.condition_id: self._registry.view(
                market.yes_token_id
            ).as_order_book()
            for market in self._event.markets
        }
        snapshot = MarketSnapshot(
            event=self._event,
            books=books,
            requested_at_ms=received_at_ms,
            received_at_ms=received_at_ms,
            gamma_duration_ms=0,
            books_duration_ms=0,
        )
        evaluation = evaluate_snapshot(
            snapshot,
            quantities=self._quantities,
            route_directions=self._route_directions,
        )
        self._last_route_at_ms = received_at_ms
        return evaluation


class AsyncObservationWriter:
    """Flush a bounded queue in DB batches outside market processing."""

    def __init__(
        self,
        *,
        repository: SqlAlchemyObservationRepository,
        session_id: Any,
        queue: asyncio.Queue[RecordedStreamMessage | object],
        batch_size: int,
        flush_interval_seconds: float,
    ):
        self._repository = repository
        self._session_id = session_id
        self._queue = queue
        self._batch_size = int(batch_size)
        self._flush_interval_seconds = float(
            flush_interval_seconds
        )
        self._closing = False

    async def run(self) -> None:
        while True:
            first = await self._queue.get()
            if first is _STOP:
                self._queue.task_done()
                return
            if not isinstance(first, RecordedStreamMessage):
                self._queue.task_done()
                raise RuntimeError(
                    "observation queue item is invalid"
                )
            batch = [first]
            stop_after_batch = False
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._flush_interval_seconds
            while len(batch) < self._batch_size:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    item = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=remaining,
                    )
                except TimeoutError:
                    break
                if item is _STOP:
                    self._queue.task_done()
                    stop_after_batch = True
                    break
                if not isinstance(item, RecordedStreamMessage):
                    self._queue.task_done()
                    raise RuntimeError(
                        "observation queue item is invalid"
                    )
                batch.append(item)
            await asyncio.to_thread(
                self._repository.append_batch,
                session_id=self._session_id,
                messages=batch,
            )
            for _item in batch:
                self._queue.task_done()
            if stop_after_batch:
                return

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        await self._queue.put(_STOP)


class ContinuousShadowRecorder:
    def __init__(
        self,
        *,
        settings: NegRiskRecorderSettings,
        repository: SqlAlchemyObservationRepository | None = None,
        public_client: PolymarketPublicClient | None = None,
        stream: PolymarketMarketStream | None = None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._repository = repository or (
            SqlAlchemyObservationRepository(
                settings.database_url
            )
        )
        self._public_client = (
            public_client or PolymarketPublicClient()
        )
        self._stream = stream or PolymarketMarketStream(
            heartbeat_seconds=settings.heartbeat_seconds,
            bootstrap_timeout_seconds=(
                settings.bootstrap_timeout_seconds
            ),
        )
        self._logger = logger or logging.getLogger(__name__)

    async def run(self) -> None:
        bootstrap = await asyncio.to_thread(
            self._public_client.fetch_stream_bootstrap,
            self._settings.event_slug,
        )
        asset_configs = asset_configs_from_books(
            event=bootstrap.event,
            books=bootstrap.books,
        )
        await asyncio.to_thread(self._repository.ensure_ready)
        started_at = _utc_now()
        session_id = await asyncio.to_thread(
            self._repository.start_session,
            StreamSessionStart(
                event_id=bootstrap.event.event_id,
                event_slug=bootstrap.event.slug,
                market_count=len(bootstrap.event.markets),
                asset_count=len(bootstrap.event.asset_ids),
                started_at=started_at,
                metadata={
                    "gamma_duration_ms": (
                        bootstrap.gamma_duration_ms
                    ),
                    "books_duration_ms": (
                        bootstrap.books_duration_ms
                    ),
                    "quantities": [
                        format(quantity, "f")
                        for quantity in self._settings.quantities
                    ],
                    "route_directions": [
                        direction.value
                        for direction
                        in self._settings.route_directions
                    ],
                    "route_sample_interval_ms": (
                        self._settings.route_sample_interval_ms
                    ),
                    "event_contract": event_contract_payload(
                        event=bootstrap.event,
                        assets=asset_configs,
                    ),
                },
            ),
        )
        registry = LocalBookRegistry(
            event=bootstrap.event,
            assets=asset_configs,
            clock_ms=_epoch_ms,
        )
        queue: asyncio.Queue[RecordedStreamMessage | object] = (
            asyncio.Queue(
                maxsize=self._settings.queue_capacity
            )
        )
        collector = StreamObservationCollector(
            registry=registry,
            quantities=self._settings.quantities,
            route_directions=self._settings.route_directions,
            route_sample_interval_ms=(
                self._settings.route_sample_interval_ms
            ),
            queue=queue,
        )
        writer = AsyncObservationWriter(
            repository=self._repository,
            session_id=session_id,
            queue=queue,
            batch_size=self._settings.write_batch_size,
            flush_interval_seconds=(
                self._settings.flush_interval_seconds
            ),
        )
        writer_task = asyncio.create_task(writer.run())
        terminal_status = "STOPPED"
        terminal_reason: str | None = None
        reconnect_delay = (
            self._settings.reconnect_initial_seconds
        )
        try:
            while True:
                reconnect_diagnostics: Mapping[
                    str, object
                ] = {}
                stream_task = asyncio.create_task(
                    self._stream.run_once(
                        registry,
                        on_message=collector.on_message,
                    )
                )
                done, _pending = await asyncio.wait(
                    {stream_task, writer_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if writer_task in done:
                    stream_task.cancel()
                    await _await_cancelled(stream_task)
                    await writer_task
                    raise ObservationRepositoryError(
                        "Observation writer stopped unexpectedly"
                    )
                try:
                    await stream_task
                except asyncio.CancelledError:
                    raise
                except (
                    MarketStreamTransportError,
                    StreamContractError,
                ) as exc:
                    terminal_reason = _reason_code(exc)
                    raw_diagnostics = getattr(
                        exc,
                        "diagnostics",
                        {},
                    )
                    if isinstance(raw_diagnostics, Mapping):
                        reconnect_diagnostics = dict(
                            raw_diagnostics
                        )
                if registry.status is StreamStatus.HALTED:
                    terminal_status = "HALTED"
                    terminal_reason = (
                        registry.reason_code or "market_resolved"
                    )
                    break
                epoch_reached_ready = (
                    registry.epoch_reached_ready
                )
                if epoch_reached_ready:
                    reconnect_delay = (
                        self._settings.reconnect_initial_seconds
                    )
                reconnect_diagnostics.update(
                    {
                        "epoch_reached_ready": (
                            epoch_reached_ready
                        ),
                        "reconnect_delay_seconds": (
                            reconnect_delay
                        ),
                    }
                )
                await asyncio.to_thread(
                    self._repository.mark_reconnecting,
                    session_id=session_id,
                    reason_code=(
                        terminal_reason
                        or "market_stream_reconnecting"
                    ),
                    connection_epoch=registry.epoch,
                    observed_at=_utc_now(),
                    diagnostics=reconnect_diagnostics,
                )
                self._logger.warning(
                    "Neg-risk market stream reconnecting "
                    "reason=%s delay_seconds=%.3f",
                    terminal_reason or "stream_ended",
                    reconnect_delay,
                )
                await asyncio.sleep(reconnect_delay)
                if not epoch_reached_ready:
                    reconnect_delay = min(
                        self._settings.reconnect_max_seconds,
                        reconnect_delay * 2,
                    )
        except asyncio.CancelledError:
            terminal_status = "STOPPED"
            terminal_reason = "recorder_cancelled"
            raise
        except Exception as exc:
            terminal_status = "ERROR"
            terminal_reason = _reason_code(exc)
            raise
        finally:
            if not writer_task.done():
                await writer.close()
                await writer_task
            else:
                try:
                    await writer_task
                except Exception:
                    if terminal_status != "ERROR":
                        terminal_status = "ERROR"
                        terminal_reason = (
                            "observation_writer_failed"
                        )
            await asyncio.to_thread(
                self._repository.finish_session,
                session_id=session_id,
                status=terminal_status,
                reason_code=terminal_reason,
                ended_at=_utc_now(),
            )
            self._repository.close()


async def _await_cancelled(task: asyncio.Task[Any]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        return


def _reason_code(exc: BaseException) -> str:
    reason = getattr(exc, "reason_code", None)
    if reason:
        return str(reason)[:160]
    if isinstance(exc, NegRiskContractError):
        return str(exc)[:160]
    return type(exc).__name__.lower()[:160]


def _epoch_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
