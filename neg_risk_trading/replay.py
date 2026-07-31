from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence

from neg_risk_trading.domain import (
    FeeSchedule,
    MarketSnapshot,
    NegRiskEvent,
    OutcomeMarket,
    RewardConfig,
    RouteDirection,
)
from neg_risk_trading.repository import ReplayMessage, ReplaySession
from neg_risk_trading.scanner import evaluate_snapshot
from neg_risk_trading.stream import (
    LocalBookRegistry,
    StreamAssetConfig,
)


EVENT_CONTRACT_VERSION = 1


class ReplayContractError(ValueError):
    """Stored public data is insufficient for deterministic replay."""


def event_contract_payload(
    *,
    event: NegRiskEvent,
    assets: Sequence[StreamAssetConfig],
) -> dict[str, object]:
    configs = tuple(assets)
    if {item.asset_id for item in configs} != set(event.asset_ids):
        raise ReplayContractError(
            "replay_contract_asset_set_mismatch"
        )
    return {
        "version": EVENT_CONTRACT_VERSION,
        "event": {
            "event_id": event.event_id,
            "slug": event.slug,
            "title": event.title,
            "neg_risk": event.neg_risk,
            "augmented": event.augmented,
        },
        "markets": [
            {
                "market_id": market.market_id,
                "condition_id": market.condition_id,
                "slug": market.slug,
                "question": market.question,
                "yes_token_id": market.yes_token_id,
                "no_token_id": market.no_token_id,
                "fee_schedule": {
                    "rate": _decimal_text(
                        market.fee_schedule.rate
                    ),
                    "exponent": market.fee_schedule.exponent,
                    "taker_only": (
                        market.fee_schedule.taker_only
                    ),
                    "rebate_rate": _decimal_text(
                        market.fee_schedule.rebate_rate
                    ),
                },
                "rewards": {
                    "minimum_size": _decimal_text(
                        market.rewards.minimum_size
                    ),
                    "maximum_spread_cents": _decimal_text(
                        market.rewards.maximum_spread_cents
                    ),
                    "daily_rate": _decimal_text(
                        market.rewards.daily_rate
                    ),
                },
            }
            for market in event.markets
        ],
        "assets": [
            {
                "asset_id": item.asset_id,
                "condition_id": item.condition_id,
                "minimum_order_size": _decimal_text(
                    item.minimum_order_size
                ),
                "tick_size": _decimal_text(item.tick_size),
            }
            for item in configs
        ],
    }


