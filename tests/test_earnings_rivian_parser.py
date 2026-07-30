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
from cbr_trading.earnings.parsers.rivian import (
    RIVIAN_CIK,
    RIVIAN_Q2_2026_CONDITION_ID,
    RivianGaapDilutedEpsParser,
    rivn_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 30, 20, 0, 30, tzinfo=timezone.utc)


def _rule(*, year: int, quarter: int, period_end: date):
    base = rivn_q2_2026_shadow_rule()
    return replace(
        base,
        rule_key=f"rivn-{year}q{quarter}-replay",
        scope_id=earnings_scope_id("RIVN", year, quarter),
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
        ticker="RIVN",
        cik=RIVIAN_CIK,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1874178/000000000026000001/exhibit991.htm"
        ),
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1874178/000000000026000001/filing.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


class RivianGaapDilutedEpsParserTests(unittest.TestCase):
    def test_parses_current_year_value_from_gaap_row(self) -> None:
        rule = _rule(
            year=2026,
            quarter=1,
            period_end=date(2026, 3, 31),
        )
        document = """
        <h1>Rivian Releases First Quarter 2026 Financial Results</h1>
        <p>Three months ended March 31, 2026.</p>
        <table>
          <tr><th></th><th>2025</th><th>2026</th></tr>
          <tr>
            <td>
              Net loss per share attributable to Class A and Class B
              common stockholders, basic and diluted
            </td>
            <td>$(0.48)</td><td>$(0.33)</td>
          </tr>
        </table>
        """

        result = RivianGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.33"))

    def test_preliminary_release_without_eps_does_not_match(self) -> None:
        rule = rivn_q2_2026_shadow_rule()
        document = """
        <p>Preliminary results for the quarter ended June 30, 2026.</p>
        <table>
          <tr><td>Total consolidated revenues</td><td>$1.4 billion</td></tr>
          <tr><td>Cash and short-term investments</td><td>$4.8 billion</td></tr>
        </table>
        """

        result = RivianGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "rivian_gaap_diluted_eps_row_not_found",
        )

    def test_q2_selects_current_quarter_not_current_ytd(self) -> None:
        rule = rivn_q2_2026_shadow_rule()
        document = """
        <h1>Rivian Releases Second Quarter 2026 Financial Results</h1>
        <p>Three months ended June 30, 2026.</p>
        <table>
          <tr>
            <th></th>
            <th colspan="2">Three Months Ended June 30</th>
            <th colspan="2">Six Months Ended June 30</th>
          </tr>
          <tr>
            <th></th><th>2025</th><th>2026</th>
            <th>2025</th><th>2026</th>
          </tr>
          <tr>
            <td>Net loss per share attributable to Class A and Class B
            common stockholders, basic and diluted</td>
            <td>$(0.97)</td><td>$(0.63)</td>
            <td>$(1.45)</td><td>$(0.97)</td>
          </tr>
        </table>
        """

        result = RivianGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.63"))
        self.assertEqual(result.candidate.parser_version, "4")

    def test_q2_unknown_four_column_layout_fails_closed(self) -> None:
        rule = rivn_q2_2026_shadow_rule()
        document = """
        <h1>Rivian Releases Second Quarter 2026 Financial Results</h1>
        <p>Quarter ended June 30, 2026.</p>
        <table>
          <tr><th></th><th>2025</th><th>2026</th>
          <th>2025</th><th>2026</th></tr>
          <tr>
            <td>Net loss per share attributable to Class A and Class B
            common stockholders, basic and diluted</td>
            <td>$(0.97)</td><td>$(0.63)</td>
            <td>$(1.45)</td><td>$(0.97)</td>
          </tr>
        </table>
        """

        result = RivianGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertIsNone(result.candidate)

    def test_conflicting_duplicate_rows_quarantine(self) -> None:
        rule = rivn_q2_2026_shadow_rule()
        document = """
        <p>Quarter ended June 30, 2026.</p>
        <table>
          <tr>
            <th></th>
            <th colspan="2">Three Months Ended June 30</th>
          </tr>
          <tr><th></th><th>2025</th><th>2026</th></tr>
          <tr>
            <td>Net loss per share attributable to Class A and Class B
            common stockholders, basic and diluted</td>
            <td>$(0.70)</td><td>$(0.75)</td>
          </tr>
          <tr>
            <td>Net loss per share attributable to Class A and Class B
            common stockholders, basic and diluted</td>
            <td>$(0.70)</td><td>$(0.76)</td>
          </tr>
        </table>
        """

        result = RivianGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_rivian_gaap_diluted_eps_rows",
        )

    def test_rule_has_reviewed_market_and_public_sources(self) -> None:
        rule = rivn_q2_2026_shadow_rule()

        self.assertEqual(rule.ticker, "RIVN")
        self.assertEqual(rule.cik, RIVIAN_CIK)
        self.assertEqual(rule.strike, Decimal("-0.78"))
        self.assertEqual(
            rule.condition_id,
            RIVIAN_Q2_2026_CONDITION_ID,
        )
        self.assertEqual(
            rule.estimated_release_at.isoformat(),
            "2026-07-30T20:00:00+00:00",
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
