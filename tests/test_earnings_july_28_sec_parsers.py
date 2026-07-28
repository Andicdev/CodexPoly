from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsMetric,
    EarningsProvider,
    ParseStatus,
    SourceAuthority,
)
from cbr_trading.earnings.parsers.july_28_sec import (
    CocaColaComparableEpsParser,
    FordAdjustedDilutedEpsParser,
    HiltonAdjustedDilutedEpsParser,
    InvescoAdjustedDilutedEpsParser,
    JetBlueAdjustedDilutedEpsParser,
    PayPalNonGaapEpsParser,
    SpGlobalAdjustedDilutedEpsParser,
    StarbucksGaapEpsParser,
    UpsAdjustedDilutedEpsParser,
    VisaNonGaapEpsParser,
    ford_q2_2026_shadow_rule,
    hlt_q2_2026_shadow_rule,
    ivz_q2_2026_shadow_rule,
    jblu_q2_2026_shadow_rule,
    ko_q2_2026_shadow_rule,
    pypl_q2_2026_shadow_rule,
    sbux_q3_2026_shadow_rule,
    spgi_q2_2026_shadow_rule,
    ups_q2_2026_shadow_rule,
    visa_q3_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 28, 10, 0, 5, tzinfo=timezone.utc)


def _source(
    rule,
    *,
    provider: EarningsProvider = EarningsProvider.SEC,
    source_url: str = "https://www.sec.gov/example-exhibit",
) -> EarningsDocumentCandidate:
    is_sec = provider is EarningsProvider.SEC
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=provider,
        provider_event_id=f"test:{rule.ticker}",
        ticker=rule.ticker,
        cik=rule.cik,
        form_type="8-K" if is_sec else "PRESS_RELEASE",
        items=("Item 2.02", "Item 9.01") if is_sec else (),
        document_type="EX-99.1" if is_sec else "HTML",
        source_url=source_url,
        filing_url=(
            "https://www.sec.gov/example-filing"
            if is_sec
            else source_url
        ),
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="test",
    )


