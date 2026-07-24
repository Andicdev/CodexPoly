from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable, Sequence

from cbr_trading.execution.order_supervisor import (
    SupervisionResult,
    TickSizeChange,
)


class TickSizeObservationSource(str, Enum):
    """Non-secret evidence that established the current tick size."""

    MARKET_CHANNEL_EVENT = "market_channel_event"
    MARKET_CHANNEL_BOOK = "market_channel_book"
    MARKET_CHANNEL_BOOK_LEVEL = "market_channel_book_level"
    MARKET_CHANNEL_PRICE_LEVEL = "market_channel_price_level"
    PERIODIC_BOOK = "periodic_book"


@dataclass(frozen=True)
class TickSizeWatch:
    """One supported, policy-backed tick transition for an asset."""

    asset_id: str
    old_tick: Decimal
    new_tick: Decimal

    def __post_init__(self) -> None:
        asset_id = str(self.asset_id or "").strip()
        if not asset_id:
            raise ValueError("asset_id is required")
        old_tick = Decimal(str(self.old_tick))
        new_tick = Decimal(str(self.new_tick))
        if old_tick <= 0 or new_tick <= 0:
            raise ValueError("tick sizes must be positive")
        if new_tick >= old_tick:
            raise ValueError("new_tick must be finer than old_tick")
        object.__setattr__(self, "asset_id", asset_id)
        object.__setattr__(self, "old_tick", old_tick)
        object.__setattr__(self, "new_tick", new_tick)


@dataclass(frozen=True)
class TickSizeObservation:
    """A source-neutral observation of one asset's tick size."""

    asset_id: str
    tick_size: Decimal
    observed_at: datetime
    source: TickSizeObservationSource
    reported_old_tick: Decimal | None = None

    def __post_init__(self) -> None:
        asset_id = str(self.asset_id or "").strip()
        if not asset_id:
            raise ValueError("asset_id is required")
        tick_size = Decimal(str(self.tick_size))
        if tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        source = self.source
        if not isinstance(source, TickSizeObservationSource):
            source = TickSizeObservationSource(str(source))
        reported_old_tick = self.reported_old_tick
        if reported_old_tick is not None:
            reported_old_tick = Decimal(str(reported_old_tick))
            if reported_old_tick <= 0:
                raise ValueError("reported_old_tick must be positive")

        object.__setattr__(self, "asset_id", asset_id)
        object.__setattr__(self, "tick_size", tick_size)
        object.__setattr__(
            self,
            "observed_at",
            self.observed_at.astimezone(timezone.utc),
        )
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "reported_old_tick", reported_old_tick)


@dataclass(frozen=True)
class TickSizeDispatch:
    event: TickSizeChange
    results: tuple[SupervisionResult, ...]


class TickSizeChangeDetector:
    """Deduplicate confirmed tick transitions before supervisor dispatch."""

    def __init__(self, watches: Sequence[TickSizeWatch]):
        normalized = tuple(watches)
        if not normalized:
            raise ValueError("at least one tick-size watch is required")
        by_asset: dict[str, TickSizeWatch] = {}
        for watch in normalized:
            if not isinstance(watch, TickSizeWatch):
                raise TypeError("watches must contain TickSizeWatch values")
            if watch.asset_id in by_asset:
                raise ValueError(
                    f"duplicate tick-size watch for asset {watch.asset_id}"
                )
            by_asset[watch.asset_id] = watch
        self._watches = by_asset
        self._current = {
            asset_id: watch.old_tick
            for asset_id, watch in by_asset.items()
        }
        self._lock = threading.RLock()

    @property
    def asset_ids(self) -> tuple[str, ...]:
        return tuple(self._watches)

    def current_tick(self, asset_id: str) -> Decimal | None:
        normalized = str(asset_id or "").strip()
        with self._lock:
            return self._current.get(normalized)

    def expected_new_tick(self, asset_id: str) -> Decimal | None:
        normalized = str(asset_id or "").strip()
        with self._lock:
            watch = self._watches.get(normalized)
            if watch is None:
                return None
            if self._current[normalized] != watch.old_tick:
                return None
            return watch.new_tick

    def dispatch(
        self,
        observation: TickSizeObservation,
        handler: Callable[
            [TickSizeChange],
            Sequence[SupervisionResult],
        ],
    ) -> TickSizeDispatch | None:
        if not isinstance(observation, TickSizeObservation):
            raise TypeError("observation must be a TickSizeObservation")
        if not callable(handler):
            raise TypeError("handler must be callable")

        with self._lock:
            watch = self._watches.get(observation.asset_id)
            if watch is None:
                return None
            current_tick = self._current[observation.asset_id]
            if observation.tick_size == current_tick:
                return None
            if (
                current_tick != watch.old_tick
                or observation.tick_size != watch.new_tick
            ):
                return None
            if (
                observation.reported_old_tick is not None
                and observation.reported_old_tick != current_tick
            ):
                return None

            event = TickSizeChange(
                event_id=_event_id(
                    asset_id=observation.asset_id,
                    old_tick=current_tick,
                    new_tick=observation.tick_size,
                ),
                asset_id=observation.asset_id,
                old_tick=current_tick,
                new_tick=observation.tick_size,
                observed_at=observation.observed_at,
                source=observation.source.value,
            )
            results = tuple(handler(event))
            self._current[observation.asset_id] = observation.tick_size
            return TickSizeDispatch(event=event, results=results)


def _event_id(
    *,
    asset_id: str,
    old_tick: Decimal,
    new_tick: Decimal,
) -> str:
    return (
        "tick-size-change:"
        f"{asset_id}:"
        f"{_canonical_decimal(old_tick)}:"
        f"{_canonical_decimal(new_tick)}"
    )


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")
