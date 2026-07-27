from __future__ import annotations

import unittest

from cbr_trading.earnings.parsers import (
    checked_in_shadow_rules,
    earnings_parser_registry,
)


class EarningsParserRegistryTests(unittest.TestCase):
    def test_every_checked_in_rule_has_company_parser(self) -> None:
        rules = checked_in_shadow_rules()
        parsers = earnings_parser_registry()

        self.assertEqual(
            {rule.ticker for rule in rules},
            {
                "BA",
                "BBBY",
                "CSGP",
                "CZR",
                "F",
                "HLT",
                "IVZ",
                "JBLU",
                "KO",
                "NVTS",
                "NXPI",
                "PYPL",
                "RCL",
                "SBUX",
                "SPGI",
                "UPS",
                "V",
                "WWD",
            },
        )
        self.assertEqual(
            set(parsers),
            {
                "BA",
                "BBBY",
                "CSGP",
                "CZR",
                "F",
                "HLT",
                "IVZ",
                "JBLU",
                "KO",
                "NVTS",
                "NXPI",
                "PYPL",
                "RCL",
                "SBUX",
                "SPGI",
                "UPS",
                "V",
                "WWD",
            },
        )
        self.assertTrue(
            all(rule.condition_id for rule in rules)
        )
        self.assertEqual(
            len({rule.scope_id for rule in rules}),
            18,
        )

    def test_rules_retain_market_date_but_use_official_release_time(
        self,
    ) -> None:
        by_ticker = {
            rule.ticker: rule
            for rule in checked_in_shadow_rules()
        }

        self.assertIn(
            "07-27-2026",
            by_ticker["WWD"].market_slug,
        )
        self.assertEqual(
            by_ticker["WWD"].estimated_release_at.isoformat(),
            "2026-07-29T20:00:00+00:00",
        )
        self.assertIn(
            "07-27-2026",
            by_ticker["BBBY"].market_slug,
        )
        self.assertEqual(
            by_ticker["BBBY"].estimated_release_at.isoformat(),
            "2026-08-04T20:00:00+00:00",
        )
        self.assertIn(
            "07-28-2026",
            by_ticker["SBUX"].market_slug,
        )
        self.assertEqual(
            by_ticker["SBUX"].estimated_release_at.isoformat(),
            "2026-07-29T20:05:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
