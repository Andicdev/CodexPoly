from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from neg_risk_trading.domain import (
    BookLevel,
    FeeSchedule,
    MarketSnapshot,
    NegRiskEvent,
    OrderBook,
    OutcomeMarket,
    RewardConfig,
    RouteUnavailable,
    evaluate_strict_maker_sell,
)


NOW_MS = 2_000_000_000_000


def _market(index: int) -> OutcomeMarket:
    marker = format(index + 10, "x")
    return OutcomeMarket(
        market_id=f"market-{index}",
        condition_id="0x" + marker * 64,
        slug=f"fed-outcome-{index}",
        question=f"Fed outcome {index}?",
        yes_token_id=str(10_000 + index),
        no_token_id=str(20_000 + index),
        fee_schedule=FeeSchedule(
            rate=Decimal("0.05"),
            exponent=1,
            taker_only=True,
            rebate_rate=Decimal("0.25"),
        ),
        rewards=RewardConfig(
            minimum_size=Decimal("200"),
            maximum_spread_cents=Decimal("4.5"),
            daily_rate=(
                Decimal("1000")
                if index == 0
                else Decimal("0")
            ),
        ),
    )


def _book(
    market: OutcomeMarket,
    *,
    bid: str,
    bid_size: str = "1000",
    ask: str,
    ask_size: str = "1000",
    timestamp_ms: int = NOW_MS,
    tick_size: str = "0.001",
) -> OrderBook:
    return OrderBook(
        condition_id=market.condition_id,
        asset_id=market.yes_token_id,
        timestamp_ms=timestamp_ms,
        book_hash=f"hash-{market.market_id}",
        bids=(
            BookLevel(
                price=Decimal(bid),
                size=Decimal(bid_size),
            ),
        ),
        asks=(
            BookLevel(
                price=Decimal(ask),
                size=Decimal(ask_size),
            ),
        ),
        minimum_order_size=Decimal("5"),
        tick_size=Decimal(tick_size),
        neg_risk=True,
    )


def _snapshot(
    *,
    augmented: bool = False,
    timestamp_ms: int = NOW_MS,
) -> MarketSnapshot:
    markets = tuple(_market(index) for index in range(5))
    event = NegRiskEvent(
        event_id="fed-september",
        slug="fed-decision-in-september-762",
        title="Fed Decision in September?",
        neg_risk=True,
        augmented=augmented,
        markets=markets,
    )
    books = {
        markets[0].condition_id: _book(
            markets[0],
            bid="0.39",
            ask="0.40",
            ask_size="1234.93",
            timestamp_ms=timestamp_ms,
            tick_size="0.01",
        ),
        markets[1].condition_id: _book(
            markets[1],
            bid="0.020",
            ask="0.022",
            timestamp_ms=timestamp_ms,
        ),
        markets[2].condition_id: _book(
            markets[2],
            bid="0.038",
            ask="0.039",
            timestamp_ms=timestamp_ms,
        ),
        markets[3].condition_id: _book(
            markets[3],
            bid="0.550",
            ask="0.560",
            timestamp_ms=timestamp_ms,
            tick_size="0.01",
        ),
        markets[4].condition_id: _book(
            markets[4],
            bid="0.016",
            ask="0.020",
            timestamp_ms=timestamp_ms,
        ),
    }
    return MarketSnapshot(
        event=event,
        books=books,
        requested_at_ms=NOW_MS - 100,
        received_at_ms=NOW_MS,
        gamma_duration_ms=25,
        books_duration_ms=40,
    )


class FeeScheduleTests(unittest.TestCase):
    def test_rounds_each_public_depth_level_up_conservatively(
        self,
    ) -> None:
        schedule = FeeSchedule(
            rate=Decimal("0.05"),
            exponent=1,
            taker_only=True,
            rebate_rate=Decimal("0.25"),
        )

        fee = schedule.conservative_taker_fee(
            quantity=Decimal("1"),
            price=Decimal("0.333"),
        )

        self.assertEqual(fee, Decimal("0.01111"))

    def test_unsupported_fee_exponent_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "fee_exponent_unsupported",
        ):
            FeeSchedule(
                rate=Decimal("0.05"),
                exponent=2,
                taker_only=True,
                rebate_rate=Decimal("0.25"),
            )