def event_contract_from_payload(
    value: object,
) -> tuple[NegRiskEvent, tuple[StreamAssetConfig, ...]]:
    contract = _mapping(
        value,
        reason_code="replay_event_contract_invalid",
    )
    if contract.get("version") != EVENT_CONTRACT_VERSION:
        raise ReplayContractError(
            "replay_event_contract_version_unsupported"
        )
    event_payload = _mapping(
        contract.get("event"),
        reason_code="replay_event_invalid",
    )
    markets_payload = _sequence(
        contract.get("markets"),
        reason_code="replay_markets_invalid",
    )
    markets: list[OutcomeMarket] = []
    for raw_market in markets_payload:
        market = _mapping(
            raw_market,
            reason_code="replay_market_invalid",
        )
        fee = _mapping(
            market.get("fee_schedule"),
            reason_code="replay_fee_schedule_invalid",
        )
        rewards = _mapping(
            market.get("rewards"),
            reason_code="replay_rewards_invalid",
        )
        try:
            exponent = int(fee.get("exponent"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ReplayContractError(
                "replay_fee_exponent_invalid"
            ) from exc
        markets.append(
            OutcomeMarket(
                market_id=_text(
                    market.get("market_id"),
                    reason_code="replay_market_id_required",
                ),
                condition_id=_text(
                    market.get("condition_id"),
                    reason_code="replay_condition_id_required",
                ),
                slug=_text(
                    market.get("slug"),
                    reason_code="replay_market_slug_required",
                ),
                question=_text(
                    market.get("question"),
                    reason_code="replay_question_required",
                ),
                yes_token_id=_text(
                    market.get("yes_token_id"),
                    reason_code="replay_yes_token_required",
                ),
                no_token_id=_text(
                    market.get("no_token_id"),
                    reason_code="replay_no_token_required",
                ),
                fee_schedule=FeeSchedule(
                    rate=_decimal(
                        fee.get("rate"),
                        reason_code="replay_fee_rate_invalid",
                    ),
                    exponent=exponent,
                    taker_only=_boolean(
                        fee.get("taker_only"),
                        reason_code=(
                            "replay_fee_taker_only_invalid"
                        ),
                    ),
                    rebate_rate=_decimal(
                        fee.get("rebate_rate"),
                        reason_code=(
                            "replay_rebate_rate_invalid"
                        ),
                    ),
                ),
                rewards=RewardConfig(
                    minimum_size=_decimal(
                        rewards.get("minimum_size"),
                        reason_code=(
                            "replay_reward_minimum_invalid"
                        ),
                    ),
                    maximum_spread_cents=_decimal(
                        rewards.get("maximum_spread_cents"),
                        reason_code=(
                            "replay_reward_spread_invalid"
                        ),
                    ),
                    daily_rate=_decimal(
                        rewards.get("daily_rate"),
                        reason_code=(
                            "replay_reward_rate_invalid"
                        ),
                    ),
                ),
            )
        )
    event = NegRiskEvent(
        event_id=_text(
            event_payload.get("event_id"),
            reason_code="replay_event_id_required",
        ),
        slug=_text(
            event_payload.get("slug"),
            reason_code="replay_event_slug_required",
        ),
        title=_text(
            event_payload.get("title"),
            reason_code="replay_event_title_required",
        ),
        neg_risk=_boolean(
            event_payload.get("neg_risk"),
            reason_code="replay_event_neg_risk_invalid",
        ),
        augmented=_boolean(
            event_payload.get("augmented"),
            reason_code="replay_event_augmented_invalid",
        ),
        markets=tuple(markets),
    )
    assets_payload = _sequence(
        contract.get("assets"),
        reason_code="replay_assets_invalid",
    )
    assets = tuple(
        StreamAssetConfig(
            asset_id=_text(
                item.get("asset_id"),
                reason_code="replay_asset_id_required",
            ),
            condition_id=_text(
                item.get("condition_id"),
                reason_code="replay_asset_condition_required",
            ),
            minimum_order_size=_decimal(
                item.get("minimum_order_size"),
                reason_code="replay_asset_minimum_invalid",
            ),
            tick_size=_decimal(
                item.get("tick_size"),
                reason_code="replay_asset_tick_invalid",
            ),
        )
        for item in (
            _mapping(
                raw,
                reason_code="replay_asset_invalid",
            )
            for raw in assets_payload
        )
    )
    if {item.asset_id for item in assets} != set(event.asset_ids):
        raise ReplayContractError(
            "replay_contract_asset_set_mismatch"
        )
    return event, assets


@dataclass
class _ReplayClock:
    value_ms: int = 0

    def __call__(self) -> int:
        return self.value_ms


@dataclass
class _RouteAggregate:
    route_direction: str
    maker_condition_id: str
    maker_question: str
    quantity: str
    observations: int = 0
    available: int = 0
    profitable_base: int = 0
    profitable_with_rebate: int = 0
    reward_candidates: int = 0
    unavailable_reasons: dict[str, int] = field(
        default_factory=dict
    )
    base_edge_sum: Decimal = Decimal("0")
    max_base_edge: Decimal | None = None
    max_rebate_edge: Decimal | None = None
    queue_sum: Decimal = Decimal("0")
    max_queue: Decimal | None = None
    positive_episodes: int = 0
    positive_milliseconds: int = 0
    observed_milliseconds: int = 0
    _last_observed_ms: int | None = None
    _last_positive: bool = False

    def observe(
        self,
        route: Mapping[str, object],
        *,
        observed_at_ms: int,
        maximum_interval_ms: int,
    ) -> None:
        self.observations += 1
        if self._last_observed_ms is not None:
            elapsed = min(
                maximum_interval_ms,
                max(
                    0,
                    observed_at_ms - self._last_observed_ms,
                ),
            )
            self.observed_milliseconds += elapsed
            if self._last_positive:
                self.positive_milliseconds += elapsed
        available = route.get("available") is True
        positive = False
        if available:
            self.available += 1
            base_edge = _decimal(
                route.get("base_edge_per_share"),
                reason_code="replay_base_edge_invalid",
            )
            rebate_edge = _decimal(
                route.get("edge_with_rebate_per_share"),
                reason_code="replay_rebate_edge_invalid",
            )
            queue = _decimal(
                route.get("queue_ahead"),
                reason_code="replay_queue_invalid",
            )
            self.base_edge_sum += base_edge
            self.queue_sum += queue
            self.max_base_edge = _maximum(
                self.max_base_edge,
                base_edge,
            )
            self.max_rebate_edge = _maximum(
                self.max_rebate_edge,
                rebate_edge,
            )
            self.max_queue = _maximum(self.max_queue, queue)
            positive = base_edge > 0
            if positive:
                self.profitable_base += 1
            if rebate_edge > 0:
                self.profitable_with_rebate += 1
            reward = route.get("reward")
            if (
                isinstance(reward, Mapping)
                and reward.get("top_of_book_candidate") is True
            ):
                self.reward_candidates += 1
        else:
            reason = _text(
                route.get("reason_code"),
                reason_code="replay_reason_required",
            )
            self.unavailable_reasons[reason] = (
                self.unavailable_reasons.get(reason, 0) + 1
            )
        if positive and not self._last_positive:
            self.positive_episodes += 1
        self._last_positive = positive
        self._last_observed_ms = observed_at_ms

    def payload(self) -> dict[str, object]:
        return {
            "route_direction": self.route_direction,
            "maker_condition_id": self.maker_condition_id,
            "maker_question": self.maker_question,
            "quantity": self.quantity,
            "observations": self.observations,
            "available": self.available,
            "profitable_base": self.profitable_base,
            "profitable_with_rebate": (
                self.profitable_with_rebate
            ),
            "reward_candidates": self.reward_candidates,
            "positive_episodes": self.positive_episodes,
            "positive_time_pct": _ratio_text(
                self.positive_milliseconds,
                self.observed_milliseconds,
            ),
            "average_base_edge_per_share": _average_text(
                self.base_edge_sum,
                self.available,
            ),
            "maximum_base_edge_per_share": _optional_decimal_text(
                self.max_base_edge
            ),
            "maximum_rebate_edge_per_share": (
                _optional_decimal_text(self.max_rebate_edge)
            ),
            "average_queue_ahead": _average_text(
                self.queue_sum,
                self.available,
            ),
            "maximum_queue_ahead": _optional_decimal_text(
                self.max_queue
            ),
            "unavailable_reasons": dict(
                sorted(self.unavailable_reasons.items())
            ),
        }


class DeterministicReplay:
    def __init__(
        self,
        *,
        session: ReplaySession,
        quantities: Sequence[Decimal] | None = None,
        route_directions: Sequence[RouteDirection] = (
            RouteDirection.MAKER_BUY,
            RouteDirection.MAKER_SELL,
        ),
        route_sample_interval_ms: int | None = None,
        maximum_interval_ms: int = 5_000,
    ):
        metadata = session.metadata
        if not isinstance(metadata, Mapping):
            raise ReplayContractError(
                "replay_session_metadata_invalid"
            )
        event, assets = event_contract_from_payload(
            metadata.get("event_contract")
        )
        if event.event_id != session.event_id:
            raise ReplayContractError(
                "replay_session_event_id_mismatch"
            )
        if event.slug != session.event_slug:
            raise ReplayContractError(
                "replay_session_event_slug_mismatch"
            )
        configured_quantities = (
            tuple(
                _decimal(
                    item,
                    reason_code="replay_quantity_invalid",
                )
                for item in quantities
            )
            if quantities is not None
            else tuple(
                _decimal(
                    item,
                    reason_code="replay_quantity_invalid",
                )
                for item in _sequence(
                    metadata.get("quantities"),
                    reason_code="replay_quantities_missing",
                )
            )
        )
        if (
            not configured_quantities
            or any(item <= 0 for item in configured_quantities)
        ):
            raise ReplayContractError(
                "replay_quantities_invalid"
            )
        directions = tuple(route_directions)
        if (
            not directions
            or len(directions) != len(set(directions))
            or any(
                not isinstance(item, RouteDirection)
                for item in directions
            )
        ):
            raise ReplayContractError(
                "replay_route_directions_invalid"
            )
        try:
            sample_interval = (
                int(route_sample_interval_ms)
                if route_sample_interval_ms is not None
                else int(
                    metadata.get("route_sample_interval_ms")
                )
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise ReplayContractError(
                "replay_sample_interval_invalid"
            ) from exc
        if sample_interval < 0:
            raise ReplayContractError(
                "replay_sample_interval_invalid"
            )
        if maximum_interval_ms <= 0:
            raise ReplayContractError(
                "replay_maximum_interval_invalid"
            )
        self._session = session
        self._event = event
        self._assets = assets
        self._quantities = configured_quantities
        self._directions = directions
        self._sample_interval_ms = sample_interval
        self._maximum_interval_ms = int(maximum_interval_ms)

    def run(
        self,
        messages: Iterable[ReplayMessage],
    ) -> dict[str, object]:
        clock = _ReplayClock()
        registry = LocalBookRegistry(
            event=self._event,
            assets=self._assets,
            clock_ms=clock,
        )
        yes_asset_ids = {
            market.yes_token_id
            for market in self._event.markets
        }
        current_epoch = 0
        expected_sequence = 0
        last_route_at_ms: int | None = None
        source_messages = 0
        applied_updates = 0
        evaluated_messages = 0
        irrelevant_messages = 0
        first_received_at: datetime | None = None
        last_received_at: datetime | None = None
        aggregates: dict[
            tuple[str, str, str],
            _RouteAggregate,
        ] = {}
        for message in messages:
            if message.connection_epoch != current_epoch:
                if message.connection_epoch != current_epoch + 1:
                    raise ReplayContractError(
                        "replay_connection_epoch_gap"
                    )
                current_epoch = registry.begin_epoch()
                expected_sequence = 0
            expected_sequence += 1
            if message.message_sequence != expected_sequence:
                raise ReplayContractError(
                    "replay_message_sequence_gap"
                )
            clock.value_ms = int(
                message.received_at.timestamp() * 1000
            )
            updates = registry.apply_message(message.payload)
            source_messages += 1
            applied_updates += len(updates)
            first_received_at = (
                message.received_at
                if first_received_at is None
                else min(first_received_at, message.received_at)
            )
            last_received_at = (
                message.received_at
                if last_received_at is None
                else max(last_received_at, message.received_at)
            )
            affected = {
                asset_id
                for update in updates
                for asset_id in update.affected_asset_ids
            }
            if (
                not registry.ready
                or not affected.intersection(yes_asset_ids)
                or (
                    last_route_at_ms is not None
                    and clock.value_ms - last_route_at_ms
                    < self._sample_interval_ms
                )
            ):
                irrelevant_messages += 1
                continue
            books = {
                market.condition_id: registry.view(
                    market.yes_token_id
                ).as_order_book()
                for market in self._event.markets
            }
            evaluation = evaluate_snapshot(
                MarketSnapshot(
                    event=self._event,
                    books=books,
                    requested_at_ms=clock.value_ms,
                    received_at_ms=clock.value_ms,
                    gamma_duration_ms=0,
                    books_duration_ms=0,
                ),
                quantities=self._quantities,
                route_directions=self._directions,
            )
            evaluated_messages += 1
            last_route_at_ms = clock.value_ms
            for name in (
                "available_routes",
                "unavailable_routes",
            ):
                routes = evaluation.get(name)
                if not isinstance(routes, list):
                    raise ReplayContractError(
                        "replay_routes_invalid"
                    )
                for raw_route in routes:
                    route = _mapping(
                        raw_route,
                        reason_code="replay_route_invalid",
                    )
                    direction = _text(
                        route.get("route_direction"),
                        reason_code=(
                            "replay_route_direction_required"
                        ),
                    )
                    condition_id = _text(
                        route.get("maker_condition_id"),
                        reason_code=(
                            "replay_maker_condition_required"
                        ),
                    )
                    quantity = _text(
                        route.get("quantity"),
                        reason_code="replay_route_quantity_required",
                    )
                    key = (direction, condition_id, quantity)
                    aggregate = aggregates.get(key)
                    if aggregate is None:
                        aggregate = _RouteAggregate(
                            route_direction=direction,
                            maker_condition_id=condition_id,
                            maker_question=_text(
                                route.get("maker_question"),
                                reason_code=(
                                    "replay_maker_question_required"
                                ),
                            ),
                            quantity=quantity,
                        )
                        aggregates[key] = aggregate
                    aggregate.observe(
                        route,
                        observed_at_ms=clock.value_ms,
                        maximum_interval_ms=(
                            self._maximum_interval_ms
                        ),
                    )
        return {
            "mode": "READ_ONLY_DETERMINISTIC_REPLAY",
            "session_id": str(self._session.session_id),
            "event_slug": self._event.slug,
            "contract_version": EVENT_CONTRACT_VERSION,
            "source_messages": source_messages,
            "applied_updates": applied_updates,
            "connection_epochs": current_epoch,
            "evaluated_messages": evaluated_messages,
            "irrelevant_messages": irrelevant_messages,
            "first_received_at": (
                first_received_at.isoformat()
                if first_received_at is not None
                else None
            ),
            "last_received_at": (
                last_received_at.isoformat()
                if last_received_at is not None
                else None
            ),
            "routes": [
                aggregate.payload()
                for _key, aggregate in sorted(
                    aggregates.items()
                )
            ],
        }


def _mapping(
    value: object,
    *,
    reason_code: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ReplayContractError(reason_code)
    return value


def _sequence(
    value: object,
    *,
    reason_code: str,
) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise ReplayContractError(reason_code)
    return value


def _text(value: object, *, reason_code: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ReplayContractError(reason_code)
    return result


def _decimal(value: object, *, reason_code: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ReplayContractError(reason_code) from exc
    if not result.is_finite():
        raise ReplayContractError(reason_code)
    return result


def _boolean(value: object, *, reason_code: str) -> bool:
    if not isinstance(value, bool):
        raise ReplayContractError(reason_code)
    return value


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _optional_decimal_text(
    value: Decimal | None,
) -> str | None:
    return _decimal_text(value) if value is not None else None


def _maximum(
    current: Decimal | None,
    value: Decimal,
) -> Decimal:
    return value if current is None else max(current, value)


def _average_text(total: Decimal, count: int) -> str | None:
    if count <= 0:
        return None
    return _decimal_text(total / Decimal(count))


def _ratio_text(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    return _decimal_text(
        Decimal(numerator)
        * Decimal("100")
        / Decimal(denominator)
    )
