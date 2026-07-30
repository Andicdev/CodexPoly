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
from cbr_trading.earnings.parsers.dolby import (
    DOLBY_CIK,
    DOLBY_Q3_2026_CONDITION_ID,
    DolbyNonGaapDilutedEpsParser,
    dlb_q3_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 30, 20, 15, 1, tzinfo=timezone.utc)


def _rule(*, year: int, quarter: int, period_end: date):
    base = dlb_q3_2026_shadow_rule()
    return replace(
        base,
        rule_key=f"dlb-{year}q{quarter}-replay",
        scope_id=earnings_scope_id("DLB", year, quarter),
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
        ticker="DLB",
        cik=DOLBY_CIK,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1308547/000000000026000001/exhibit991.htm"
        ),
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1308547/000000000026000001/filing.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


class DolbyNonGaapDilutedEpsParserTests(unittest.TestCase):
    def test_parses_current_quarter_non_gaap_diluted_eps(self) -> None:
        rule = _rule(
            year=2025,
            quarter=3,
            period_end=date(2025, 6, 27),
        )
        document = """
        <h1>Dolby Laboratories Reports Third Quarter 2025 Results</h1>
        <p>Fiscal 2025 third quarter ended June 27, 2025.</p>
        <p>
          GAAP net income was $46 million or $0.48 per diluted share.
          On a non-GAAP basis, third quarter net income was
          $76 million, or $0.78 per diluted share.
        </p>
        """

        result = DolbyNonGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("0.78"))
        self.assertEqual(result.candidate.basis.value, "diluted")

    def test_gaap_and_guidance_without_headline_do_not_match(self) -> None:
        rule = dlb_q3_2026_shadow_rule()
        document = """
        <p>Fiscal 2026 third quarter ended June 26, 2026.</p>
        <p>GAAP net income was $52 million or $0.54 per diluted share.</p>
        <p>Non-GAAP diluted EPS guidance is $0.72 to $0.82.</p>
        """

        result = DolbyNonGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "dolby_non_gaap_diluted_eps_not_found",
        )

    def test_conflicting_current_quarter_headlines_quarantine(self) -> None:
        rule = dlb_q3_2026_shadow_rule()
        document = """
        <p>Fiscal 2026 third quarter ended June 26, 2026.</p>
        <p>
          On a non-GAAP basis, third quarter net income was
          $70 million, or $0.71 per diluted share.
        </p>
        <p>
          On a non-GAAP basis, third quarter net income was
          $72 million, or $0.73 per diluted share.
        </p>
        """

        result = DolbyNonGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_dolby_non_gaap_diluted_eps_values",
        )

    def test_rule_has_reviewed_market_and_three_live_sources(self) -> None:
        rule = dlb_q3_2026_shadow_rule()

        self.assertEqual(rule.ticker, "DLB")
        self.assertEqual(rule.cik, DOLBY_CIK)
        self.assertEqual(rule.strike, Decimal("0.67"))
        self.assertEqual(
            rule.condition_id,
            DOLBY_Q3_2026_CONDITION_ID,
        )
        self.assertEqual(
            rule.estimated_release_at.isoformat(),
            "2026-07-30T20:15:00+00:00",
        )
        self.assertEqual(
            rule.source_policy["company_ir"]["kind"],
            "html_listing",
        )
        self.assertEqual(
            rule.source_policy["press_wire"]["provider"],
            "prnewswire",
        )


if __name__ == "__main__":
    unittest.main()
