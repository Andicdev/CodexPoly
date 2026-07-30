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
from cbr_trading.earnings.parsers.roblox import (
    ROBLOX_CIK,
    ROBLOX_Q2_2026_CONDITION_ID,
    RobloxGaapDilutedEpsParser,
    rblx_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 30, 20, 8, 45, tzinfo=timezone.utc)


def _rule(*, year: int, quarter: int, period_end: date):
    base = rblx_q2_2026_shadow_rule()
    return replace(
        base,
        rule_key=f"rblx-{year}q{quarter}-replay",
        scope_id=earnings_scope_id("RBLX", year, quarter),
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
        ticker="RBLX",
        cik=ROBLOX_CIK,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1315098/000000000026000001/exhibit991.htm"
        ),
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1315098/000000000026000001/filing.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


class RobloxGaapDilutedEpsParserTests(unittest.TestCase):
    def test_parses_current_year_value_from_gaap_row(self) -> None:
        rule = _rule(
            year=2026,
            quarter=1,
            period_end=date(2026, 3, 31),
        )
        document = """
        <h1>Roblox First Quarter 2026 Shareholder Letter</h1>
        <p>Three months ended March 31, 2026.</p>
        <table>
          <tr><th></th><th>2026</th><th>2025</th></tr>
          <tr>
            <td>Net loss per share attributable to common
                stockholders, basic and diluted</td>
            <td>$ (0.35)</td><td>$ (0.32)</td>
          </tr>
        </table>
        """

        result = RobloxGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.35"))

    def test_guidance_without_eps_does_not_match(self) -> None:
        rule = rblx_q2_2026_shadow_rule()
        document = """
        <h1>Roblox Second Quarter 2026 Guidance</h1>
        <p>Quarter ended June 30, 2026.</p>
        <p>Consolidated net loss guidance is $(257)-$(242) million.</p>
        """

        result = RobloxGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "roblox_gaap_diluted_eps_row_not_found",
        )

    def test_parses_sec_row_with_zero_width_formatting_marks(
        self,
    ) -> None:
        rule = rblx_q2_2026_shadow_rule()
        document = """
        <h1>Roblox Second Quarter 2026 Shareholder Letter</h1>
        <p>Three months ended June 30, 2026.</p>
        <table>
          <tr>
            <td>Net\u200b loss\u200b per\u200b share\u200b attributable
                \u200bto\u200b common\u200b stockholders,\u200b basic
                \u200band\u200b diluted</td>
            <td>$\u200b (0.26)</td><td>$\u200b (0.41)</td>
          </tr>
        </table>
        """

        result = RobloxGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.26"))

    def test_conflicting_duplicate_rows_quarantine(self) -> None:
        rule = rblx_q2_2026_shadow_rule()
        document = """
        <p>Quarter ended June 30, 2026.</p>
        <table>
          <tr><td>Net loss per share attributable to common stockholders,
          basic and diluted</td><td>$(0.30)</td><td>$(0.40)</td></tr>
          <tr><td>Net loss per share attributable to common stockholders,
          basic and diluted</td><td>$(0.31)</td><td>$(0.40)</td></tr>
        </table>
        """

        result = RobloxGaapDilutedEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_roblox_gaap_diluted_eps_rows",
        )

    def test_rule_has_reviewed_market_and_public_sources(self) -> None:
        rule = rblx_q2_2026_shadow_rule()

        self.assertEqual(rule.ticker, "RBLX")
        self.assertEqual(rule.cik, ROBLOX_CIK)
        self.assertEqual(rule.strike, Decimal("-0.33"))
        self.assertEqual(
            rule.condition_id,
            ROBLOX_Q2_2026_CONDITION_ID,
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
