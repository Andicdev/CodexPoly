from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from neg_risk_trading.domain import (
    BookLevel,
    NegRiskContractError,
    NegRiskEvent,
    OrderBook,
)


ONE = Decimal("1")
SUPPORTED_TICKS = (Decimal("0.01"), Decimal("0.001"))


class StreamStatus(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    READY = "READY"
    SUSPECT = "SUSPECT"
    RESYNCING = "RESYNCING"
    HALTED = "HALTED"


class StreamContractError(NegRiskContractError):
    """A public market event cannot safely update local state."""


@dataclass(frozen=True)
class StreamAssetConfig:
    asset_id: str
    condition_id: str
    minimum_order_size: Decimal
    tick_size: Decimal

    def __post_init__(self) -> None:
        asset_id = str(self.asset_id or "").strip()
        condition_id = str(self.condition_id or "").strip().lower()
        minimum_order_size = _decimal(
            self.minimum_order_size,
            reason_code="stream_minimum_order_size_invalid",
        )
        tick_size = _decimal(
            self.tick_size,
            reason_code="stream_tick_size_invalid",
        )
        if not asset_id.isdigit():
            raise StreamContractError("stream_asset_id_invalid")
        if not condition_id.startswith("0x"):
            raise StreamContractError(
                "stream_condition_id_invalid"
            )
        if minimum_order_size <= 0:
            raise StreamContractError(
                "stream_minimum_order_size_not_positive"
            )
        if tick_size not in SUPPORTED_TICKS:
            raise StreamContractError(
                "stream_tick_size_unsupported"
            )
        object.__setattr__(self, "asset_id", asset_id)
        object.__setattr__(self, "condition_id", condition_id)
        object.__setattr__(
            self,
            "minimum_order_size",
            minimum_order_size,
        )
        object.__setattr__(self, "tick_size", tick_size)


@dataclass(frozen=True)
class StreamBookView:
    asset_id: str
    condition_id: str
    timestamp_ms: int
    received_at_ms: int
    book_hash: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    minimum_order_size: Decimal
    tick_size: Decimal
    epoch: int
    update_count: int

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    def level_size(
        self,
        *,
        side: str,
        price: Decimal,
    ) -> Decimal:
        normalized_side = str(side or "").strip().upper()
        if normalized_side == "BUY":
            levels = self.bids
        elif normalized_side == "SELL":
            levels = self.asks
        else:
            raise ValueError("side must be BUY or SELL")
        normalized_price = _decimal(
            price,
            reason_code="queue_price_invalid",
        )
        return sum(
            (
                level.size
                for level in levels
                if level.price == normalized_price
            ),
            Decimal("0"),
        )

    def as_order_book(self) -> OrderBook:
        return OrderBook(
            condition_id=self.condition_id,
            asset_id=self.asset_id,
            timestamp_ms=self.timestamp_ms,
            book_hash=self.book_hash,
            bids=self.bids,
            asks=self.asks,
            minimum_order_size=self.minimum_order_size,
            tick_size=self.tick_size,
            neg_risk=True,
        )


@dataclass(frozen=True)
class StreamUpdate:
    event_type: str
    affected_asset_ids: tuple[str, ...]
    timestamp_ms: int | None
    received_at_ms: int
    status: StreamStatus
    became_ready: bool


@dataclass
class QueueAheadBounds:
    """Conservative FIFO bounds from aggregate public level data."""

    asset_id: str
    side: str
    price: Decimal
    own_remaining: Decimal
    ahead_lower: Decimal
    ahead_upper: Decimal
    last_aggregate_size: Decimal

    @classmethod
    def before_placement(
        cls,
        book: StreamBookView,
        *,
        side: str,
        price: Decimal,
        own_size: Decimal,
    ) -> QueueAheadBounds:
        normalized_side = str(side or "").strip().upper()
        normalized_price = _decimal(
            price,
            reason_code="queue_price_invalid",
        )
        normalized_size = _decimal(
            own_size,
            reason_code="queue_own_size_invalid",
        )
        if normalized_side not in {"BUY", "SELL"}:
            raise StreamContractError("queue_side_invalid")
        if normalized_size <= 0:
            raise StreamContractError(
                "queue_own_size_not_positive"
            )
        queue = book.level_size(
            side=normalized_side,
            price=normalized_price,
        )
        return cls(
            asset_id=book.asset_id,
            side=normalized_side,
            price=normalized_price,
            own_remaining=normalized_size,
            ahead_lower=queue,
            ahead_upper=queue,
            last_aggregate_size=queue,
        )

    def observe_aggregate_size(
        self,
        value: Decimal,
        *,
        includes_own_order: bool,
    ) -> None:
        aggregate = _decimal(
            value,
            reason_code="queue_aggregate_size_invalid",
        )
        if aggregate < 0:
            raise StreamContractError(
                "queue_aggregate_size_negative"
            )
        external = aggregate
        if includes_own_order:
            external = max(
                Decimal("0"),
                aggregate - self.own_remaining,
            )
        decrease = max(
            Decimal("0"),
            self.last_aggregate_size - external,
        )
        self.ahead_lower = max(
            Decimal("0"),
            self.ahead_lower - decrease,
        )
        self.ahead_upper = min(self.ahead_upper, external)
        self.ahead_lower = min(
            self.ahead_lower,
            self.ahead_upper,
        )
        self.last_aggregate_size = external

    def observe_own_fill(self, quantity: Decimal) -> None:
        fill = _decimal(
            quantity,
            reason_code="queue_fill_size_invalid",
        )
        if fill <= 0 or fill > self.own_remaining:
            raise StreamContractError("queue_fill_size_invalid")
        self.own_remaining -= fill
        # A FIFO fill proves the volume previously ahead has cleared.
        self.ahead_lower = Decimal("0")
        self.ahead_upper = Decimal("0")


@dataclass
class _MutableBook:
    config: StreamAssetConfig
    timestamp_ms: int
    received_at_ms: int
    book_hash: str
    bids: dict[Decimal, Decimal]
    asks: dict[Decimal, Decimal]
    tick_size: Decimal
    epoch: int
    update_count: int

    def copy(self) -> _MutableBook:
        return _MutableBook(
            config=self.config,
            timestamp_ms=self.timestamp_ms,
            received_at_ms=self.received_at_ms,
            book_hash=self.book_hash,
            bids=dict(self.bids),
            asks=dict(self.asks),
            tick_size=self.tick_size,
            epoch=self.epoch,
            update_count=self.update_count,
        )

    def view(self) -> StreamBookView:
        return StreamBookView(
            asset_id=self.config.asset_id,
            condition_id=self.config.condition_id,
            timestamp_ms=self.timestamp_ms,
            received_at_ms=self.received_at_ms,
            book_hash=self.book_hash,
            bids=_book_levels(self.bids, reverse=True),
            asks=_book_levels(self.asks, reverse=False),
            minimum_order_size=self.config.minimum_order_size,
            tick_size=self.tick_size,
            epoch=self.epoch,
            update_count=self.update_count,
        )


class LocalBookRegistry:
    """Fail-closed local L2 books for one WebSocket connection epoch."""

    def __init__(
        self,
        *,
        event: NegRiskEvent,
        assets: Sequence[StreamAssetConfig],
        clock_ms: Callable[[], int],
    ):
        configs = {
            asset.asset_id: asset
            for asset in assets
        }
        if len(configs) != len(tuple(assets)):
            raise StreamContractError(
                "stream_asset_config_duplicate"
            )
        if set(configs) != set(event.asset_ids):
            raise StreamContractError(
                "stream_asset_config_set_mismatch"
            )
        for market in event.markets:
            for asset_id in (
                market.yes_token_id,
                market.no_token_id,
            ):
                if (
                    configs[asset_id].condition_id
                    != market.condition_id
                ):
                    raise StreamContractError(
                        "stream_asset_condition_mismatch"
                    )
        self._event = event
        self._configs = MappingProxyType(configs)
        self._clock_ms = clock_ms
        self._books: dict[str, _MutableBook] = {}
        self._epoch = 0
        self._status = StreamStatus.DISCONNECTED
        self._reason_code: str | None = None

    @property
    def status(self) -> StreamStatus:
        return self._status

    @property
    def event(self) -> NegRiskEvent:
        return self._event

    @property
    def reason_code(self) -> str | None:
        return self._reason_code

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def asset_ids(self) -> tuple[str, ...]:
        return tuple(self._configs)

    @property
    def ready(self) -> bool:
        return self._status is StreamStatus.READY

    def begin_epoch(self) -> int:
        self._epoch += 1
        self._books.clear()
        self._reason_code = None
        self._status = (
            StreamStatus.BOOTSTRAPPING
            if self._epoch == 1
            else StreamStatus.RESYNCING
        )
        return self._epoch

    def disconnect(self) -> None:
        self._status = StreamStatus.DISCONNECTED
        self._reason_code = "market_stream_disconnected"

    def mark_suspect(self, reason_code: str) -> None:
        normalized = str(reason_code or "").strip()
        if not normalized:
            raise ValueError("reason_code is required")
        if self._status is StreamStatus.HALTED:
            return
        self._status = StreamStatus.SUSPECT
        self._reason_code = normalized

    def view(self, asset_id: str) -> StreamBookView:
        normalized = str(asset_id or "").strip()
        try:
            book = self._books[normalized]
        except KeyError as exc:
            raise StreamContractError(
                "stream_book_not_initialized"
            ) from exc
        return book.view()

    def views(self) -> Mapping[str, StreamBookView]:
        return MappingProxyType(
            {
                asset_id: book.view()
                for asset_id, book in self._books.items()
            }
        )

    def apply_message(
        self,
        payload: object,
    ) -> tuple[StreamUpdate, ...]:
        if isinstance(payload, list):
            updates: list[StreamUpdate] = []
            for message in payload:
                updates.append(self._apply_one(message))
            return tuple(updates)
        return (self._apply_one(payload),)

    def _apply_one(self, payload: object) -> StreamUpdate:
        if self._status in {
            StreamStatus.DISCONNECTED,
            StreamStatus.SUSPECT,
            StreamStatus.HALTED,
        }:
            raise StreamContractError(
                "stream_epoch_not_writable"
            )
        try:
            message = _mapping(
                payload,
                reason_code="market_event_invalid",
            )
            event_type = str(
                message.get("event_type") or ""
            ).strip()
            if event_type == "book":
                return self._apply_book(message)
            if event_type == "price_change":
                return self._apply_price_change(message)
            if event_type == "tick_size_change":
                return self._apply_tick_size_change(message)
            if event_type in {
                "last_trade_price",
                "best_bid_ask",
                "new_market",
            }:
                return self._observe_non_book_event(
                    message,
                    event_type=event_type,
                )
            if event_type == "market_resolved":
                return self._halt_for_resolution(message)
            raise StreamContractError(
                "market_event_type_unsupported"
            )
        except StreamContractError as exc:
            if self._status is not StreamStatus.HALTED:
                self.mark_suspect(str(exc))
            raise

    def _apply_book(
        self,
        message: Mapping[str, Any],
    ) -> StreamUpdate:
        received_at_ms = self._now()
        asset_id, config = self._asset_and_config(message)
        timestamp_ms = _timestamp_ms(message.get("timestamp"))
        previous = self._books.get(asset_id)
        if (
            previous is not None
            and timestamp_ms < previous.timestamp_ms
        ):
            raise StreamContractError(
                "stream_timestamp_regressed"
            )
        book_hash = _required_text(
            message.get("hash"),
            reason_code="stream_book_hash_missing",
        )
        bids = _level_map(
            message.get("bids"),
            reason_code="stream_bids_invalid",
        )
        asks = _level_map(
            message.get("asks"),
            reason_code="stream_asks_invalid",
        )
        tick_size = (
            previous.tick_size
            if previous is not None
            else config.tick_size
        )
        tick_size = _infer_finer_tick(
            tick_size,
            tuple(bids) + tuple(asks),
        )
        was_ready = self.ready
        self._books[asset_id] = _MutableBook(
            config=config,
            timestamp_ms=timestamp_ms,
            received_at_ms=received_at_ms,
            book_hash=book_hash,
            bids=bids,
            asks=asks,
            tick_size=tick_size,
            epoch=self._epoch,
            update_count=(
                previous.update_count + 1
                if previous is not None
                else 1
            ),
        )
        self._promote_if_complete()
        return StreamUpdate(
            event_type="book",
            affected_asset_ids=(asset_id,),
            timestamp_ms=timestamp_ms,
            received_at_ms=received_at_ms,
            status=self._status,
            became_ready=not was_ready and self.ready,
        )

    def _apply_price_change(
        self,
        message: Mapping[str, Any],
    ) -> StreamUpdate:
        received_at_ms = self._now()
        condition_id = _condition_id(message)
        timestamp_ms = _timestamp_ms(message.get("timestamp"))
        changes = _list(
            message.get("price_changes"),
            reason_code="price_changes_invalid",
        )
        if not changes:
            raise StreamContractError("price_changes_empty")

        pending: dict[str, _MutableBook] = {}
        expected_tops: dict[
            str,
            tuple[Decimal | None, Decimal | None],
        ] = {}
        seen_levels: set[tuple[str, str, Decimal]] = set()
        for raw_change in changes:
            change = _mapping(
                raw_change,
                reason_code="price_change_invalid",
            )
            asset_id, config = self._asset_and_config(
                change,
                fallback_condition_id=condition_id,
            )
            if config.condition_id != condition_id:
                raise StreamContractError(
                    "price_change_condition_mismatch"
                )
            current = pending.get(asset_id)
            if current is None:
                try:
                    current = self._books[asset_id].copy()
                except KeyError as exc:
                    raise StreamContractError(
                        "price_change_before_book"
                    ) from exc
                if timestamp_ms < current.timestamp_ms:
                    raise StreamContractError(
                        "stream_timestamp_regressed"
                    )
                pending[asset_id] = current

            side = str(change.get("side") or "").strip().upper()
            if side not in {"BUY", "SELL"}:
                raise StreamContractError(
                    "price_change_side_invalid"
                )
            price = _price(change.get("price"))
            size = _size_allow_zero(change.get("size"))
            level_key = (asset_id, side, price)
            if level_key in seen_levels:
                raise StreamContractError(
                    "price_change_level_duplicate"
                )
            seen_levels.add(level_key)
            current.tick_size = _infer_finer_tick(
                current.tick_size,
                (price,),
            )
            levels = (
                current.bids
                if side == "BUY"
                else current.asks
            )
            if size == 0:
                levels.pop(price, None)
            else:
                levels[price] = size
            current.timestamp_ms = timestamp_ms
            current.received_at_ms = received_at_ms
            current.book_hash = _required_text(
                change.get("hash"),
                reason_code="price_change_hash_missing",
            )
            current.update_count += 1
            expected_tops[asset_id] = (
                _optional_price(change.get("best_bid")),
                _optional_price(change.get("best_ask")),
            )

        for asset_id, current in pending.items():
            expected_bid, expected_ask = expected_tops[asset_id]
            if (
                expected_bid is not None
                and expected_bid != _best_price(
                    current.bids,
                    reverse=True,
                )
            ):
                raise StreamContractError(
                    "price_change_best_bid_mismatch"
                )
            if (
                expected_ask is not None
                and expected_ask != _best_price(
                    current.asks,
                    reverse=False,
                )
            ):
                raise StreamContractError(
                    "price_change_best_ask_mismatch"
                )

        self._books.update(pending)
        return StreamUpdate(
            event_type="price_change",
            affected_asset_ids=tuple(pending),
            timestamp_ms=timestamp_ms,
            received_at_ms=received_at_ms,
            status=self._status,
            became_ready=False,
        )

    def _apply_tick_size_change(
        self,
        message: Mapping[str, Any],
    ) -> StreamUpdate:
        received_at_ms = self._now()
        asset_id, _config = self._asset_and_config(message)
        timestamp_ms = _timestamp_ms(message.get("timestamp"))
        try:
            current = self._books[asset_id]
        except KeyError as exc:
            raise StreamContractError(
                "tick_size_change_before_book"
            ) from exc
        if timestamp_ms < current.timestamp_ms:
            raise StreamContractError(
                "stream_timestamp_regressed"
            )
        old_tick = _decimal(
            message.get("old_tick_size"),
            reason_code="old_tick_size_invalid",
        )
        new_tick = _decimal(
            message.get("new_tick_size"),
            reason_code="new_tick_size_invalid",
        )
        if old_tick != current.tick_size:
            raise StreamContractError(
                "old_tick_size_mismatch"
            )
        if new_tick not in SUPPORTED_TICKS or new_tick == old_tick:
            raise StreamContractError(
                "new_tick_size_unsupported"
            )
        current.tick_size = new_tick
        current.timestamp_ms = timestamp_ms
        current.received_at_ms = received_at_ms
        current.update_count += 1
        return StreamUpdate(
            event_type="tick_size_change",
            affected_asset_ids=(asset_id,),
            timestamp_ms=timestamp_ms,
            received_at_ms=received_at_ms,
            status=self._status,
            became_ready=False,
        )

    def _observe_non_book_event(
        self,
        message: Mapping[str, Any],
        *,
        event_type: str,
    ) -> StreamUpdate:
        received_at_ms = self._now()
        timestamp_value = message.get("timestamp")
        timestamp_ms = (
            _timestamp_ms(timestamp_value)
            if timestamp_value not in (None, "")
            else None
        )
        affected: tuple[str, ...] = ()
        raw_asset_id = (
            message.get("asset_id")
            or message.get("token_id")
        )
        if raw_asset_id not in (None, ""):
            asset_id, _config = self._asset_and_config(message)
            affected = (asset_id,)
        return StreamUpdate(
            event_type=event_type,
            affected_asset_ids=affected,
            timestamp_ms=timestamp_ms,
            received_at_ms=received_at_ms,
            status=self._status,
            became_ready=False,
        )

    def _halt_for_resolution(
        self,
        message: Mapping[str, Any],
    ) -> StreamUpdate:
        received_at_ms = self._now()
        condition_id = _condition_id(message)
        if condition_id not in {
            config.condition_id
            for config in self._configs.values()
        }:
            raise StreamContractError(
                "market_resolved_condition_unexpected"
            )
        timestamp_ms = _timestamp_ms(message.get("timestamp"))
        self._status = StreamStatus.HALTED
        self._reason_code = "market_resolved"
        affected = tuple(
            config.asset_id
            for config in self._configs.values()
            if config.condition_id == condition_id
        )
        return StreamUpdate(
            event_type="market_resolved",
            affected_asset_ids=affected,
            timestamp_ms=timestamp_ms,
            received_at_ms=received_at_ms,
            status=self._status,
            became_ready=False,
        )

    def _asset_and_config(
        self,
        value: Mapping[str, Any],
        *,
        fallback_condition_id: str | None = None,
    ) -> tuple[str, StreamAssetConfig]:
        asset_id = str(
            value.get("asset_id")
            or value.get("token_id")
            or ""
        ).strip()
        try:
            config = self._configs[asset_id]
        except KeyError as exc:
            raise StreamContractError(
                "stream_asset_unexpected"
            ) from exc
        condition_id = fallback_condition_id or _condition_id(value)
        if condition_id != config.condition_id:
            raise StreamContractError(
                "stream_asset_condition_mismatch"
            )
        return asset_id, config

    def _promote_if_complete(self) -> None:
        if set(self._books) == set(self._configs):
            self._status = StreamStatus.READY
            self._reason_code = None

    def _now(self) -> int:
        value = self._clock_ms()
        if not isinstance(value, int) or value < 0:
            raise StreamContractError("stream_clock_invalid")
        return value


def asset_configs_from_books(
    *,
    event: NegRiskEvent,
    books: Mapping[str, OrderBook],
) -> tuple[StreamAssetConfig, ...]:
    if set(books) != set(event.asset_ids):
        raise StreamContractError(
            "stream_bootstrap_book_set_mismatch"
        )
    market_by_asset = {
        asset_id: market
        for market in event.markets
        for asset_id in (
            market.yes_token_id,
            market.no_token_id,
        )
    }
    configs: list[StreamAssetConfig] = []
    for asset_id in event.asset_ids:
        book = books[asset_id]
        market = market_by_asset[asset_id]
        if (
            book.asset_id != asset_id
            or book.condition_id != market.condition_id
            or book.neg_risk is not True
        ):
            raise StreamContractError(
                "stream_bootstrap_book_mismatch"
            )
        configs.append(
            StreamAssetConfig(
                asset_id=asset_id,
                condition_id=market.condition_id,
                minimum_order_size=book.minimum_order_size,
                tick_size=book.tick_size,
            )
        )
    return tuple(configs)


def _mapping(
    value: object,
    *,
    reason_code: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StreamContractError(reason_code)
    return value


def _list(
    value: object,
    *,
    reason_code: str,
) -> list[Any]:
    if not isinstance(value, list):
        raise StreamContractError(reason_code)
    return value


def _decimal(
    value: object,
    *,
    reason_code: str,
) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise StreamContractError(reason_code) from exc
    if not result.is_finite():
        raise StreamContractError(reason_code)
    return result


def _price(value: object) -> Decimal:
    price = _decimal(
        value,
        reason_code="stream_price_invalid",
    )
    if price <= 0 or price >= ONE:
        raise StreamContractError("stream_price_out_of_range")
    return price


def _optional_price(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    return _price(value)


def _size_allow_zero(value: object) -> Decimal:
    size = _decimal(
        value,
        reason_code="stream_size_invalid",
    )
    if size < 0:
        raise StreamContractError("stream_size_negative")
    return size


def _required_text(
    value: object,
    *,
    reason_code: str,
) -> str:
    result = str(value or "").strip()
    if not result:
        raise StreamContractError(reason_code)
    return result


def _condition_id(value: Mapping[str, Any]) -> str:
    condition_id = str(value.get("market") or "").strip().lower()
    if not condition_id.startswith("0x"):
        raise StreamContractError("stream_condition_id_invalid")
    return condition_id


def _timestamp_ms(value: object) -> int:
    raw = str(value or "").strip()
    if not raw.isdigit():
        raise StreamContractError("stream_timestamp_invalid")
    timestamp = int(raw)
    if timestamp < 1_000_000_000_000:
        raise StreamContractError(
            "stream_timestamp_not_milliseconds"
        )
    return timestamp


def _level_map(
    value: object,
    *,
    reason_code: str,
) -> dict[Decimal, Decimal]:
    levels = _list(value, reason_code=reason_code)
    result: dict[Decimal, Decimal] = {}
    for raw_level in levels:
        level = _mapping(
            raw_level,
            reason_code=reason_code,
        )
        price = _price(level.get("price"))
        size = _size_allow_zero(level.get("size"))
        if size == 0:
            raise StreamContractError(
                f"{reason_code}_zero_size"
            )
        if price in result:
            raise StreamContractError(
                f"{reason_code}_price_duplicate"
            )
        result[price] = size
    return result


def _book_levels(
    levels: Mapping[Decimal, Decimal],
    *,
    reverse: bool,
) -> tuple[BookLevel, ...]:
    return tuple(
        BookLevel(price=price, size=levels[price])
        for price in sorted(levels, reverse=reverse)
    )


def _best_price(
    levels: Mapping[Decimal, Decimal],
    *,
    reverse: bool,
) -> Decimal | None:
    if not levels:
        return None
    return sorted(levels, reverse=reverse)[0]


def _infer_finer_tick(
    current_tick: Decimal,
    prices: Sequence[Decimal],
) -> Decimal:
    if all(price % current_tick == 0 for price in prices):
        return current_tick
    finer_ticks = [
        tick
        for tick in SUPPORTED_TICKS
        if tick < current_tick
        and all(price % tick == 0 for price in prices)
    ]
    if not finer_ticks:
        raise StreamContractError(
            "stream_price_tick_misaligned"
        )
    return max(finer_ticks)
