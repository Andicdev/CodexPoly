from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    ParseStatus,
    SourceAuthority,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers.amazon import (
    AMAZON_CIK,
    AMAZON_Q2_2026_CONDITION_ID,
    AmazonGaapDilutedEpsParser,
    amzn_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 30, 20, 1, 1, tzinfo=timezone.utc)


def _rule(*, year: int, quarter: int, period_end: date):
    base = amzn_q2_2026_shadow_rule()
    return replace(
        base,
        rule_key=f"amzn-{year}q{quarter}-replay",
        scope_id=earnings_scope_id("AMZN", year, quarter),
        fiscal_year=year,
        fiscal_quarter=quarter,
        period_end=period_end,
    )


def _source(rule) -> EarningsDocumentCandidate:
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=f"accession-{rule.fiscal_year}q{rule.fiscal_quarter}",
        ticker="AMZN",
        cik=AMAZON_CIK,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1018724/000000000026000001/exhibit991.htm"
        ),
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1018724/000000000026000001/filing.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


class AmazonGaapDilutedEpsParserTests(unittest.TestCase):
    def test_parses_current_q2_eps_not_prior_year_comparison(self) -> None:
        rule = _rule(
            year=2025,
            quarter=2,
            period_end=date(2025, 6, 30),
        )
        document = """
        <h1>Amazon.com Announces Second Quarter Results</h1>
        <p>Financial results for the second quarter ended June 30, 2025.</p>
        <p>
          Net income increased to $18.2 billion in the second quarter,
          or $1.68 per diluted share, compared with $13.5 billion,
          or $1.26 per diluted share, in second quarter 2024.
        </p>
        """

        result = AmazonGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("1.68"))
        self.assertEqual(result.candidate.basis.value, "diluted")
        self.assertEqual(
            result.candidate.parser_name,
            "amazon_gaap_diluted_eps",
        )

    def test_net_loss_semantics_make_unsigned_eps_negative(self) -> None:
        rule = _rule(
            year=2022,
            quarter=2,
            period_end=date(2022, 6, 30),
        )
        document = """
        <p>Financial results for the second quarter ended June 30, 2022.</p>
        <p>
          Net loss was $2.0 billion in the second quarter,
          or $0.20 per diluted share, compared with net income
          in second quarter 2021.
        </p>
        """

        result = AmazonGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.20"))

    def test_missing_current_quarter_headline_does_not_guess(self) -> None:
        rule = amzn_q2_2026_shadow_rule()
        document = """
        <p>Quarter ended June 30, 2026.</p>
        <p>GAAP EPS guidance is expected to be $2.10.</p>
        """

        result = AmazonGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "amazon_gaap_diluted_eps_not_found",
        )

    def test_rule_has_reviewed_market_and_parallel_sources(self) -> None:
        rule = amzn_q2_2026_shadow_rule()

        self.assertEqual(rule.ticker, "AMZN")
        self.assertEqual(rule.cik, AMAZON_CIK)
        self.assertEqual(rule.strike, Decimal("1.82"))
        self.assertEqual(
            rule.condition_id,
            AMAZON_Q2_2026_CONDITION_ID,
        )
        self.assertEqual(
            rule.estimated_release_at.isoformat(),
            "2026-07-30T20:01:00+00:00",
        )
        self.assertEqual(
            rule.source_policy["company_ir"]["feed_url"],
            "https://ir.aboutamazon.com/rss/pressrelease.aspx",
        )
        self.assertEqual(
            rule.source_policy["press_wire"]["provider"],
            "businesswire",
        )


if __name__ == "__main__":
    unittest.main()
