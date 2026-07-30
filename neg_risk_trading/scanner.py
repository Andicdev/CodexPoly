from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from neg_risk_trading.domain import (
    MakerSellEvaluation,
    MarketSnapshot,
    NegRiskContractError,
    RouteUnavailable,
    evaluate_strict_maker_sell,
)


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _evaluation_payload(
    evaluation: MakerSellEvaluation,
) -> dict[str, Any]:
    return {
        "available": True,
        "maker_condition_id": evaluation.maker_condition_id,
        "maker_question": evaluation.maker_question,
        "maker_price": _decimal_text(
            evaluation.maker_price
        ),
        "quantity": _decimal_text(evaluation.quantity),
        "queue_ahead": _decimal_text(evaluation.queue_ahead),
        "hedge_leg_count": len(evaluation.hedge_legs),
        "hedge_legs": [
            {
                "condition_id": leg.condition_id,
                "question": leg.question,
                "gross_proceeds": _decimal_text(
                    leg.gross_proceeds
                ),
                "conservative_taker_fee": _decimal_text(
                    leg.taker_fee
                ),
                "fills": [
                    {
                        "price": _decimal_text(fill.price),
                        "quantity": _decimal_text(
                            fill.quantity
                        ),
                    }
                    for fill in leg.fills
                ],
            }
            for leg in evaluation.hedge_legs
        ],
        "gross_collateral": _decimal_text(
            evaluation.gross_collateral
        ),
        "conservative_taker_fees": _decimal_text(
            evaluation.conservative_taker_fees
        ),
        "base_profit": _decimal_text(
            evaluation.base_profit
        ),
        "base_edge_per_share": _decimal_text(
            evaluation.base_edge_per_share
        ),
        "estimated_maker_rebate": _decimal_text(
            evaluation.estimated_maker_rebate
        ),
        "profit_with_rebate": _decimal_text(
            evaluation.profit_with_rebate
        ),
        "edge_with_rebate_per_share": _decimal_text(
            evaluation.edge_with_rebate_per_share
        ),
        "strict_edge_positive": evaluation.base_profit > 0,
        "reward": {
            "daily_rate": _decimal_text(
                evaluation.reward_daily_rate
            ),
            "minimum_size": _decimal_text(
                evaluation.reward_minimum_size
            ),
            "maximum_spread_cents": _decimal_text(
                evaluation.reward_maximum_spread_cents
            ),
            "top_midpoint_spread_cents": (
                _decimal_text(
                    evaluation.top_midpoint_spread_cents
                )
                if evaluation.top_midpoint_spread_cents
                is not None
                else None
            ),
            "top_of_book_candidate": (
                evaluation.reward_top_of_book_candidate
            ),
            "methodology_note": (
                "Top-of-book screening only; authoritative rewards use "
                "the size-cutoff-adjusted midpoint and relative maker score."
            ),
        },
    }


def evaluate_snapshot(
    snapshot: MarketSnapshot,
    *,
    quantities: Iterable[Decimal],
    maximum_books_duration_ms: int = 2_000,
) -> dict[str, Any]:
    normalized_quantities = tuple(
        Decimal(str(quantity))
        for quantity in quantities
    )
    if not normalized_quantities:
        raise ValueError("at least one quantity is required")
    if any(quantity <= 0 for quantity in normalized_quantities):
        raise ValueError("quantities must be positive")

    evaluations: list[dict[str, Any]] = []
    for market in snapshot.event.markets:
        for quantity in normalized_quantities:
            try:
                result = evaluate_strict_maker_sell(
                    snapshot,
                    maker_condition_id=market.condition_id,
                    quantity=quantity,
                    maximum_books_duration_ms=(
                        maximum_books_duration_ms
                    ),
                )
            except RouteUnavailable as exc:
                evaluations.append(
                    {
                        "available": False,
                        "maker_condition_id": market.condition_id,
                        "maker_question": market.question,
                        "quantity": _decimal_text(quantity),
                        "reason_code": exc.reason_code,
                    }
                )
            except NegRiskContractError:
                raise
            else:
                evaluations.append(
                    _evaluation_payload(result)
                )

    available = [
        result
        for result in evaluations
        if result["available"]
    ]
    available.sort(
        key=lambda result: Decimal(
            result["edge_with_rebate_per_share"]
        ),
        reverse=True,
    )
    unavailable = [
        result
        for result in evaluations
        if not result["available"]
    ]
    return {
        "mode": "READ_ONLY_SHADOW",
        "event": {
            "id": snapshot.event.event_id,
            "slug": snapshot.event.slug,
            "title": snapshot.event.title,
            "neg_risk": snapshot.event.neg_risk,
            "augmented": snapshot.event.augmented,
            "active_market_count": len(
                snapshot.event.markets
            ),
        },
        "snapshot": {
            "requested_at_ms": snapshot.requested_at_ms,
            "received_at_ms": snapshot.received_at_ms,
            "gamma_duration_ms": snapshot.gamma_duration_ms,
            "books_duration_ms": snapshot.books_duration_ms,
            "maximum_books_duration_ms": (
                maximum_books_duration_ms
            ),
            "book_timestamp_note": (
                "CLOB book timestamps are retained as last-change "
                "telemetry and are not treated as one batch clock."
            ),
        },
        "available_routes": available,
        "unavailable_routes": unavailable,
    }
