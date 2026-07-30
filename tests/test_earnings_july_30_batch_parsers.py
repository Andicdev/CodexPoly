from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    ParseStatus,
    SourceAuthority,
)
from cbr_trading.earnings.parsers import (
    CignaAdjustedIncomePerShareParser,
    IceAdjustedDilutedEpsParser,
    YumEpsExcludingSpecialItemsParser,
    checked_in_shadow_rules,
    ci_q2_2026_shadow_rule,
    earnings_parser_registry,
    ice_q2_2026_shadow_rule,
    yum_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 30, 11, 0, 1, tzinfo=timezone.utc)


def _source(rule) -> EarningsDocumentCandidate:
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=f"test:{rule.ticker}:final",
        ticker=rule.ticker,
        cik=rule.cik,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url="https://www.sec.gov/example-exhibit",
        filing_url="https://www.sec.gov/example-filing",
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="test",
    )


class July30BatchParserTests(unittest.TestCase):
    def test_yum_accepts_eps_excluding_special_items(self) -> None:
        rule = yum_q2_2026_shadow_rule()
        result = YumEpsExcludingSpecialItemsParser().parse(
            (
                "Yum! Brands Reports Second-Quarter Results for the "
                "quarter ended June 30, 2026. Second-quarter GAAP "
                "EPS was $1.48 and second-quarter EPS excluding "
                "Special Items was $1.61, a 9% increase."
            ),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(str(result.candidate.value), "1.61")

    def test_ice_accepts_adjusted_diluted_eps(self) -> None:
        rule = ice_q2_2026_shadow_rule()
        result = IceAdjustedDilutedEpsParser().parse(
            (
                "Intercontinental Exchange Reports Second Quarter "
                "2026 Results for the quarter ended June 30, 2026. "
                "GAAP diluted EPS of $1.91. Adj. diluted EPS of "
                "$1.88, up 8% year-over-year."
            ),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(str(result.candidate.value), "1.88")

    def test_cigna_selects_per_share_not_billion_amount(self) -> None:
        rule = ci_q2_2026_shadow_rule()
        result = CignaAdjustedIncomePerShareParser().parse(
            (
                "The Cigna Group Reports Second Quarter 2026 Results "
                "for the quarter ended June 30, 2026. The Cigna "
                "Group's adjusted income from operations for second "
                "quarter 2026 was $2.0 billion, or $7.71 per share, "
                "compared with $1.9 billion, or $7.02 per share, for "
                "second quarter 2025."
            ),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(str(result.candidate.value), "7.71")

    def test_gaap_or_guidance_only_documents_fail_closed(self) -> None:
        cases = (
            (
                YumEpsExcludingSpecialItemsParser(),
                yum_q2_2026_shadow_rule(),
                "YUM second quarter 2026 GAAP EPS was $1.48.",
            ),
            (
                IceAdjustedDilutedEpsParser(),
                ice_q2_2026_shadow_rule(),
                "ICE second quarter 2026 GAAP diluted EPS of $1.91.",
            ),
            (
                CignaAdjustedIncomePerShareParser(),
                ci_q2_2026_shadow_rule(),
                (
                    "Cigna second quarter 2026 shareholders' net "
                    "income was $1.7 billion, or $6.26 per share."
                ),
            ),
        )
        for parser, rule, document in cases:
            with self.subTest(ticker=rule.ticker):
                result = parser.parse(
                    document,
                    source=_source(rule),
                    rule=rule,
                    detected_at=_DETECTED,
                )
                self.assertEqual(result.status, ParseStatus.NO_MATCH)
                self.assertIsNone(result.candidate)

    def test_rules_and_parsers_are_checked_in(self) -> None:
        expected = {
            "YUM": ("1.56", "businesswire"),
            "ICE": ("1.84", "businesswire"),
            "CI": ("7.60", "businesswire"),
        }
        rules = {
            rule.ticker: rule
            for rule in checked_in_shadow_rules()
        }
        registry = earnings_parser_registry()

        for ticker, (strike, provider) in expected.items():
            with self.subTest(ticker=ticker):
                self.assertIn(ticker, registry)
                self.assertEqual(str(rules[ticker].strike), strike)
                self.assertEqual(
                    rules[ticker].source_policy["press_wire"]["provider"],
                    provider,
                )


if __name__ == "__main__":
    unittest.main()
