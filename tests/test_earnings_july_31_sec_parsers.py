from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    EarningsTransport,
    ParseStatus,
    SourceAuthority,
)
from cbr_trading.earnings.parsers import (
    AresAfterTaxRealizedIncomePerShareParser,
    CboeAdjustedDilutedEpsParser,
    ChevronAdjustedDilutedEpsParser,
    ColgateBaseBusinessDilutedEpsParser,
    FranklinAdjustedDilutedEpsParser,
    ModernaGaapBasicAndDilutedEpsParser,
    ares_q2_2026_shadow_rule,
    ben_q3_2026_shadow_rule,
    cboe_q2_2026_shadow_rule,
    checked_in_shadow_rules,
    cl_q2_2026_shadow_rule,
    cvx_q2_2026_shadow_rule,
    earnings_parser_registry,
    mrna_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 31, 11, 0, 1, tzinfo=timezone.utc)


def _source(rule) -> EarningsDocumentCandidate:
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=f"test:{rule.ticker}:2026",
        ticker=rule.ticker,
        cik=rule.cik,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url="https://www.sec.gov/example",
        filing_url="https://www.sec.gov/example",
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="test",
        transport=EarningsTransport.SEC_API_WEBSOCKET,
    )


class July31SecParserTests(unittest.TestCase):
    def _assert_value(self, parser, rule, document: str, expected: str) -> None:
        result = parser.parse(
            document,
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED, result.reason)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal(expected))

    def test_ben_adjusted_diluted_eps(self) -> None:
        self._assert_value(
            FranklinAdjustedDilutedEpsParser(),
            ben_q3_2026_shadow_rule(),
            (
                "Franklin Resources announces third quarter 2026 results "
                "for the quarter ended June 30, 2026. Adjusted net income "
                "was $400 million and adjusted diluted earnings per share "
                "was $0.72 for the quarter ended June 30, 2026."
            ),
            "0.72",
        )

    def test_cboe_adjusted_diluted_eps(self) -> None:
        self._assert_value(
            CboeAdjustedDilutedEpsParser(),
            cboe_q2_2026_shadow_rule(),
            (
                "Cboe reports second quarter 2026 results for the quarter "
                "ended June 30, 2026. Adjusted diluted EPS 1 of $3.55 "
                "increased compared with the prior year."
            ),
            "3.55",
        )

    def test_chevron_adjusted_summary_row(self) -> None:
        self._assert_value(
            ChevronAdjustedDilutedEpsParser(),
            cvx_q2_2026_shadow_rule(),
            (
                "Chevron reports second quarter 2026 results for June 30, "
                "2026. Adjusted Earnings Per Share - Diluted (1) $/Share "
                "$ 5.44 $ 1.41 $ 2.18."
            ),
            "5.44",
        )

    def test_colgate_base_business_eps(self) -> None:
        self._assert_value(
            ColgateBaseBusinessDilutedEpsParser(),
            cl_q2_2026_shadow_rule(),
            (
                "Colgate announces second quarter 2026 results for June "
                "30, 2026. Base Business EPS (diluted) $0.96 $0.92 +4%."
            ),
            "0.96",
        )

    def test_moderna_gaap_loss_per_share(self) -> None:
        self._assert_value(
            ModernaGaapBasicAndDilutedEpsParser(),
            mrna_q2_2026_shadow_rule(),
            (
                "Moderna reports second quarter 2026 results for June 30, "
                "2026. Net loss per share __EARNINGS_ROW__ Basic and "
                "Diluted $ (1.99) $ (3.40)."
            ),
            "-1.99",
        )

    def test_ares_after_tax_realized_income_per_share(self) -> None:
        self._assert_value(
            AresAfterTaxRealizedIncomePerShareParser(),
            ares_q2_2026_shadow_rule(),
            (
                "Ares Management reports second quarter 2026 results for "
                "June 30, 2026. After-tax realized income per share of "
                "Class A common stock was $1.31 for the quarter ended "
                "June 30, 2026."
            ),
            "1.31",
        )

    def test_wrong_period_and_metric_lookalikes_fail_closed(self) -> None:
        rule = cl_q2_2026_shadow_rule()
        wrong_period = ColgateBaseBusinessDilutedEpsParser().parse(
            (
                "First quarter 2026 results for March 31, 2026. "
                "Base Business EPS (diluted) $0.97."
            ),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )
        self.assertEqual(wrong_period.status, ParseStatus.QUARANTINED)

        cvx = cvx_q2_2026_shadow_rule()
        gaap_only = ChevronAdjustedDilutedEpsParser().parse(
            (
                "Second quarter 2026 results for June 30, 2026. "
                "Earnings Per Share - Diluted $/Share $ 5.44."
            ),
            source=_source(cvx),
            rule=cvx,
            detected_at=_DETECTED,
        )
        self.assertEqual(gaap_only.status, ParseStatus.NO_MATCH)

    def test_rules_and_registry_are_checked_in(self) -> None:
        registry = earnings_parser_registry()
        for ticker in ("BEN", "CBOE", "CVX", "CL", "MRNA", "ARES"):
            self.assertIn(ticker, registry)

        scopes = {rule.scope_id for rule in checked_in_shadow_rules()}
        self.assertTrue(
            {
                "earnings:BEN:2026Q3",
                "earnings:CBOE:2026Q2",
                "earnings:CVX:2026Q2",
                "earnings:CL:2026Q2",
                "earnings:MRNA:2026Q2",
                "earnings:ARES:2026Q2",
            }.issubset(scopes)
        )


if __name__ == "__main__":
    unittest.main()
