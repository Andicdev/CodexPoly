from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from cbr_trading.execution.order_supervisor import OrderSupervisor
from cbr_trading.execution.tick_size_detector import (
    TickSizeChangeDetector,
    TickSizeDispatch,
    TickSizeObservation,
    TickSizeObservationSource,
)
from cbr_trading.secret_guard import redact_exception


class MarketChannelError(RuntimeError):
    """Sanitized failure at the public market-channel boundary."""


class PolymarketTickObservationAdapter:
    """Translate official SDK market events and books into tick evidence."""

    def __init__(
        self,
        *,
        detector: TickSizeChangeDetector,
        clock: Callable[[], datetime] | None = None,
    ):
        self._detector = detector
        self._clock = clock or _utc_now

    def observation_for_event(
        self,
        event: Any,
    ) -> TickSizeObservation | None:
        observations = self.observations_for_event(event)
        return observations[0] if observations else None

    def observations_for_event(
        self,
        event: Any,
    ) -> tuple[TickSizeObservation, ...]:
        event_type = str(getattr(event, "type", "") or "").strip()
        payload = getattr(event, "payload", None)
        if event_type == "tick_size_change":
            return (
                TickSizeObservation(
                    asset_id=_asset_id(payload),
                    tick_size=Decimal(str(payload.new_tick_size)),
                    reported_old_tick=_optional_decimal(
                        getattr(payload, "old_tick_size", None)
                    ),
                    observed_at=self._observed_at(payload),
                    source=(
                        TickSizeObservationSource.MARKET_CHANNEL_EVENT
                    ),
                ),
            )
        if event_type == "book":
            observation = self.observation_for_book(
                payload,
                source=TickSizeObservationSource.MARKET_CHANNEL_BOOK,
            )
            return (observation,) if observation is not None else ()
        if event_type == "price_change":
            return self._observations_for_price_change(payload)
        return ()

    def observation_for_book(
        self,
        book: Any,
        *,
        source: TickSizeObservationSource,
    ) -> TickSizeObservation | None:
        asset_id = _asset_id(book)
        observed_at = self._observed_at(book)
        explicit_tick = _optional_decimal(
            getattr(book, "tick_size", None)
        )
        if explicit_tick is not None:
            return TickSizeObservation(
                asset_id=asset_id,
                tick_size=explicit_tick,
                observed_at=observed_at,
                source=source,
            )

        current_tick = self._detector.current_tick(asset_id)
        expected_tick = self._detector.expected_new_tick(asset_id)
        if current_tick is None or expected_tick is None:
            return None
        if _book_proves_expected_tick(
            book,
            current_tick=current_tick,
            expected_tick=expected_tick,
        ):
            evidence_source = (
                TickSizeObservationSource.PERIODIC_BOOK
                if source == TickSizeObservationSource.PERIODIC_BOOK
                else TickSizeObservationSource.MARKET_CHANNEL_BOOK_LEVEL
            )
            return TickSizeObservation(
                asset_id=asset_id,
                tick_size=expected_tick,
                observed_at=observed_at,
                source=evidence_source,
            )
        return None

    def _observations_for_price_change(
        self,
        payload: Any,
    ) -> tuple[TickSizeObservation, ...]:
        observed_at = self._observed_at(payload)
        observations: list[TickSizeObservation] = []
        seen_assets: set[str] = set()
        for change in tuple(
            getattr(payload, "price_changes", ()) or ()
        ):
            asset_id = _asset_id(change)
            if asset_id in seen_assets:
                continue
            current_tick = self._detector.current_tick(asset_id)
            expected_tick = self._detector.expected_new_tick(asset_id)
            if current_tick is None or expected_tick is None:
                continue
            try:
                size = Decimal(str(change.size))
                price = Decimal(str(change.price))
            except (AttributeError, InvalidOperation, ValueError):
                continue
            if (
                size > 0
                and _price_proves_expected_tick(
                    price,
                    current_tick=current_tick,
                    expected_tick=expected_tick,
                )
            ):
                observations.append(
                    TickSizeObservation(
                        asset_id=asset_id,
                        tick_size=expected_tick,
                        observed_at=observed_at,
                        source=(
                            TickSizeObservationSource
                            .MARKET_CHANNEL_PRICE_LEVEL
                        ),
                    )
                )
                seen_assets.add(asset_id)
        return tuple(observations)

    def _observed_at(self, value: Any) -> datetime:
        timestamp = getattr(value, "timestamp", None)
        if timestamp is None:
            timestamp = self._clock()
        if not isinstance(timestamp, datetime):
            raise ValueError("market timestamp must be a datetime")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("market timestamp must be timezone-aware")
        return timestamp.astimezone(timezone.utc)


