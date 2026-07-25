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
from cbr_trading.earnings.parsers.woodward import (
    WoodwardGaapEpsParser,
    wwd_q3_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 29, 20, 0, 5, tzinfo=timezone.utc)


def _source() -> EarningsDocumentCandidate:
    rule = wwd_q3_2026_shadow_rule()
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id="wwd-2026q3-accession",
        ticker=rule.ticker,
        cik=rule.cik,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url="https://www.sec.gov/wwd-exhibit991.htm",
        filing_url="https://www.sec.gov/wwd-filing.htm",
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="wwd-transport-fingerprint",
    )


def _document(
    *,
    period: str = "June 30, 2026",
    eps: str = "2.43",
    diluted_basis: bool = True,
) -> str:
    basis = (
        "All per share amounts are presented on a fully diluted basis."
        if diluted_basis
        else "Per-share values are unaudited."
    )
    return f"""
    <html><body>
      <p>Woodward reported results for the third quarter ended {period}.</p>
      <p>{basis}</p>
      <table>
        <tr><th></th><th>Third Quarter 2026</th><th>YTD 2026</th></tr>
        <tr><td>Adjusted EPS</td><td>$</td><td>2.51</td></tr>
        <tr>
          <td>Earnings per share (EPS)</td>
          <td>$</td><td>{eps}</td><td>$</td><td>6.79</td>
        </tr>
      </table>
    </body></html>
    """


class WoodwardGaapEpsParserTests(unittest.TestCase):
    def test_accepts_headline_gaap_diluted_eps(self) -> None:
        rule = wwd_q3_2026_shadow_rule()

        result = WoodwardGaapEpsParser().parse(
            _document(),
            source=_source(),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("2.43"))
        self.assertEqual(result.candidate.metric, rule.metric)
        self.assertEqual(
            result.candidate.basis,
            rule.primary_basis,
        )

    def test_rounds_standard_half_up(self) -> None:
        result = WoodwardGaapEpsParser().parse(
            _document(eps="2.425"),
            source=_source(),
            rule=wwd_q3_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("2.43"))

    def test_wrong_period_is_quarantined(self) -> None:
        result = WoodwardGaapEpsParser().parse(
            _document(period="March 31, 2026"),
            source=_source(),
            rule=wwd_q3_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "fiscal_period_not_confirmed")

    def test_diluted_basis_must_be_explicit(self) -> None:
        result = WoodwardGaapEpsParser().parse(
            _document(diluted_basis=False),
            source=_source(),
            rule=wwd_q3_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "diluted_basis_not_confirmed")

    def test_adjusted_eps_alone_is_not_gaap_match(self) -> None:
        document = _document().replace(
            "<tr>\n          <td>Earnings per share (EPS)</td>"
            "\n          <td>$</td><td>2.43</td><td>$</td>"
            "<td>6.79</td>\n        </tr>",
            "",
        )

        result = WoodwardGaapEpsParser().parse(
            document,
            source=_source(),
            rule=wwd_q3_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "woodward_gaap_eps_row_not_found",
        )


if __name__ == "__main__":
    unittest.main()
