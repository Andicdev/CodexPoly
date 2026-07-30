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
from cbr_trading.earnings.parsers.apple import (
    APPLE_CIK,
    APPLE_Q3_2026_CONDITION_ID,
    AppleGaapDilutedEpsParser,
    aapl_q3_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 30, 20, 30, 1, tzinfo=timezone.utc)


def _rule(*, year: int, quarter: int, period_end: date):
    base = aapl_q3_2026_shadow_rule()
    return replace(
        base,
        rule_key=f"aapl-{year}q{quarter}-replay",
        scope_id=earnings_scope_id("AAPL", year, quarter),
        fiscal_year=year,
        fiscal_quarter=quarter,
        period_end=period_end,
    )


def _source(rule) -> EarningsDocumentCandidate:
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=(
            f"accession-{rule.fiscal_year}q{rule.fiscal_quarter}"
        ),
        ticker="AAPL",
        cik=APPLE_CIK,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "320193/000000000026000001/exhibit991.htm"
        ),
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "320193/000000000026000001/filing.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


class AppleGaapDilutedEpsParserTests(unittest.TestCase):
    def test_parses_q3_headline_eps(self) -> None:
        rule = _rule(
            year=2025,
            quarter=3,
            period_end=date(2025, 6, 28),
        )
        document = """
        <h1>Apple reports third quarter results</h1>
        <p>
          Fiscal 2025 third quarter ended June 28, 2025.
          The Company posted quarterly revenue of $94.0 billion
          and quarterly diluted earnings per share of $1.57,
          up 12 percent year over year.
        </p>
        """

        result = AppleGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("1.57"))
        self.assertEqual(result.candidate.basis.value, "diluted")

    def test_parses_was_wording(self) -> None:
        rule = _rule(
            year=2026,
            quarter=2,
            period_end=date(2026, 3, 28),
        )
        document = """
        <p>Fiscal 2026 second quarter ended March 28, 2026.</p>
        <p>Diluted earnings per share was $2.01.</p>
        """

        result = AppleGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("2.01"))

    def test_table_only_or_guidance_does_not_guess(self) -> None:
        rule = aapl_q3_2026_shadow_rule()
        document = """
        <p>Fiscal 2026 third quarter ended June 27, 2026.</p>
        <p>Diluted EPS guidance is expected to be $2.10.</p>
        <table><tr><td>Diluted</td><td>$1.95</td></tr></table>
        """

        result = AppleGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "apple_gaap_diluted_eps_not_found",
        )

    def test_rule_has_reviewed_market_and_official_atom_source(self) -> None:
        rule = aapl_q3_2026_shadow_rule()

        self.assertEqual(rule.ticker, "AAPL")
        self.assertEqual(rule.cik, APPLE_CIK)
        self.assertEqual(rule.strike, Decimal("1.89"))
        self.assertEqual(
            rule.condition_id,
            APPLE_Q3_2026_CONDITION_ID,
        )
        self.assertEqual(
            rule.estimated_release_at.isoformat(),
            "2026-07-30T20:30:00+00:00",
        )
        self.assertEqual(
            rule.source_policy["company_ir"]["feed_url"],
            "https://www.apple.com/newsroom/rss-feed.rss",
        )
        self.assertEqual(
            rule.source_policy["company_ir"]["kind"],
            "rss",
        )
        self.assertNotIn("press_wire", rule.source_policy)


if __name__ == "__main__":
    unittest.main()
