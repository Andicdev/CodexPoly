from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    ParseStatus,
    SourceAuthority,
)
from cbr_trading.earnings.parsers.nxp import (
    NXP_CIK,
    NxpNonGaapEpsParser,
    nxpi_q2_2026_shadow_rule,
)


_DETECTED = datetime(
    2026,
    7,
    28,
    20,
    10,
    5,
    tzinfo=timezone.utc,
)


def _source(
    *,
    provider: EarningsProvider = EarningsProvider.SEC,
) -> EarningsDocumentCandidate:
    rule = nxpi_q2_2026_shadow_rule()
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=provider,
        provider_event_id="nxpi-q2-2026-document",
        ticker="NXPI",
        cik=NXP_CIK,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1413447/000141344726000099/exhibit991.htm"
        ),
        filing_url=(
            "https://www.sec.gov/Archives/edgar/data/"
            "1413447/000141344726000099/filing.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


def _document(value: str = "3.54") -> str:
    return f"""
    <html>
      <body>
        <h1>NXP Semiconductors Reports Second Quarter 2026 Results</h1>
        <p>
          NXP today reported financial results for the second quarter,
          which ended June 28, 2026.
        </p>
        <ul>
          <li>
            GAAP diluted Net Income per Share was $2.80;
          </li>
          <li>
            Non-GAAP diluted Net Income per Share was ${value};
          </li>
        </ul>
        <table>
          <tr>
            <td>Non-GAAP diluted Net Income (Loss) per Share</td>
            <td>$</td><td>{value}</td>
            <td>$</td><td>3.05</td>
          </tr>
          <tr>
            <td>Earnings Per Share - diluted guidance</td>
            <td>$3.29</td><td>$3.50</td><td>$3.72</td>
          </tr>
        </table>
      </body>
    </html>
    """


class NxpNonGaapEpsParserTests(unittest.TestCase):
    def test_accepts_repeated_headline_and_table_value(self) -> None:
        result = NxpNonGaapEpsParser().parse(
            _document("3.54"),
            source=_source(),
            rule=nxpi_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        self.assertEqual(
            result.reason,
            "official_nxp_headline_non_gaap_diluted_eps",
        )
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("3.54"))
        self.assertEqual(result.candidate.basis.value, "diluted")
        self.assertEqual(result.candidate.confidence, Decimal("1"))

    def test_ignores_gaap_and_guidance_values(self) -> None:
        result = NxpNonGaapEpsParser().parse(
            _document("3.53"),
            source=_source(),
            rule=nxpi_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("3.53"))

    def test_rounds_with_standard_half_up_semantics(self) -> None:
        result = NxpNonGaapEpsParser().parse(
            _document("3.535"),
            source=_source(),
            rule=nxpi_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.raw_value, Decimal("3.535"))
        self.assertEqual(result.candidate.value, Decimal("3.54"))

    def test_wrong_period_is_quarantined(self) -> None:
        result = NxpNonGaapEpsParser().parse(
            _document()
            .replace("Second Quarter", "First Quarter")
            .replace("second quarter", "first quarter")
            .replace("June 28, 2026", "March 29, 2026"),
            source=_source(),
            rule=nxpi_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "fiscal_period_not_confirmed")

    def test_conflicting_headline_values_are_quarantined(self) -> None:
        conflicting = _document("3.54").replace(
            "</ul>",
            (
                "<li>Non-GAAP diluted Net Income per Share "
                "was $3.55;</li></ul>"
            ),
        )
        result = NxpNonGaapEpsParser().parse(
            conflicting,
            source=_source(),
            rule=nxpi_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_nxp_headline_eps_values",
        )

    def test_rule_requires_nxp_context(self) -> None:
        result = NxpNonGaapEpsParser().parse(
            _document(),
            source=replace(_source(), ticker="OTHER"),
            rule=nxpi_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "source_ticker_mismatch")


if __name__ == "__main__":
    unittest.main()
