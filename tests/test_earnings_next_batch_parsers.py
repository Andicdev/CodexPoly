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
from cbr_trading.earnings.parsers.boeing import (
    BOEING_CIK,
    BoeingCoreEpsParser,
    ba_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.caesars import (
    CAESARS_CIK,
    CaesarsGaapEpsParser,
    czr_q2_2026_shadow_rule,
)
from cbr_trading.earnings.parsers.costar import (
    COSTAR_CIK,
    CostarGaapEpsParser,
    csgp_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 28, 20, 5, 5, tzinfo=timezone.utc)


def _source(
    *,
    ticker: str,
    cik: str,
    scope_id: str,
    provider: EarningsProvider = EarningsProvider.SEC,
) -> EarningsDocumentCandidate:
    return EarningsDocumentCandidate(
        scope_id=scope_id,
        provider=provider,
        provider_event_id=f"{ticker.casefold()}-q2-2026-document",
        ticker=ticker,
        cik=cik,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url=f"https://www.sec.gov/{ticker.casefold()}.htm",
        filing_url=(
            f"https://www.sec.gov/{ticker.casefold()}-index.htm"
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


class BoeingCoreEpsParserTests(unittest.TestCase):
    def test_accepts_boeing_parenthesized_core_loss(self) -> None:
        rule = ba_q2_2026_shadow_rule()
        document = """
        <h1>Boeing Reports Second Quarter 2026 Results</h1>
        <p>The quarter ended June 30, 2026.</p>
        <p>
          GAAP loss per share of ($0.11) and core loss per share
          (non-GAAP)* of ($0.20).
        </p>
        <table>
          <tr>
            <td>Core loss per share</td>
            <td>($0.20)</td><td>($0.49)</td>
          </tr>
        </table>
        """

        result = BoeingCoreEpsParser().parse(
            document,
            source=_source(
                ticker="BA",
                cik=BOEING_CIK,
                scope_id=rule.scope_id,
            ),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.20"))
        self.assertEqual(result.candidate.metric.value, "non_gaap_eps")
        self.assertEqual(result.candidate.basis.value, "diluted")

    def test_does_not_substitute_gaap_eps_for_core_eps(self) -> None:
        rule = ba_q2_2026_shadow_rule()
        result = BoeingCoreEpsParser().parse(
            (
                "<h1>Second Quarter 2026</h1>"
                "<p>Quarter ended June 30, 2026.</p>"
                "<p>GAAP diluted loss per share was ($0.11).</p>"
            ),
            source=_source(
                ticker="BA",
                cik=BOEING_CIK,
                scope_id=rule.scope_id,
            ),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)


class CaesarsGaapEpsParserTests(unittest.TestCase):
    def test_accepts_current_gaap_diluted_loss(self) -> None:
        rule = czr_q2_2026_shadow_rule()
        document = """
        <h1>
          Caesars Entertainment, Inc. Reports Second Quarter 2026 Results
        </h1>
        <p>For the quarter ended June 30, 2026.</p>
        <table>
          <tr>
            <td>Diluted loss per share</td>
            <td>$</td><td>(0.08)</td>
            <td>$</td><td>(0.54)</td>
          </tr>
        </table>
        """

        result = CaesarsGaapEpsParser().parse(
            document,
            source=_source(
                ticker="CZR",
                cik=CAESARS_CIK,
                scope_id=rule.scope_id,
            ),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("-0.08"))
        self.assertEqual(result.candidate.metric.value, "gaap_eps")

    def test_wrong_company_context_is_quarantined(self) -> None:
        rule = czr_q2_2026_shadow_rule()
        source = _source(
            ticker="CZR",
            cik=CAESARS_CIK,
            scope_id=rule.scope_id,
        )

        result = CaesarsGaapEpsParser().parse(
            (
                "<h1>Second Quarter 2026 Results</h1>"
                "<p>June 30, 2026</p>"
                "<p>Diluted earnings per share $0.06</p>"
            ),
            source=replace(source, cik="1"),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(result.reason, "source_cik_mismatch")


class CostarGaapEpsParserTests(unittest.TestCase):
    def test_ignores_adjusted_and_non_gaap_eps(self) -> None:
        rule = csgp_q2_2026_shadow_rule()
        document = """
        <h1>CoStar Group Reports Second Quarter 2026 Results</h1>
        <p>For the quarter ended June 30, 2026.</p>
        <p>
          Net income was $50 million and earnings per diluted share
          was $0.12. Adjusted EPS was $0.31.
        </p>
        <table>
          <tr>
            <td>Net income (loss) per share - diluted</td>
            <td>$0.12</td><td>$0.01</td>
          </tr>
          <tr>
            <td>Non-GAAP net income per share - diluted</td>
            <td>$0.31</td><td>$0.17</td>
          </tr>
        </table>
        """

        result = CostarGaapEpsParser().parse(
            document,
            source=_source(
                ticker="CSGP",
                cik=COSTAR_CIK,
                scope_id=rule.scope_id,
            ),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("0.12"))
        self.assertEqual(result.candidate.metric.value, "gaap_eps")

    def test_conflicting_gaap_values_are_quarantined(self) -> None:
        rule = csgp_q2_2026_shadow_rule()
        result = CostarGaapEpsParser().parse(
            """
            <h1>CoStar Group Second Quarter 2026 Results</h1>
            <p>Quarter ended June 30, 2026.</p>
            <p>Earnings per diluted share was $0.12.</p>
            <p>Earnings per diluted share was $0.13.</p>
            """,
            source=_source(
                ticker="CSGP",
                cik=COSTAR_CIK,
                scope_id=rule.scope_id,
            ),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_costar_gaap_diluted_eps_values",
        )


if __name__ == "__main__":
    unittest.main()