class StrictMakerSellEvaluationTests(unittest.TestCase):
    def test_depth_aware_fed_route_includes_fees_rebate_and_queue(
        self,
    ) -> None:
        snapshot = _snapshot()
        maker = snapshot.event.markets[0]

        result = evaluate_strict_maker_sell(
            snapshot,
            maker_condition_id=maker.condition_id,
            quantity=Decimal("200"),
        )

        self.assertEqual(result.maker_price, Decimal("0.40"))
        self.assertEqual(
            result.queue_ahead,
            Decimal("1234.93"),
        )
        self.assertEqual(
            result.gross_collateral,
            Decimal("204.800"),
        )
        self.assertEqual(
            result.conservative_taker_fees,
            Decimal("3.19400"),
        )
        self.assertEqual(
            result.base_profit,
            Decimal("1.60600"),
        )
        self.assertEqual(
            result.base_edge_per_share,
            Decimal("0.00803"),
        )
        self.assertEqual(
            result.estimated_maker_rebate,
            Decimal("0.600000"),
        )
        self.assertEqual(
            result.profit_with_rebate,
            Decimal("2.206000"),
        )
        self.assertEqual(len(result.hedge_legs), 4)
        self.assertTrue(result.reward_top_of_book_candidate)
        self.assertEqual(
            result.top_midpoint_spread_cents,
            Decimal("0.500"),
        )

    def test_reward_size_screen_is_false_below_minimum(
        self,
    ) -> None:
        snapshot = _snapshot()

        result = evaluate_strict_maker_sell(
            snapshot,
            maker_condition_id=(
                snapshot.event.markets[0].condition_id
            ),
            quantity=Decimal("50"),
        )

        self.assertFalse(result.reward_top_of_book_candidate)

    def test_incomplete_hedge_depth_fails_closed(self) -> None:
        snapshot = _snapshot()
        hedge_market = snapshot.event.markets[2]
        shallow = replace(
            snapshot.books[hedge_market.condition_id],
            bids=(
                BookLevel(
                    price=Decimal("0.038"),
                    size=Decimal("10"),
                ),
            ),
        )
        books = dict(snapshot.books)
        books[hedge_market.condition_id] = shallow
        snapshot = replace(snapshot, books=books)

        with self.assertRaises(RouteUnavailable) as raised:
            evaluate_strict_maker_sell(
                snapshot,
                maker_condition_id=(
                    snapshot.event.markets[0].condition_id
                ),
                quantity=Decimal("200"),
            )

        self.assertTrue(
            raised.exception.reason_code.startswith(
                "hedge_depth_insufficient:"
            )
        )

    def test_augmented_event_fails_closed(self) -> None:
        snapshot = _snapshot(augmented=True)

        with self.assertRaisesRegex(
            RouteUnavailable,
            "augmented_event_not_supported",
        ):
            evaluate_strict_maker_sell(
                snapshot,
                maker_condition_id=(
                    snapshot.event.markets[0].condition_id
                ),
                quantity=Decimal("200"),
            )

    def test_slow_book_batch_fails_closed(self) -> None:
        snapshot = replace(
            _snapshot(timestamp_ms=NOW_MS - 20_000),
            books_duration_ms=2_001,
        )

        with self.assertRaisesRegex(
            RouteUnavailable,
            "book_batch_duration_exceeded",
        ):
            evaluate_strict_maker_sell(
                snapshot,
                maker_condition_id=(
                    snapshot.event.markets[0].condition_id
                ),
                quantity=Decimal("200"),
                maximum_books_duration_ms=2_000,
            )

    def test_last_change_timestamp_skew_does_not_reject_batch(
        self,
    ) -> None:
        snapshot = _snapshot(timestamp_ms=NOW_MS - 20_000)

        result = evaluate_strict_maker_sell(
            snapshot,
            maker_condition_id=(
                snapshot.event.markets[0].condition_id
            ),
            quantity=Decimal("200"),
        )

        self.assertEqual(result.base_profit, Decimal("1.60600"))

    def test_crossing_maker_sell_fails_closed(self) -> None:
        snapshot = _snapshot()

        with self.assertRaisesRegex(
            RouteUnavailable,
            "maker_sell_would_cross",
        ):
            evaluate_strict_maker_sell(
                snapshot,
                maker_condition_id=(
                    snapshot.event.markets[0].condition_id
                ),
                maker_price=Decimal("0.39"),
                quantity=Decimal("200"),
            )


if __name__ == "__main__":
    unittest.main()
