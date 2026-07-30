from __future__ import annotations

import json
import time
import unittest
from datetime import date

from neg_risk_trading.domain import NegRiskContractError
from neg_risk_trading.polymarket import (
    CLOB_BASE_URL,
    GAMMA_BASE_URL,
    PolymarketPublicClient,
    extract_event_slug,
    parse_clob_asset_books,
    parse_clob_books,
    parse_gamma_event,
)


EVENT_SLUG = "fed-decision-in-september-762"


def _condition(index: int) -> str:
    marker = format(index + 10, "x")
    return "0x" + marker * 64


def _gamma_market(index: int) -> dict:
    outcomes = ["Yes", "No"]
    token_ids = [str(10_000 + index), str(20_000 + index)]
    if index == 1:
        outcomes.reverse()
        token_ids.reverse()
    return {
        "id": f"market-{index}",
        "slug": f"fed-outcome-{index}",
        "question": f"Fed outcome {index}?",
        "conditionId": _condition(index),
        "active": True,
        "closed": False,
        "archived": False,
        "outcomes": json.dumps(outcomes),
        "clobTokenIds": json.dumps(token_ids),
        "feesEnabled": True,
        "feeSchedule": {
            "rate": 0.05,
            "exponent": 1,
            "takerOnly": True,
            "rebateRate": 0.25,
        },
        "rewardsMinSize": 200,
        "rewardsMaxSpread": 4.5,
        "clobRewards": [
            {
                "rewardsDailyRate": 1000 if index == 0 else 0,
                "startDate": "2026-07-29",
                "endDate": "2500-12-31",
            }
        ],
    }


def _gamma_event() -> dict:
    return {
        "id": "event-fed",
        "slug": EVENT_SLUG,
        "title": "Fed Decision in September?",
        "active": True,
        "closed": False,
        "archived": False,
        "negRisk": True,
        "negRiskAugmented": False,
        "markets": [
            _gamma_market(index)
            for index in range(5)
        ],
    }


def _book_payload(
    index: int,
    *,
    timestamp_ms: int,
    asset_id: str | None = None,
) -> dict:
    return {
        "market": _condition(index),
        "asset_id": asset_id or str(10_000 + index),
        "timestamp": str(timestamp_ms),
        "hash": f"book-hash-{index}",
        "bids": [{"price": "0.40", "size": "1000"}],
        "asks": [{"price": "0.41", "size": "1000"}],
        "min_order_size": "5",
        "tick_size": "0.01",
        "neg_risk": True,
        "last_trade_price": "0.40",
    }


class EventParserTests(unittest.TestCase):
    def test_extracts_only_polymarket_event_slug(self) -> None:
        self.assertEqual(
            extract_event_slug(
                "https://polymarket.com/event/"
                f"{EVENT_SLUG}?ignored=1"
            ),
            EVENT_SLUG,
        )
        with self.assertRaisesRegex(
            NegRiskContractError,
            "event_host_invalid",
        ):
            extract_event_slug(
                f"https://example.com/event/{EVENT_SLUG}"
            )

    def test_parses_standard_fed_event_and_yes_token_order(
        self,
    ) -> None:
        event = parse_gamma_event(
            _gamma_event(),
            expected_slug=EVENT_SLUG,
            as_of=date(2026, 7, 30),
        )

        self.assertFalse(event.augmented)
        self.assertEqual(len(event.markets), 5)
        self.assertEqual(
            event.markets[1].yes_token_id,
            "10001",
        )
        self.assertEqual(
            event.markets[1].no_token_id,
            "20001",
        )
        self.assertEqual(len(event.asset_ids), 10)
        self.assertEqual(
            event.markets[0].rewards.daily_rate,
            1000,
        )

    def test_enabled_fees_without_schedule_fail_closed(
        self,
    ) -> None:
        payload = _gamma_event()
        del payload["markets"][0]["feeSchedule"]

        with self.assertRaisesRegex(
            NegRiskContractError,
            "fee_schedule_missing",
        ):
            parse_gamma_event(
                payload,
                expected_slug=EVENT_SLUG,
                as_of=date(2026, 7, 30),
            )

    def test_malformed_numeric_metadata_fails_with_reason_code(
        self,
    ) -> None:
        payload = _gamma_event()
        payload["markets"][0]["feeSchedule"]["rate"] = "not-a-rate"

        with self.assertRaisesRegex(
            NegRiskContractError,
            "^fee_rate_invalid$",
        ):
            parse_gamma_event(
                payload,
                expected_slug=EVENT_SLUG,
                as_of=date(2026, 7, 30),
            )

    def test_missing_augmented_flag_fails_closed(self) -> None:
        payload = _gamma_event()
        del payload["negRiskAugmented"]

        with self.assertRaisesRegex(
            NegRiskContractError,
            "^gamma_neg_risk_augmented_ambiguous$",
        ):
            parse_gamma_event(
                payload,
                expected_slug=EVENT_SLUG,
                as_of=date(2026, 7, 30),
            )

    def test_inactive_component_market_fails_closed(self) -> None:
        payload = _gamma_event()
        payload["markets"][2]["active"] = False

        with self.assertRaisesRegex(
            NegRiskContractError,
            "^gamma_market_not_active$",
        ):
            parse_gamma_event(
                payload,
                expected_slug=EVENT_SLUG,
                as_of=date(2026, 7, 30),
            )


