from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from types import MappingProxyType
from typing import Mapping


FEE_QUANTUM = Decimal("0.00001")
ONE = Decimal("1")
HUNDRED = Decimal("100")


class NegRiskContractError(ValueError):
    """A malformed market or book violates the fail-closed contract."""


class RouteUnavailable(RuntimeError):
    """A safe reason why a strict route cannot currently be executed."""

    def __init__(self, reason_code: str):
        normalized = str(reason_code or "").strip()
        if not normalized:
            raise ValueError("reason_code is required")
        super().__init__(normalized)
        self.reason_code = normalized


def _decimal(value: object, *, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise NegRiskContractError(f"{name}_invalid") from exc
    if not result.is_finite():
        raise NegRiskContractError(f"{name}_invalid")
    return result


def _required_text(value: object, *, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise NegRiskContractError(f"{name}_required")
    return normalized


@dataclass(frozen=True)
class FeeSchedule:
    rate: Decimal
    exponent: int
    taker_only: bool
    rebate_rate: Decimal

    def __post_init__(self) -> None:
        rate = _decimal(self.rate, name="fee_rate")
        rebate_rate = _decimal(
            self.rebate_rate,
            name="rebate_rate",
        )
        if rate < 0 or rate >= ONE:
            raise NegRiskContractError("fee_rate_out_of_range")
        if rebate_rate < 0 or rebate_rate > ONE:
            raise NegRiskContractError("rebate_rate_out_of_range")
        if self.exponent != 1:
            raise NegRiskContractError("fee_exponent_unsupported")
        if self.taker_only is not True:
            raise NegRiskContractError("non_taker_only_fee_unsupported")
        object.__setattr__(self, "rate", rate)
        object.__setattr__(self, "rebate_rate", rebate_rate)

    def fee_equivalent(
        self,
        *,
        quantity: Decimal,
        price: Decimal,
    ) -> Decimal:
        normalized_quantity = _decimal(
            quantity,
            name="fee_quantity",
        )
        normalized_price = _decimal(price, name="fee_price")
        if normalized_quantity <= 0:
            raise NegRiskContractError("fee_quantity_not_positive")
        if normalized_price <= 0 or normalized_price >= ONE:
            raise NegRiskContractError("fee_price_out_of_range")
        return (
            normalized_quantity
            * self.rate
            * normalized_price
            * (ONE - normalized_price)
        )

    def conservative_taker_fee(
        self,
        *,
        quantity: Decimal,
        price: Decimal,
    ) -> Decimal:
        raw = self.fee_equivalent(
            quantity=quantity,
            price=price,
        )
        if raw == 0:
            return Decimal("0")
        return raw.quantize(FEE_QUANTUM, rounding=ROUND_CEILING)

    def estimated_maker_rebate(
        self,
        *,
        quantity: Decimal,
        price: Decimal,
    ) -> Decimal:
        return (
            self.fee_equivalent(
                quantity=quantity,
                price=price,
            )
            * self.rebate_rate
        )


@dataclass(frozen=True)
class RewardConfig:
    minimum_size: Decimal
    maximum_spread_cents: Decimal
    daily_rate: Decimal

    def __post_init__(self) -> None:
        minimum_size = _decimal(
            self.minimum_size,
            name="reward_minimum_size",
        )
        maximum_spread = _decimal(
            self.maximum_spread_cents,
            name="reward_maximum_spread_cents",
        )
        daily_rate = _decimal(
            self.daily_rate,
            name="reward_daily_rate",
        )
        if minimum_size < 0:
            raise NegRiskContractError("reward_minimum_size_negative")
        if maximum_spread < 0:
            raise NegRiskContractError(
                "reward_maximum_spread_negative"
            )
        if daily_rate < 0:
            raise NegRiskContractError("reward_daily_rate_negative")
        object.__setattr__(self, "minimum_size", minimum_size)
        object.__setattr__(
            self,
            "maximum_spread_cents",
            maximum_spread,
        )
        object.__setattr__(self, "daily_rate", daily_rate)


@dataclass(frozen=True)
class OutcomeMarket:
    market_id: str
    condition_id: str
    slug: str
    question: str
    yes_token_id: str
    no_token_id: str
    fee_schedule: FeeSchedule
    rewards: RewardConfig

    def __post_init__(self) -> None:
        for name in (
            "market_id",
            "condition_id",
            "slug",
            "question",
            "yes_token_id",
            "no_token_id",
        ):
            object.__setattr__(
                self,
                name,
                _required_text(getattr(self, name), name=name),
            )
        if not self.condition_id.startswith("0x"):
            raise NegRiskContractError("condition_id_invalid")
        if not self.yes_token_id.isdigit():
            raise NegRiskContractError("yes_token_id_invalid")
        if not self.no_token_id.isdigit():
            raise NegRiskContractError("no_token_id_invalid")
        if self.yes_token_id == self.no_token_id:
            raise NegRiskContractError("binary_token_id_duplicate")


@dataclass(frozen=True)
class NegRiskEvent:
    event_id: str
    slug: str
    title: str
    neg_risk: bool
    augmented: bool
    markets: tuple[OutcomeMarket, ...]

    def __post_init__(self) -> None:
        for name in ("event_id", "slug", "title"):
            object.__setattr__(
                self,
                name,
                _required_text(getattr(self, name), name=name),
            )
        markets = tuple(self.markets)
        if len(markets) < 2:
            raise NegRiskContractError("event_markets_incomplete")
        condition_ids = [market.condition_id for market in markets]
        token_ids = [
            token_id
            for market in markets
            for token_id in (
                market.yes_token_id,
                market.no_token_id,
            )
        ]
        if len(condition_ids) != len(set(condition_ids)):
            raise NegRiskContractError("condition_id_duplicate")
        if len(token_ids) != len(set(token_ids)):
            raise NegRiskContractError("event_token_id_duplicate")
        object.__setattr__(self, "markets", markets)

    @property
    def asset_ids(self) -> tuple[str, ...]:
        return tuple(
            token_id
            for market in self.markets
            for token_id in (
                market.yes_token_id,
                market.no_token_id,
            )
        )

    def market(self, condition_id: str) -> OutcomeMarket:
        normalized = str(condition_id or "").strip()
        for market in self.markets:
            if market.condition_id == normalized:
                return market
        raise RouteUnavailable("maker_market_not_found")


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal

    def __post_init__(self) -> None:
        price = _decimal(self.price, name="book_price")
        size = _decimal(self.size, name="book_size")
        if price <= 0 or price >= ONE:
            raise NegRiskContractError("book_price_out_of_range")
        if size <= 0:
            raise NegRiskContractError("book_size_not_positive")
        object.__setattr__(self, "price", price)
        object.__setattr__(self, "size", size)


@dataclass(frozen=True)
class DepthFill:
    price: Decimal
    quantity: Decimal

    @property
    def collateral(self) -> Decimal:
        return self.price * self.quantity


@dataclass(frozen=True)
class SweepResult:
    fills: tuple[DepthFill, ...]

    @property
    def quantity(self) -> Decimal:
        return sum(
            (fill.quantity for fill in self.fills),
            Decimal("0"),
        )

    @property
    def collateral(self) -> Decimal:
        return sum(
            (fill.collateral for fill in self.fills),
            Decimal("0"),
        )


def _normalized_levels(
    levels: tuple[BookLevel, ...],
    *,
    reverse: bool,
    side: str,
) -> tuple[BookLevel, ...]:
    normalized = tuple(
        level if isinstance(level, BookLevel) else BookLevel(**level)
        for level in levels
    )
    prices = [level.price for level in normalized]
    if len(prices) != len(set(prices)):
        raise NegRiskContractError(f"{side}_price_duplicate")
    return tuple(
        sorted(
            normalized,
            key=lambda level: level.price,
            reverse=reverse,
        )
    )


@dataclass(frozen=True)
class OrderBook:
    condition_id: str
    asset_id: str
    timestamp_ms: int
    book_hash: str
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    minimum_order_size: Decimal
    tick_size: Decimal
    neg_risk: bool

    def __post_init__(self) -> None:
        condition_id = _required_text(
            self.condition_id,
            name="book_condition_id",
        )
        asset_id = _required_text(
            self.asset_id,
            name="book_asset_id",
        )
        if not asset_id.isdigit():
            raise NegRiskContractError("book_asset_id_invalid")
        if not isinstance(self.timestamp_ms, int):
            raise NegRiskContractError("book_timestamp_invalid")
        if self.timestamp_ms < 1_000_000_000_000:
            raise NegRiskContractError("book_timestamp_not_milliseconds")
        minimum_order_size = _decimal(
            self.minimum_order_size,
            name="minimum_order_size",
        )
        tick_size = _decimal(self.tick_size, name="tick_size")
        if minimum_order_size <= 0:
            raise NegRiskContractError(
                "minimum_order_size_not_positive"
            )
        if tick_size <= 0 or tick_size >= ONE:
            raise NegRiskContractError("tick_size_out_of_range")
        object.__setattr__(self, "condition_id", condition_id)
        object.__setattr__(self, "asset_id", asset_id)
        object.__setattr__(
            self,
            "book_hash",
            _required_text(self.book_hash, name="book_hash"),
        )
        object.__setattr__(
            self,
            "bids",
            _normalized_levels(
                tuple(self.bids),
                reverse=True,
                side="bid",
            ),
        )
        object.__setattr__(
            self,
            "asks",
            _normalized_levels(
                tuple(self.asks),
                reverse=False,
                side="ask",
            ),
        )
        object.__setattr__(
            self,
            "minimum_order_size",
            minimum_order_size,
        )
        object.__setattr__(self, "tick_size", tick_size)

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    def size_at_ask(self, price: Decimal) -> Decimal:
        normalized_price = _decimal(price, name="maker_price")
        return sum(
            (
                level.size
                for level in self.asks
                if level.price == normalized_price
            ),
            Decimal("0"),
        )

    def sweep_bids(self, quantity: Decimal) -> SweepResult:
        normalized_quantity = _decimal(
            quantity,
            name="sweep_quantity",
        )
        if normalized_quantity <= 0:
            raise NegRiskContractError("sweep_quantity_not_positive")
        if normalized_quantity < self.minimum_order_size:
            raise RouteUnavailable("hedge_below_minimum_order_size")

        remaining = normalized_quantity
        fills: list[DepthFill] = []
        for level in self.bids:
            if remaining <= 0:
                break
            taken = min(remaining, level.size)
            fills.append(
                DepthFill(
                    price=level.price,
                    quantity=taken,
                )
            )
            remaining -= taken
        if remaining > 0:
            raise RouteUnavailable("hedge_depth_insufficient")
        return SweepResult(fills=tuple(fills))


@dataclass(frozen=True)
class MarketSnapshot:
    event: NegRiskEvent
    books: Mapping[str, OrderBook]
    requested_at_ms: int
    received_at_ms: int
    gamma_duration_ms: int
    books_duration_ms: int

    def __post_init__(self) -> None:
        if self.received_at_ms < self.requested_at_ms:
            raise NegRiskContractError("snapshot_clock_invalid")
        if self.gamma_duration_ms < 0 or self.books_duration_ms < 0:
            raise NegRiskContractError("snapshot_duration_negative")
        normalized_books = dict(self.books)
        expected = {
            market.condition_id
            for market in self.event.markets
        }
        if set(normalized_books) != expected:
            raise NegRiskContractError("snapshot_book_set_mismatch")
        for market in self.event.markets:
            book = normalized_books[market.condition_id]
            if book.condition_id != market.condition_id:
                raise NegRiskContractError(
                    "snapshot_condition_mismatch"
                )
            if book.asset_id != market.yes_token_id:
                raise NegRiskContractError("snapshot_asset_mismatch")
            if book.neg_risk is not True:
                raise NegRiskContractError(
                    "snapshot_book_not_neg_risk"
                )
        object.__setattr__(
            self,
            "books",
            MappingProxyType(normalized_books),
        )

    def validate_batch_coherence(
        self,
        *,
        maximum_books_duration_ms: int,
    ) -> None:
        if maximum_books_duration_ms <= 0:
            raise ValueError(
                "maximum_books_duration_ms must be positive"
            )
        if self.books_duration_ms > maximum_books_duration_ms:
            raise RouteUnavailable(
                "book_batch_duration_exceeded"
            )


@dataclass(frozen=True)
class HedgeLeg:
    condition_id: str
    question: str
    fills: tuple[DepthFill, ...]
    gross_proceeds: Decimal
    taker_fee: Decimal


@dataclass(frozen=True)
class MakerSellEvaluation:
    event_slug: str
    maker_condition_id: str
    maker_question: str
    maker_price: Decimal
    quantity: Decimal
    queue_ahead: Decimal
    hedge_legs: tuple[HedgeLeg, ...]
    gross_collateral: Decimal
    conservative_taker_fees: Decimal
    base_profit: Decimal
    estimated_maker_rebate: Decimal
    profit_with_rebate: Decimal
    reward_daily_rate: Decimal
    reward_minimum_size: Decimal
    reward_maximum_spread_cents: Decimal
    top_midpoint_spread_cents: Decimal | None
    reward_top_of_book_candidate: bool

    @property
    def base_edge_per_share(self) -> Decimal:
        return self.base_profit / self.quantity

    @property
    def edge_with_rebate_per_share(self) -> Decimal:
        return self.profit_with_rebate / self.quantity


def _price_aligned(*, price: Decimal, tick_size: Decimal) -> bool:
    return price % tick_size == 0


def evaluate_strict_maker_sell(
    snapshot: MarketSnapshot,
    *,
    maker_condition_id: str,
    quantity: Decimal,
    maker_price: Decimal | None = None,
    maximum_books_duration_ms: int = 2_000,
) -> MakerSellEvaluation:
    snapshot.validate_batch_coherence(
        maximum_books_duration_ms=maximum_books_duration_ms,
    )
    event = snapshot.event
    if event.neg_risk is not True:
        raise RouteUnavailable("event_not_neg_risk")
    if event.augmented is True:
        raise RouteUnavailable("augmented_event_not_supported")

    quantity = _decimal(quantity, name="route_quantity")
    if quantity <= 0:
        raise NegRiskContractError("route_quantity_not_positive")
    maker_market = event.market(maker_condition_id)
    maker_book = snapshot.books[maker_market.condition_id]
    if quantity < maker_book.minimum_order_size:
        raise RouteUnavailable("maker_below_minimum_order_size")

    if maker_price is None:
        if maker_book.best_ask is None:
            raise RouteUnavailable("maker_book_has_no_ask")
        effective_maker_price = maker_book.best_ask.price
    else:
        effective_maker_price = _decimal(
            maker_price,
            name="maker_price",
        )
    if (
        effective_maker_price <= 0
        or effective_maker_price >= ONE
    ):
        raise RouteUnavailable("maker_price_out_of_range")
    if not _price_aligned(
        price=effective_maker_price,
        tick_size=maker_book.tick_size,
    ):
        raise RouteUnavailable("maker_price_tick_misaligned")
    if (
        maker_book.best_bid is not None
        and effective_maker_price <= maker_book.best_bid.price
    ):
        raise RouteUnavailable("maker_sell_would_cross")

    maker_proceeds = effective_maker_price * quantity
    gross_collateral = maker_proceeds
    conservative_taker_fees = Decimal("0")
    hedge_legs: list[HedgeLeg] = []
    for hedge_market in event.markets:
        if hedge_market.condition_id == maker_market.condition_id:
            continue
        hedge_book = snapshot.books[hedge_market.condition_id]
        try:
            sweep = hedge_book.sweep_bids(quantity)
        except RouteUnavailable as exc:
            raise RouteUnavailable(
                f"{exc.reason_code}:{hedge_market.condition_id}"
            ) from exc
        leg_fee = sum(
            (
                hedge_market.fee_schedule.conservative_taker_fee(
                    quantity=fill.quantity,
                    price=fill.price,
                )
                for fill in sweep.fills
            ),
            Decimal("0"),
        )
        gross_collateral += sweep.collateral
        conservative_taker_fees += leg_fee
        hedge_legs.append(
            HedgeLeg(
                condition_id=hedge_market.condition_id,
                question=hedge_market.question,
                fills=sweep.fills,
                gross_proceeds=sweep.collateral,
                taker_fee=leg_fee,
            )
        )

    base_profit = (
        gross_collateral
        - conservative_taker_fees
        - quantity
    )
    estimated_rebate = (
        maker_market.fee_schedule.estimated_maker_rebate(
            quantity=quantity,
            price=effective_maker_price,
        )
    )
    reward_config = maker_market.rewards
    midpoint_spread: Decimal | None = None
    if (
        maker_book.best_bid is not None
        and maker_book.best_ask is not None
    ):
        midpoint = (
            maker_book.best_bid.price
            + maker_book.best_ask.price
        ) / Decimal("2")
        midpoint_spread = (
            abs(effective_maker_price - midpoint) * HUNDRED
        )
    reward_candidate = (
        reward_config.daily_rate > 0
        and quantity >= reward_config.minimum_size
        and midpoint_spread is not None
        and midpoint_spread
        <= reward_config.maximum_spread_cents
    )
    return MakerSellEvaluation(
        event_slug=event.slug,
        maker_condition_id=maker_market.condition_id,
        maker_question=maker_market.question,
        maker_price=effective_maker_price,
        quantity=quantity,
        queue_ahead=maker_book.size_at_ask(
            effective_maker_price
        ),
        hedge_legs=tuple(hedge_legs),
        gross_collateral=gross_collateral,
        conservative_taker_fees=conservative_taker_fees,
        base_profit=base_profit,
        estimated_maker_rebate=estimated_rebate,
        profit_with_rebate=base_profit + estimated_rebate,
        reward_daily_rate=reward_config.daily_rate,
        reward_minimum_size=reward_config.minimum_size,
        reward_maximum_spread_cents=(
            reward_config.maximum_spread_cents
        ),
        top_midpoint_spread_cents=midpoint_spread,
        reward_top_of_book_candidate=reward_candidate,
    )
