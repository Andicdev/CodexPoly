from __future__ import annotations

import unittest

from cbr_trading.admin.market_resolver import (
    EventMarketSet,
    ResolvedMarket,
)
from cbr_trading.admin.templates import (
    RuleTemplateConfig,
    build_three_way_rule_drafts,
)


def _markets() -> EventMarketSet:
    markets = tuple(
        ResolvedMarket(
            direction=direction,
            condition_id="0x" + marker * 64,
            question=f"CBR {direction}?",
            market_id=f"market-{direction}",
            slug=f"market-{direction}",
            outcomes=("Yes", "No"),
            token_ids=(f"{marker}1", f"{marker}2"),
        )
        for direction, marker in (
            ("decrease", "a"),
            ("no_change", "b"),
            ("increase", "c"),
        )
    )
    return EventMarketSet(
        event_id="event-1",
        event_slug="cbr-july",
        event_title="CBR July",
        event_url="https://polymarket.com/event/cbr-july",
        markets=markets,
    )


class ThreeWayTemplateTests(unittest.TestCase):
    def test_builds_stable_legacy_compatible_rules(self) -> None:
        drafts = build_three_way_rule_drafts(
            _markets(),
            RuleTemplateConfig(
                account_name="main",
                order_qty=10,
                order_price_yes=0.91,
                order_price_no=0.09,
                increase_price_yes=0.95,
                increase_price_no=0.05,
            ),
        )

        self.assertEqual(
            [draft.rule_key for draft in drafts],
            [
                "cbr_decrease_fast",
                "cbr_no_change_fast",
                "cbr_increase_fast",
            ],
        )
        self.assertEqual(
            [draft.params["cmp"] for draft in drafts],
            ["<", "==", ">"],
        )
        self.assertTrue(
            all(
                draft.params["metric_key"]
                == "cbr_key_rate_change_bp"
                for draft in drafts
            )
        )
        self.assertEqual(
            drafts[2].params["order_price_yes"],
            0.95,
        )
        self.assertEqual(
            drafts[2].params["order_price_no"],
            0.05,
        )
        self.assertEqual(drafts[0].condition_id, "0x" + "a" * 64)

    def test_rejects_invalid_order_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "order_qty"):
            build_three_way_rule_drafts(
                _markets(),
                RuleTemplateConfig(
                    account_name="main",
                    order_qty=0,
                ),
            )

        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            build_three_way_rule_drafts(
                _markets(),
                RuleTemplateConfig(
                    account_name="main",
                    order_qty=10,
                    order_price_yes=1.0,
                ),
            )


if __name__ == "__main__":
    unittest.main()