class BookParserTests(unittest.TestCase):
    def test_requires_one_exact_book_per_yes_token(self) -> None:
        event = parse_gamma_event(
            _gamma_event(),
            expected_slug=EVENT_SLUG,
            as_of=date(2026, 7, 30),
        )
        now_ms = time.time_ns() // 1_000_000
        books = parse_clob_books(
            [
                _book_payload(index, timestamp_ms=now_ms)
                for index in range(5)
            ],
            event=event,
        )

        self.assertEqual(len(books), 5)
        self.assertEqual(
            books[_condition(0)].asset_id,
            "10000",
        )

    def test_partial_book_batch_fails_closed(self) -> None:
        event = parse_gamma_event(
            _gamma_event(),
            expected_slug=EVENT_SLUG,
            as_of=date(2026, 7, 30),
        )
        now_ms = time.time_ns() // 1_000_000

        with self.assertRaisesRegex(
            NegRiskContractError,
            "clob_book_set_incomplete",
        ):
            parse_clob_books(
                [
                    _book_payload(index, timestamp_ms=now_ms)
                    for index in range(4)
                ],
                event=event,
            )

    def test_parses_all_yes_and_no_asset_books(self) -> None:
        event = parse_gamma_event(
            _gamma_event(),
            expected_slug=EVENT_SLUG,
            as_of=date(2026, 7, 30),
        )
        now_ms = time.time_ns() // 1_000_000
        payload = []
        for index in range(5):
            payload.append(
                _book_payload(index, timestamp_ms=now_ms)
            )
            payload.append(
                _book_payload(
                    index,
                    timestamp_ms=now_ms,
                    asset_id=str(20_000 + index),
                )
            )

        books = parse_clob_asset_books(
            payload,
            event=event,
        )

        self.assertEqual(set(books), set(event.asset_ids))
        self.assertEqual(
            books["20003"].condition_id,
            _condition(3),
        )

    def test_malformed_book_level_fails_with_reason_code(
        self,
    ) -> None:
        event = parse_gamma_event(
            _gamma_event(),
            expected_slug=EVENT_SLUG,
            as_of=date(2026, 7, 30),
        )
        now_ms = time.time_ns() // 1_000_000
        payload = [
            _book_payload(index, timestamp_ms=now_ms)
            for index in range(5)
        ]
        payload[0]["bids"][0]["price"] = "not-a-price"

        with self.assertRaisesRegex(
            NegRiskContractError,
            "^clob_bids_invalid_price_invalid$",
        ):
            parse_clob_books(payload, event=event)


class _FakeResponse:
    def __init__(self, payload: object):
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, gamma: dict, books: list[dict]):
        self.headers: dict[str, str] = {}
        self.gamma = gamma
        self.books = books
        self.get_calls: list[tuple[str, object]] = []
        self.post_calls: list[tuple[str, object, object]] = []

    def get(self, url: str, *, timeout: object) -> _FakeResponse:
        self.get_calls.append((url, timeout))
        return _FakeResponse(self.gamma)

    def post(
        self,
        url: str,
        *,
        json: object,
        timeout: object,
    ) -> _FakeResponse:
        self.post_calls.append((url, json, timeout))
        return _FakeResponse(self.books)


class PublicClientTests(unittest.TestCase):
    def test_fetches_all_books_in_one_public_batch(self) -> None:
        now_ms = time.time_ns() // 1_000_000
        session = _FakeSession(
            _gamma_event(),
            [
                _book_payload(index, timestamp_ms=now_ms)
                for index in range(5)
            ],
        )
        client = PolymarketPublicClient(session=session)

        snapshot = client.fetch_snapshot(EVENT_SLUG)

        self.assertEqual(len(session.get_calls), 1)
        self.assertEqual(
            session.get_calls[0][0],
            f"{GAMMA_BASE_URL}/events/slug/{EVENT_SLUG}",
        )
        self.assertEqual(len(session.post_calls), 1)
        self.assertEqual(
            session.post_calls[0][0],
            f"{CLOB_BASE_URL}/books",
        )
        self.assertEqual(
            session.post_calls[0][1],
            [
                {"token_id": str(10_000 + index)}
                for index in range(5)
            ],
        )
        self.assertEqual(len(snapshot.books), 5)

    def test_stream_bootstrap_fetches_all_ten_assets_once(
        self,
    ) -> None:
        now_ms = time.time_ns() // 1_000_000
        books = []
        for index in range(5):
            books.append(
                _book_payload(index, timestamp_ms=now_ms)
            )
            books.append(
                _book_payload(
                    index,
                    timestamp_ms=now_ms,
                    asset_id=str(20_000 + index),
                )
            )
        session = _FakeSession(_gamma_event(), books)
        client = PolymarketPublicClient(session=session)

        bootstrap = client.fetch_stream_bootstrap(EVENT_SLUG)

        self.assertEqual(len(session.get_calls), 1)
        self.assertEqual(len(session.post_calls), 1)
        self.assertEqual(
            session.post_calls[0][1],
            [
                {"token_id": asset_id}
                for asset_id in bootstrap.event.asset_ids
            ],
        )
        self.assertEqual(
            set(bootstrap.books),
            set(bootstrap.event.asset_ids),
        )


if __name__ == "__main__":
    unittest.main()
