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
from cbr_trading.earnings.parsers.july_29_sec import (
    AresCapitalCoreEpsParser,
    CbreGaapEpsParser,
    EbayNonGaapEpsParser,
    GarminProFormaDilutedEpsParser,
    HumanaAdjustedEpsParser,
    IntegraAdjustedDilutedEpsParser,
    MetaGaapEpsParser,
    MicrosoftGaapEpsParser,
    PenskeAutomotiveGaapEpsParser,
    ProcterGambleCoreEpsParser,
    QualcommNonGaapEpsParser,
    RobinhoodGaapEpsParser,
    SofiGaapEpsParser,
    WingstopGaapEpsParser,
    arcc_q2_2026_shadow_rule,
    cbre_q2_2026_shadow_rule,
    ebay_q2_2026_shadow_rule,
    grmn_q2_2026_shadow_rule,
    hood_q2_2026_shadow_rule,
    hum_q2_2026_shadow_rule,
    iart_q2_2026_shadow_rule,
    meta_q2_2026_shadow_rule,
    msft_q4_2026_shadow_rule,
    pag_q2_2026_shadow_rule,
    pg_q4_2026_shadow_rule,
    qcom_q3_2026_shadow_rule,
    sofi_q2_2026_shadow_rule,
    wing_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 29, 20, 5, 5, tzinfo=timezone.utc)


def _source(rule) -> EarningsDocumentCandidate:
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id=f"test:{rule.ticker}",
        ticker=rule.ticker,
        cik=rule.cik,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url="https://www.sec.gov/example-exhibit",
        filing_url="https://www.sec.gov/example-filing",
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="test",
    )


