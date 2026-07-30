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
from cbr_trading.earnings.parsers.reddit import (
    REDDIT_CIK,
    REDDIT_Q2_2026_CONDITION_ID,
    RedditGaapDilutedEpsParser,
    rddt_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 30, 20, 8, 36, tzinfo=timezone.utc)


def _rule(*, year: int, quarter: int, period_end: date):
    base = rddt_q2_2026_shadow_rule()
    return replace(
        base,
        rule_key=f"rddt-{year}q{quarter}-replay",
        scope_id=earnings_scope_id("RDDT", year, quarter),
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
        ticker="RDDT",
        cik=REDDIT_CIK,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1713445/000000000026000001/exhibit991.htm"
        ),
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1713445/000000000026000001/filing.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


class RedditGaapDilutedEpsParserTests(unittest.TestCase):
    def test_parses_headline_and_basic_diluted_pair(self) -> None:
        rule = _rule(
            year=2025,
            quarter=2,
            period_end=date(2025, 6, 30),
        )
        document = """
        <h1>Reddit Announces Second Quarter 2025 Results</h1>
        <p>Quarter ended June 30, 2025.</p>
        <p>Net income of $89 million. Diluted EPS of $0.45</p>
        <p>
          Basic and diluted earnings per share (“EPS”) were
          $0.48 and $0.45, respectively.
        </p>
        """

        result = RedditGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("0.45"))

    def test_guidance_and_table_only_do_not_match(self) -> None:
        rule = rddt_q2_2026_shadow_rule()
        document = """
        <p>Quarter ended June 30, 2026.</p>
        <p>Diluted EPS is expected to be $1.02 next quarter.</p>
        <table><tr><td>Diluted</td><td>$0.98</td></tr></table>
        """

        result = RedditGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "reddit_gaap_diluted_eps_not_found",
        )

    def test_conflicting_headline_and_pair_quarantine(self) -> None:
        rule = rddt_q2_2026_shadow_rule()
        document = """
        <p>Quarter ended June 30, 2026.</p>
        <p>Net income of $200 million. Diluted EPS of $1.01</p>
        <p>
          Basic and diluted earnings per share were
          $1.08 and $1.02, respectively.
        </p>
        """

        result = RedditGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_reddit_gaap_diluted_eps_values",
        )

    def test_rule_has_reviewed_market_and_public_sources(self) -> None:
        rule = rddt_q2_2026_shadow_rule()

        self.assertEqual(rule.ticker, "RDDT")
        self.assertEqual(rule.cik, REDDIT_CIK)
        self.assertEqual(rule.strike, Decimal("0.97"))
        self.assertEqual(
            rule.condition_id,
            REDDIT_Q2_2026_CONDITION_ID,
        )
        self.assertEqual(
            rule.estimated_release_at.isoformat(),
            "2026-07-30T20:08:00+00:00",
        )
        self.assertEqual(
            rule.source_policy["company_ir"]["kind"],
            "html_listing",
        )
        self.assertEqual(
            rule.source_policy["press_wire"]["provider"],
            "businesswire",
        )


if __name__ == "__main__":
    unittest.main()