class July28SecParserTests(unittest.TestCase):
    def test_historical_reported_values_are_selected(self) -> None:
        cases = (
            (
                PayPalNonGaapEpsParser(),
                pypl_q2_2026_shadow_rule(),
                (
                    "PayPal reports second quarter 2026 results. "
                    "GAAP EPS decreased 6% to $1.21; "
                    "non-GAAP EPS increased 1% to $1.34."
                ),
                "1.34",
            ),
            (
                UpsAdjustedDilutedEpsParser(),
                ups_q2_2026_shadow_rule(),
                (
                    "UPS releases second quarter 2026 earnings. "
                    "Diluted EPS of $1.02; Non-GAAP Adj. "
                    "Diluted EPS of $1.07."
                ),
                "1.07",
            ),
            (
                HiltonAdjustedDilutedEpsParser(),
                hlt_q2_2026_shadow_rule(),
                (
                    "Hilton reported its second quarter 2026 results. "
                    "Diluted EPS was $2.10 for the second quarter, and "
                    "diluted EPS, adjusted for special items, was "
                    "$2.29. For the three months ended June 30, 2026, "
                    "diluted EPS was $2.10 and diluted EPS, adjusted "
                    "for special items, was $2.29. For the six months "
                    "ended June 30, 2026, diluted EPS was $3.76 and "
                    "diluted EPS, adjusted for special items, was "
                    "$4.30. Diluted EPS, "
                    "adjusted for special items, is projected to be "
                    "between $2.18 and $2.24."
                ),
                "2.29",
            ),
            (
                InvescoAdjustedDilutedEpsParser(),
                ivz_q2_2026_shadow_rule(),
                (
                    "Invesco Announces Second Quarter 2026 Diluted "
                    "EPS of $0.51; Adjusted Diluted EPS (1) of $0.57."
                ),
                "0.57",
            ),
            (
                CocaColaComparableEpsParser(),
                ko_q2_2026_shadow_rule(),
                (
                    "Coca-Cola reports second quarter 2026 results. "
                    "EPS grew 18% to $0.91; Comparable EPS "
                    "(Non-GAAP) grew 18% to $0.86."
                ),
                "0.86",
            ),
            (
                JetBlueAdjustedDilutedEpsParser(),
                jblu_q2_2026_shadow_rule(),
                (
                    "<h1>JetBlue second quarter 2026 results</h1>"
                    "<table><tr><th>Diluted excluding special items "
                    "and gain on investments</th><td>$ (0.87)</td>"
                    "<td>$ (0.59)</td></tr></table>"
                ),
                "-0.87",
            ),
            (
                SpGlobalAdjustedDilutedEpsParser(),
                spgi_q2_2026_shadow_rule(),
                (
                    "S&P Global reports second quarter 2026 results. "
                    "Adjusted diluted earnings per share increased "
                    "14% to $4.97."
                ),
                "4.97",
            ),
            (
                StarbucksGaapEpsParser(),
                sbux_q3_2026_shadow_rule(),
                (
                    "Starbucks reports third quarter fiscal 2026 "
                    "results. Q3 GAAP EPS $0.49, Non-GAAP EPS $0.50."
                ),
                "0.49",
            ),
            (
                VisaNonGaapEpsParser(),
                visa_q3_2026_shadow_rule(),
                (
                    "<h1>Visa third quarter fiscal 2026 results</h1>"
                    "<table><tr><th>Non-GAAP Earnings Per Share (1)"
                    "</th><td>$3.31</td><td>20%</td></tr></table>"
                ),
                "3.31",
            ),
            (
                FordAdjustedDilutedEpsParser(),
                ford_q2_2026_shadow_rule(),
                (
                    "<h1>Ford second quarter 2026 results</h1>"
                    "<table><tr><th>Adjusted Earnings Per Share – "
                    "Diluted (Non-GAAP)</th><td>$0.14</td>"
                    "<td>$0.66</td></tr></table>"
                ),
                "0.14",
            ),
        )

        for parser, rule, document, expected in cases:
            with self.subTest(ticker=rule.ticker):
                result = parser.parse(
                    document,
                    source=_source(rule),
                    rule=rule,
                    detected_at=_DETECTED,
                )
                self.assertEqual(result.status, ParseStatus.ACCEPTED)
                self.assertIsNotNone(result.candidate)
                self.assertEqual(
                    str(result.candidate.value),
                    expected,
                )

    def test_hilton_company_ir_html_selects_adjusted_eps(self) -> None:
        rule = hlt_q2_2026_shadow_rule()
        source_url = (
            "https://stories.hilton.com/releases/"
            "hilton-reports-2026-second-quarter-results"
        )
        result = HiltonAdjustedDilutedEpsParser().parse(
            (
                "<html><body><h1>Hilton Reports 2026 Second Quarter "
                "Results</h1><p>For the quarter ended June 30, 2026, "
                "diluted EPS was $1.66, and diluted "
                "EPS, adjusted for special items, was $2.01.</p>"
                "<p>Diluted EPS, adjusted for special items, is "
                "projected to be between $2.18 and $2.24.</p>"
                "</body></html>"
            ),
            source=_source(
                rule,
                provider=EarningsProvider.COMPANY_IR,
                source_url=source_url,
            ),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        self.assertIsNotNone(result.candidate)
        self.assertEqual(str(result.candidate.value), "2.01")

    def test_hilton_six_month_value_is_not_a_quarter_result(self) -> None:
        rule = hlt_q2_2026_shadow_rule()
        result = HiltonAdjustedDilutedEpsParser().parse(
            (
                "Hilton reported its second quarter 2026 results. "
                "For the six months ended June 30, 2026, diluted EPS "
                "was $3.76 and diluted EPS, adjusted for special "
                "items, was $4.30."
            ),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)

    def test_guidance_and_wrong_metric_fail_closed(self) -> None:
        cases = (
            (
                HiltonAdjustedDilutedEpsParser(),
                hlt_q2_2026_shadow_rule(),
                (
                    "Hilton second quarter 2026 outlook: diluted EPS, "
                    "adjusted for special items, is projected to be "
                    "between $2.18 and $2.24."
                ),
            ),
            (
                StarbucksGaapEpsParser(),
                sbux_q3_2026_shadow_rule(),
                (
                    "Starbucks third quarter fiscal 2026 results. "
                    "Q3 Non-GAAP EPS $0.50."
                ),
            ),
        )

        for parser, rule, document in cases:
            with self.subTest(ticker=rule.ticker):
                result = parser.parse(
                    document,
                    source=_source(rule),
                    rule=rule,
                    detected_at=_DETECTED,
                )
                self.assertEqual(result.status, ParseStatus.NO_MATCH)

    def test_rules_match_source_and_market_basis(self) -> None:
        rules = (
            pypl_q2_2026_shadow_rule(),
            ups_q2_2026_shadow_rule(),
            hlt_q2_2026_shadow_rule(),
            ivz_q2_2026_shadow_rule(),
            ko_q2_2026_shadow_rule(),
            jblu_q2_2026_shadow_rule(),
            spgi_q2_2026_shadow_rule(),
            sbux_q3_2026_shadow_rule(),
            visa_q3_2026_shadow_rule(),
            ford_q2_2026_shadow_rule(),
        )

        self.assertEqual(len({rule.condition_id for rule in rules}), 10)
        self.assertTrue(
            all(
                rule.source_policy["sec"]["required_item"] == "2.02"
                for rule in rules
            )
        )
        hlt_rule = hlt_q2_2026_shadow_rule()
        self.assertEqual(
            hlt_rule.source_policy["company_ir"],
            {
                "kind": "rss",
                "provider": "company_ir",
                "feed_url": "https://stories.hilton.com/feed/",
                "allowed_document_hosts": ["stories.hilton.com"],
                "title_all": [
                    "Hilton",
                    "Second Quarter",
                    "Results",
                ],
                "title_none": ["Announces", "Release Date"],
            },
        )
        self.assertTrue(
            all(
                "company_ir" not in rule.source_policy
                for rule in rules
                if rule.ticker != "HLT"
            )
        )
        self.assertEqual(
            sbux_q3_2026_shadow_rule().metric,
            EarningsMetric.GAAP_EPS,
        )
        self.assertEqual(
            sbux_q3_2026_shadow_rule().estimated_release_at.isoformat(),
            "2026-07-29T20:05:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
