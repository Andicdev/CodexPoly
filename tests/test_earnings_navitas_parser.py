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
from cbr_trading.earnings.parsers.navitas import (
    NavitasEpsParser,
    nvts_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 27, 21, 0, 5, tzinfo=timezone.utc)


def _rule(
    *,
    year: int,
    quarter: int,
    period_end: date,
):
    base = nvts_q2_2026_shadow_rule()
    return replace(
        base,
        rule_key=f"nvts-{year}q{quarter}-replay",
        scope_id=earnings_scope_id("NVTS", year, quarter),
        fiscal_year=year,
        fiscal_quarter=quarter,
        period_end=period_end,
    )


def _source(rule) -> EarningsDocumentCandidate:
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=f"accession-{rule.fiscal_year}q{rule.fiscal_quarter}",
        ticker="NVTS",
        cik="1821769",
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1821769/000000000026000001/exhibit991.htm"
        ),
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1821769/000000000026000001/filing.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


def _document(period_label: str, value: str) -> str:
    return f"""
    <html>
      <body>
        <table>
          <tr><th>Three Months Ended {period_label}</th></tr>
          <tr>
            <td>
              Average shares outstanding for calculation of non-GAAP
              Net loss per share (basic and diluted)
            </td>
            <td>229,988</td><td>222,344</td>
          </tr>
          <tr>
            <td>Non-GAAP Net loss per share (basic and diluted)</td>
            <td>$</td><td>{value}</td>
            <td>$</td><td>(0.99)</td>
          </tr>
        </table>
      </body>
    </html>
    """


class NavitasEpsParserReplayTests(unittest.TestCase):
    def test_replays_four_official_historical_layouts(self) -> None:
        # Minimal snippets mirror the official Navitas reconciliation rows.
        cases = (
            (2026, 1, date(2026, 3, 31), "March 31, 2026", "(0.04)", "-0.04"),
            (
                2025,
                4,
                date(2025, 12, 31),
                "December 31, 2025",
                "(0.05)",
                "-0.05",
            ),
            (
                2025,
                3,
                date(2025, 9, 30),
                "September 30, 2025",
                "(0.05)",
                "-0.05",
            ),
            (2025, 2, date(2025, 6, 30), "June 30, 2025", "(0.05)", "-0.05"),
        )
        parser = NavitasEpsParser()
        for year, quarter, ended, label, raw, expected in cases:
            with self.subTest(year=year, quarter=quarter):
                rule = _rule(
                    year=year,
                    quarter=quarter,
                    period_end=ended,
                )
                result = parser.parse(
                    _document(label, raw),
                    source=_source(rule),
                    rule=rule,
                    detected_at=_DETECTED,
                )
                self.assertEqual(result.status, ParseStatus.ACCEPTED)
                assert result.candidate is not None
                self.assertEqual(
                    result.candidate.value,
                    Decimal(expected),
                )
                self.assertEqual(result.candidate.confidence, Decimal("1"))

    def test_rounds_with_standard_half_up_semantics(self) -> None:
        rule = nvts_q2_2026_shadow_rule()
        result = NavitasEpsParser().parse(
            _document("June 30, 2026", "(0.035)"),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.raw_value, Decimal("-0.035"))
        self.assertEqual(result.candidate.value, Decimal("-0.04"))

    def test_missing_period_is_quarantined_not_guessed(self) -> None:
        rule = nvts_q2_2026_shadow_rule()
        result = NavitasEpsParser().parse(
            _document("March 31, 2026", "(0.03)"),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "fiscal_period_not_confirmed")

    def test_conflicting_rows_are_quarantined(self) -> None:
        rule = nvts_q2_2026_shadow_rule()
        document = (
            _document("June 30, 2026", "(0.03)")
            + _document("June 30, 2026", "(0.04)")
        )
        result = NavitasEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "conflicting_navitas_eps_rows")

    def test_absent_non_gaap_row_is_not_premature_no(self) -> None:
        rule = nvts_q2_2026_shadow_rule()
        document = """
        <p>Three Months Ended June 30, 2026</p>
        <p>GAAP diluted loss per share $ (0.20)</p>
        """
        result = NavitasEpsParser().parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "navitas_non_gaap_eps_row_not_found",
        )


if __name__ == "__main__":
    unittest.main()
