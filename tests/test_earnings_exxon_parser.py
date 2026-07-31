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
    ExxonEarningsExcludingItemsEpsParser,
    checked_in_shadow_rules,
    earnings_parser_registry,
    xom_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.exxon import (
    EXXONMOBIL_HOLDINGS_CIK,
    EXXONMOBIL_PREDECESSOR_CIK,
)


_DETECTED = datetime(2026, 7, 31, 10, 30, 1, tzinfo=timezone.utc)


def _source(
    *,
    cik: str = EXXONMOBIL_HOLDINGS_CIK,
) -> EarningsDocumentCandidate:
    rule = xom_q2_2026_shadow_rule()
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.COMPANY_IR,
        provider_event_id="test:XOM:2026Q2",
        ticker=rule.ticker,
        cik=cik,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://investor.exxonmobil.com/"
            "company-information/press-releases/detail/example"
        ),
        filing_url=(
            "https://investor.exxonmobil.com/"
            "company-information/press-releases/detail/example"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="test",
    )


class ExxonEarningsParserTests(unittest.TestCase):
    def test_table_selects_primary_eps_excluding_identified_items(
        self,
    ) -> None:
        result = ExxonEarningsExcludingItemsEpsParser().parse(
            (
                "ExxonMobil Announces Second-Quarter 2026 Results "
                "for the quarter ended June 30, 2026. Results Summary. "
                "Earnings Per Common Share ² | 3.50 | 1.00 | "
                "Earnings Excluding Identified Items Per Common Share "
                "(non-GAAP) ² | 3.71 | 1.16 | "
                "Earnings Excluding Identified Items and Estimated "
                "Timing Effects Per Common Share (non-GAAP) ² | "
                "4.80 | 2.09 |"
            ),
            source=_source(),
            rule=xom_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(str(result.candidate.value), "3.71")
        self.assertEqual(
            result.candidate.attributes["resolution_basis"],
            "earnings_excluding_identified_items_per_common_share",
        )

    def test_prose_shape_accepts_primary_non_gaap_eps(self) -> None:
        result = ExxonEarningsExcludingItemsEpsParser().parse(
            (
                "ExxonMobil Announces Second-Quarter 2026 Results "
                "for the quarter ended June 30, 2026. "
                "Earnings excluding identified items were $15.8 "
                "billion, or $3.71 per share. Earnings were $20.4 "
                "billion, or $4.80 per share, excluding identified "
                "items and estimated timing effects."
            ),
            source=_source(),
            rule=xom_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(str(result.candidate.value), "3.71")

    def test_timing_effects_or_gaap_only_does_not_match(self) -> None:
        result = ExxonEarningsExcludingItemsEpsParser().parse(
            (
                "ExxonMobil Announces Second-Quarter 2026 Results "
                "for the quarter ended June 30, 2026. "
                "Earnings per common share were $3.50. "
                "Earnings Excluding Identified Items and Estimated "
                "Timing Effects Per Common Share (non-GAAP) were $4.80."
            ),
            source=_source(),
            rule=xom_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertIsNone(result.candidate)

    def test_conflicting_primary_values_are_quarantined(self) -> None:
        result = ExxonEarningsExcludingItemsEpsParser().parse(
            (
                "ExxonMobil Announces Second-Quarter 2026 Results "
                "for the quarter ended June 30, 2026. "
                "Earnings Excluding Identified Items Per Common Share "
                "(non-GAAP) | 3.71 | "
                "Earnings excluding identified items were $15.8 "
                "billion, or $3.72 per share."
            ),
            source=_source(),
            rule=xom_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_exxon_earnings_excluding_items_eps",
        )

    def test_predecessor_cik_fails_closed_after_redomiciliation(
        self,
    ) -> None:
        result = ExxonEarningsExcludingItemsEpsParser().parse(
            (
                "ExxonMobil Announces Second-Quarter 2026 Results "
                "for the quarter ended June 30, 2026. "
                "Earnings excluding identified items were $15.8 "
                "billion, or $3.71 per share."
            ),
            source=_source(cik=EXXONMOBIL_PREDECESSOR_CIK),
            rule=xom_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "source_cik_mismatch")

    def test_rule_registry_and_public_sources_are_checked_in(self) -> None:
        rule = xom_q2_2026_shadow_rule()

        self.assertEqual(rule.cik, EXXONMOBIL_HOLDINGS_CIK)
        self.assertEqual(str(rule.strike), "3.66")
        self.assertEqual(
            rule.source_policy["company_ir"]["feed_url"],
            (
                "https://investor.exxonmobil.com/"
                "company-information/press-releases/rss"
            ),
        )
        self.assertEqual(
            rule.source_policy["press_wire"]["provider"],
            "businesswire",
        )
        self.assertIn("XOM", earnings_parser_registry())
        self.assertEqual(
            sum(
                candidate.scope_id == "earnings:XOM:2026Q2"
                for candidate in checked_in_shadow_rules()
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
