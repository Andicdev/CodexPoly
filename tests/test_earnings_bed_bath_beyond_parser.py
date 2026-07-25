from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    ParseStatus,
    SourceAuthority,
)
from cbr_trading.earnings.parsers.bed_bath_beyond import (
    BedBathBeyondNonGaapEpsParser,
    bbby_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 8, 4, 20, 0, 5, tzinfo=timezone.utc)


def _source() -> EarningsDocumentCandidate:
    rule = bbby_q2_2026_shadow_rule()
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id="bbby-2026q2-accession",
        ticker=rule.ticker,
        cik=rule.cik,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url="https://www.sec.gov/bbby-exhibit991.htm",
        filing_url="https://www.sec.gov/bbby-filing.htm",
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="bbby-transport-fingerprint",
    )


def _document(
    *,
    period: str = "June 30, 2026",
    adjusted_eps: str = "(0.25)",
) -> str:
    return f"""
    <html><body>
      <p>Financial results for the second quarter ended {period}.</p>
      <p>
        The following tables reflect the reconciliation of diluted net
        loss per share to adjusted diluted net loss per share
        (in thousands, except per share data):
      </p>
      <table>
        <tr><th>Three months ended</th></tr>
        <tr><th>{period}</th></tr>
        <tr>
          <th>Diluted EPS</th>
          <th>Less: investment gain</th>
          <th>Less: equity method loss</th>
          <th>Adjusted Diluted EPS</th>
        </tr>
        <tr><td>Net loss per share of common stock:</td></tr>
        <tr>
          <td>Diluted</td>
          <td>$ (0.30)</td>
          <td>$ 0.02</td>
          <td>$ (0.01)</td>
          <td>$ {adjusted_eps}</td>
        </tr>
      </table>
      <table>
        <tr><th>Three months ended</th></tr>
        <tr><th>June 30, 2025</th></tr>
        <tr><td>Adjusted Diluted EPS</td></tr>
        <tr><td>Net loss per share of common stock:</td></tr>
        <tr><td>Diluted</td><td>$ (0.42)</td></tr>
      </table>
      <p>
        The following table reflects the reconciliation of adjusted
        EBITDA to net loss.
      </p>
    </body></html>
    """


class BedBathBeyondNonGaapEpsParserTests(unittest.TestCase):
    def test_accepts_current_adjusted_diluted_eps(self) -> None:
        rule = bbby_q2_2026_shadow_rule()

        result = BedBathBeyondNonGaapEpsParser().parse(
            _document(),
            source=_source(),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.25"))
        self.assertEqual(result.candidate.metric, rule.metric)
        self.assertEqual(
            result.candidate.basis,
            rule.primary_basis,
        )

    def test_rounds_standard_half_up(self) -> None:
        result = BedBathBeyondNonGaapEpsParser().parse(
            _document(adjusted_eps="(0.255)"),
            source=_source(),
            rule=bbby_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.26"))

    def test_wrong_period_is_quarantined(self) -> None:
        result = BedBathBeyondNonGaapEpsParser().parse(
            _document(period="March 31, 2026"),
            source=_source(),
            rule=bbby_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "fiscal_period_not_confirmed")

    def test_gaap_eps_without_reconciliation_is_not_a_match(self) -> None:
        document = """
        <p>Second quarter ended June 30, 2026.</p>
        <p>GAAP diluted loss per share was $ (0.30).</p>
        """

        result = BedBathBeyondNonGaapEpsParser().parse(
            document,
            source=_source(),
            rule=bbby_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "bbby_adjusted_diluted_eps_row_not_found",
        )

    def test_conflicting_reconciliation_sections_are_quarantined(
        self,
    ) -> None:
        result = BedBathBeyondNonGaapEpsParser().parse(
            _document(adjusted_eps="(0.25)")
            + _document(adjusted_eps="(0.26)"),
            source=_source(),
            rule=bbby_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_bbby_adjusted_eps_rows",
        )


if __name__ == "__main__":
    unittest.main()