class PolymarketMarketChannel:
    """Route public SDK market events into the source-neutral supervisor."""

    def __init__(
        self,
        *,
        detector: TickSizeChangeDetector,
        supervisor: OrderSupervisor,
        client_factory: Callable[[], Any] | None = None,
        logger: logging.Logger | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._detector = detector
        self._supervisor = supervisor
        self._client_factory = client_factory
        self._logger = logger or logging.getLogger(__name__)
        self._adapter = PolymarketTickObservationAdapter(
            detector=detector,
            clock=clock,
        )
        self._client: Any | None = None
        self._handle: Any | None = None
        self._running = False
        self._stop_requested = False

    async def run(self) -> tuple[TickSizeDispatch, ...]:
        if self._running:
            raise RuntimeError("market channel is already running")
        if self._stop_requested:
            return ()
        self._running = True
        dispatches: list[TickSizeDispatch] = []
        client: Any | None = None
        handle: Any | None = None
        try:
            client = self._new_client()
            self._client = client
            if self._stop_requested:
                return ()
            spec = await asyncio.to_thread(
                self._market_spec,
                self._detector.asset_ids,
            )
            handle = await client.subscribe(spec)
            self._handle = handle
            if self._stop_requested:
                return ()

            async for event in handle:
                if self._stop_requested:
                    break
                try:
                    event_dispatches = await asyncio.to_thread(
                        self.process_event,
                        event,
                    )
                except Exception as exc:
                    self._logger.warning(
                        "market-channel event failed: %s",
                        redact_exception(exc),
                    )
                    continue
                dispatches.extend(event_dispatches)
            return tuple(dispatches)
        except Exception as exc:
            if self._stop_requested:
                return tuple(dispatches)
            raise MarketChannelError(redact_exception(exc)) from None
        finally:
            self._handle = None
            self._client = None
            await _close_safely(
                handle,
                logger=self._logger,
                label="market subscription",
            )
            await _close_safely(
                client,
                logger=self._logger,
                label="public market client",
            )
            self._running = False

    def process_event(self, event: Any) -> tuple[TickSizeDispatch, ...]:
        dispatches: list[TickSizeDispatch] = []
        for observation in self._adapter.observations_for_event(event):
            try:
                dispatch = self._detector.dispatch(
                    observation,
                    self._supervisor.on_tick_size_change,
                )
            except Exception as exc:
                self._logger.warning(
                    "tick observation dispatch failed asset=%s: %s",
                    observation.asset_id,
                    redact_exception(exc),
                )
                continue
            if dispatch is not None:
                dispatches.append(dispatch)
        return tuple(dispatches)

    async def close(self) -> None:
        self._stop_requested = True
        await _close_safely(
            self._handle,
            logger=self._logger,
            label="market subscription",
        )
        await _close_safely(
            self._client,
            logger=self._logger,
            label="public market client",
        )

    def _new_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        try:
            from polymarket import AsyncPublicClient
        except ImportError as exc:
            raise MarketChannelError(
                "market channel requires polymarket-client"
            ) from exc
        return AsyncPublicClient(logger=self._logger)

    @staticmethod
    def _market_spec(asset_ids: tuple[str, ...]) -> Any:
        try:
            from polymarket.streams import MarketSpec
        except ImportError as exc:
            raise MarketChannelError(
                "market channel requires polymarket-client"
            ) from exc
        return MarketSpec(
            token_ids=asset_ids,
            custom_feature_enabled=False,
        )


def _asset_id(value: Any) -> str:
    asset_id = str(
        getattr(
            value,
            "token_id",
            getattr(value, "asset_id", ""),
        )
        or ""
    ).strip()
    if not asset_id:
        raise ValueError("market event has no asset_id")
    return asset_id


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    normalized = Decimal(str(value))
    if normalized <= 0:
        raise ValueError("tick size must be positive")
    return normalized


def _book_proves_expected_tick(
    book: Any,
    *,
    current_tick: Decimal,
    expected_tick: Decimal,
) -> bool:
    for side in ("bids", "asks"):
        for level in tuple(getattr(book, side, ()) or ()):
            try:
                price = Decimal(str(level.price))
                size = Decimal(str(getattr(level, "size", "1")))
            except (AttributeError, InvalidOperation, ValueError):
                continue
            if (
                size > 0
                and _price_proves_expected_tick(
                    price,
                    current_tick=current_tick,
                    expected_tick=expected_tick,
                )
            ):
                return True
    return False


def _price_proves_expected_tick(
    price: Decimal,
    *,
    current_tick: Decimal,
    expected_tick: Decimal,
) -> bool:
    return (
        Decimal("0") < price < Decimal("1")
        and price % current_tick != 0
        and price % expected_tick == 0
    )


async def _close_safely(
    value: Any,
    *,
    logger: logging.Logger,
    label: str,
) -> None:
    if value is None:
        return
    close = getattr(value, "close", None)
    if not callable(close):
        return
    try:
        result = close()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.warning(
            "%s close failed: %s",
            label,
            redact_exception(exc),
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
