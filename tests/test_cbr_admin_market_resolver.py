from __future__ import annotations

import unittest

from cbr_trading.admin.market_resolver import (
    MarketResolverError,
    extract_event_slug,
    resolve_three_way_markets,
)


def _market(
    direction: str,
    marker: str,
    *,
    active: bool = True,
) -> dict:
    questions = {
        "decrease": "Will the Bank of Russia decrease the key rate?",
        "no_change": (
            "Will the Bank of Russia make no change to the key rate?"
        ),
        "increase": "Will the Bank of Russia increase the key rate?",
    }
    return {
        "id": f"market-{direction}",
        "slug": f"market-{direction}",
        "question": questions[direction],
        "conditionId": "0x" + marker * 64,
        "active": active,
        "closed": False,
        "archived": False,
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": f'["{marker}1", "{marker}2"]',
    }


def _event() -> dict:
    return {
        "id": "event-1",
        "slug": "bank-of-russia-decision-in-july",
        "title": "Bank of Russia decision in July?",
        "markets": [
            _market("increase", "c"),
            _market("decrease", "a"),
            _market("no_change", "b"),
        ],
    }


class EventSlugTests(unittest.TestCase):
    def test_extracts_slug_from_url_or_plain_slug(self) -> None:
        expected = "bank-of-russia-decision-in-july"
        self.assertEqual(
            extract_event_slug(
                "https://polymarket.com/event/"
                "bank-of-russia-decision-in-july?x=1"
            ),
            expected,
        )
        self.assertEqual(extract_event_slug(expected), expected)

    def test_rejects_non_polymarket_host(self) -> None:
        with self.assertRaisesRegex(
            MarketResolverError,
            "polymarket.com",
        ):
            extract_event_slug(
                "https://example.com/event/cbr-decision"
            )


class ThreeWayResolverTests(unittest.TestCase):
    def test_resolves_three_active_binary_markets(self) -> None:
        result = resolve_three_way_markets(
            _event(),
            event_url=(
                "https://polymarket.com/event/"
                "bank-of-russia-decision-in-july"
            ),
        )

        self.assertEqual(
            [market.direction for market in result.markets],
            ["decrease", "no_change", "increase"],
        )
        self.assertEqual(
            result.by_direction()["decrease"].condition_id,
            "0x" + "a" * 64,
        )
        self.assertEqual(
            result.by_direction()["increase"].outcomes,
            ("Yes", "No"),
        )

    def test_missing_direction_fails_closed(self) -> None:
        event = _event()
        event["markets"] = event["markets"][:2]

        with self.assertRaisesRegex(
            MarketResolverError,
            "Missing active CBR markets",
        ):
            resolve_three_way_markets(
                event,
                event_url="https://polymarket.com/event/test",
            )

    def test_duplicate_direction_fails_closed(self) -> None:
        event = _event()
        event["markets"].append(_market("decrease", "d"))

        with self.assertRaisesRegex(
            MarketResolverError,
            "Multiple active markets",
        ):
            resolve_three_way_markets(
                event,
                event_url="https://polymarket.com/event/test",
            )

    def test_non_binary_market_is_rejected(self) -> None:
        event = _event()
        event["markets"][0]["outcomes"] = '["Up", "Down"]'

        with self.assertRaisesRegex(
            MarketResolverError,
            "not binary",
        ):
            resolve_three_way_markets(
                event,
                event_url="https://polymarket.com/event/test",
            )


if __name__ == "__main__":
    unittest.main()