class July29SecParserTests(unittest.TestCase):
    def test_historical_release_shapes_select_market_metric(self) -> None:
        cases = (
            (
                SofiGaapEpsParser(),
                sofi_q2_2026_shadow_rule(),
                (
                    "SoFi reports second quarter 2026 results. "
                    "GAAP net income reached $166.7 million and "
                    "diluted earnings per share reached $0.12. "
                    "Full-year adjusted EPS guidance is $0.60."
                ),
                "0.12",
            ),
            (
                ProcterGambleCoreEpsParser(),
                pg_q4_2026_shadow_rule(),
                (
                    "P&G announces fourth quarter and fiscal year "
                    "2026 results. Fiscal Year Results. Core net "
                    "earnings per share increased four percent to "
                    "$6.90. April-June Quarter Results. Net sales "
                    "were $21.0 billion. Core net earnings per share "
                    "increased six percent to $1.48."
                ),
                "1.48",
            ),
            (
                HumanaAdjustedEpsParser(),
                hum_q2_2026_shadow_rule(),
                (
                    "Humana reports second quarter 2026 results. "
                    "Reports 2Q26 earnings per share (EPS) of $6.41 "
                    "on a GAAP basis, Adjusted EPS of $7.15. "
                    "Adjusted FY 2026 EPS guidance is at least $9.00."
                ),
                "7.15",
            ),
            (
                WingstopGaapEpsParser(),
                wing_q2_2026_shadow_rule(),
                (
                    "Wingstop reports fiscal second quarter 2026 "
                    "financial results for the quarter ended "
                    "June 27, 2026. Net income of $31.2 million, "
                    "or $1.08 per diluted share. Adjusted earnings "
                    "per diluted share were $1.17."
                ),
                "1.08",
            ),
            (
                AresCapitalCoreEpsParser(),
                arcc_q2_2026_shadow_rule(),
                (
                    "Ares Capital Corporation announces June 30, "
                    "2026 financial results for the second quarter "
                    "of 2026. Operating Results. Core EPS(2) "
                    "$0.49. GAAP net income per share $0.13."
                ),
                "0.49",
            ),
            (
                IntegraAdjustedDilutedEpsParser(),
                iart_q2_2026_shadow_rule(),
                (
                    "Integra LifeSciences reports second quarter "
                    "2026 financial results for the quarter ending "
                    "June 30, 2026. GAAP earnings per diluted share "
                    "were $0.04. Adjusted earnings per diluted share "
                    "of $0.51."
                ),
                "0.51",
            ),
            (
                GarminProFormaDilutedEpsParser(),
                grmn_q2_2026_shadow_rule(),
                (
                    "Garmin announces second quarter 2026 results "
                    "for the 13-weeks ended June 27, 2026. GAAP EPS "
                    "of $2.20 and pro forma EPS(1) of $2.31."
                ),
                "2.31",
            ),
            (
                CbreGaapEpsParser(),
                cbre_q2_2026_shadow_rule(),
                (
                    "CBRE Group reports financial results for Q2 "
                    "2026 for the quarter ended June 30, 2026. "
                    "GAAP EPS up 23% to $1.35 and Core EPS up 18% "
                    "to $2.01."
                ),
                "1.35",
            ),
            (
                PenskeAutomotiveGaapEpsParser(),
                pag_q2_2026_shadow_rule(),
                (
                    "Penske Automotive Group reports quarterly "
                    "results for the second quarter ended June 30, "
                    "2026. Adjusted earnings per share of $3.10. "
                    "Earnings Before Taxes of $320 Million; Net "
                    "Income of $225 Million; Earnings Per Share of "
                    "$3.42."
                ),
                "3.42",
            ),
            (
                QualcommNonGaapEpsParser(),
                qcom_q3_2026_shadow_rule(),
                (
                    "Qualcomm Announces Third Quarter Fiscal 2026 "
                    "Results. Revenues: $10.6 billion. GAAP EPS: "
                    "$6.88, Non-GAAP EPS: $2.65."
                ),
                "2.65",
            ),
            (
                MicrosoftGaapEpsParser(),
                msft_q4_2026_shadow_rule(),
                (
                    "Microsoft announces fourth quarter fiscal 2026 "
                    "results for the quarter ended June 30, 2026. "
                    "Diluted earnings per share was $4.27 and "
                    "increased 23% on a GAAP basis."
                ),
                "4.27",
            ),
            (
                MetaGaapEpsParser(),
                meta_q2_2026_shadow_rule(),
                (
                    "<h1>Meta Reports Second Quarter 2026 Results</h1>"
                    "<h2>Second Quarter 2026 Financial Highlights</h2>"
                    "<table><tr><th>Diluted earnings per share "
                    "(EPS) (1)</th><td>$7.34</td><td>$5.16</td>"
                    "</tr></table>"
                ),
                "7.34",
            ),
            (
                EbayNonGaapEpsParser(),
                ebay_q2_2026_shadow_rule(),
                (
                    "eBay reports second quarter 2026 results. "
                    "GAAP and Non-GAAP earnings per diluted share "
                    "of $1.12 and $1.66, respectively, on a "
                    "continuing operations basis."
                ),
                "1.66",
            ),
            (
                RobinhoodGaapEpsParser(),
                hood_q2_2026_shadow_rule(),
                (
                    "Robinhood reports second quarter 2026 results. "
                    "Diluted earnings per share (EPS) increased 3% "
                    "to $0.38, compared to Q2 2025."
                ),
                "0.38",
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
                self.assertEqual(str(result.candidate.value), expected)

    def test_wrong_metric_and_guidance_only_fail_closed(self) -> None:
        cases = (
            (
                SofiGaapEpsParser(),
                sofi_q2_2026_shadow_rule(),
                (
                    "SoFi second quarter 2026 outlook. Adjusted "
                    "earnings per share guidance is $0.60."
                ),
            ),
            (
                ProcterGambleCoreEpsParser(),
                pg_q4_2026_shadow_rule(),
                (
                    "P&G fourth quarter 2026 outlook. Core EPS "
                    "guidance is between $1.40 and $1.50."
                ),
            ),
            (
                QualcommNonGaapEpsParser(),
                qcom_q3_2026_shadow_rule(),
                (
                    "Qualcomm third quarter fiscal 2026 results. "
                    "GAAP EPS was $2.10."
                ),
            ),
            (
                WingstopGaapEpsParser(),
                wing_q2_2026_shadow_rule(),
                (
                    "Wingstop second quarter 2026 outlook for the "
                    "quarter ending June 27, 2026. Adjusted earnings "
                    "per diluted share guidance is $1.20."
                ),
            ),
            (
                GarminProFormaDilutedEpsParser(),
                grmn_q2_2026_shadow_rule(),
                (
                    "Garmin second quarter 2026 results for the "
                    "quarter ended June 27, 2026. GAAP diluted EPS "
                    "was $2.40."
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

    def test_rules_match_gamma_market_and_sec_policy(self) -> None:
        rules = (
            sofi_q2_2026_shadow_rule(),
            pg_q4_2026_shadow_rule(),
            hum_q2_2026_shadow_rule(),
            wing_q2_2026_shadow_rule(),
            arcc_q2_2026_shadow_rule(),
            iart_q2_2026_shadow_rule(),
            grmn_q2_2026_shadow_rule(),
            cbre_q2_2026_shadow_rule(),
            pag_q2_2026_shadow_rule(),
            qcom_q3_2026_shadow_rule(),
            msft_q4_2026_shadow_rule(),
            meta_q2_2026_shadow_rule(),
            ebay_q2_2026_shadow_rule(),
            hood_q2_2026_shadow_rule(),
        )

        self.assertEqual(len({rule.condition_id for rule in rules}), 14)
        self.assertTrue(
            all(
                rule.source_policy["sec"]["form_type"] == "8-K"
                and rule.source_policy["sec"]["required_item"] == "2.02"
                and rule.source_policy["sec"]["document_type"] == "EX-99.1"
                for rule in rules
            )
        )
        self.assertEqual(
            {rule.ticker for rule in rules if rule.metric is EarningsMetric.GAAP_EPS},
            {"SOFI", "WING", "CBRE", "PAG", "MSFT", "META", "HOOD"},
        )
        self.assertEqual(
            {rule.ticker for rule in rules if rule.metric is EarningsMetric.NON_GAAP_EPS},
            {
                "PG",
                "HUM",
                "ARCC",
                "IART",
                "GRMN",
                "QCOM",
                "EBAY",
            },
        )
        self.assertEqual(
            hum_q2_2026_shadow_rule().estimated_release_at.isoformat(),
            "2026-07-29T10:00:00+00:00",
        )
        self.assertEqual(
            qcom_q3_2026_shadow_rule().estimated_release_at.isoformat(),
            "2026-07-29T20:05:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
