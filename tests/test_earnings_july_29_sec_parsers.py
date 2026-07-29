from __future__ import annotations

import unittest
from dataclasses import replace
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
    ElectronicArtsGaapEpsParser,
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
    ea_q1_2027_shadow_rule,
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
                ElectronicArtsGaapEpsParser(),
                ea_q1_2027_shadow_rule(),
                (
                    "<h1>Electronic Arts Reports Q1 FY27 Results</h1>"
                    "<p>Quarterly Financial Highlights for the "
                    "three months ended June 30, 2026.</p>"
                    "<table><tr><th>Diluted earnings per share</th>"
                    "<td>$0.84</td><td>$1.04</td></tr></table>"
                    "<table><tr><th>Diluted earnings per share</th>"
                    "<td>$1.04</td><td>$0.98</td><td>$0.79</td>"
                    "</tr></table>"
                    "<p>Fiscal year diluted EPS outlook: $4.00.</p>"
                ),
                "0.84",
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

    def test_july_29_official_ir_release_replays(self) -> None:
        cases = (
            (
                CbreGaapEpsParser(),
                cbre_q2_2026_shadow_rule(),
                (
                    "CBRE Group, Inc. today reported financial "
                    "results for the second quarter ended June 30, "
                    "2026. Key Highlights: GAAP EPS of $0.69 and "
                    "Core EPS of $1.56. Revenue up 16%."
                ),
                "0.69",
                "2",
            ),
            (
                WingstopGaapEpsParser(),
                wing_q2_2026_shadow_rule(),
                (
                    "Wingstop Inc. Reports Fiscal Second Quarter "
                    "Financial Results for the quarter ended "
                    "June 27, 2026. Q2 2026 Highlights. Net income, "
                    "increased 16.9% to $31.3 million, or $1.15 per "
                    "diluted share. Adjusted earnings per diluted "
                    "share increased to $1.18."
                ),
                "1.15",
                "2",
            ),
            (
                IntegraAdjustedDilutedEpsParser(),
                iart_q2_2026_shadow_rule(),
                (
                    "Integra LifeSciences Reports Second Quarter "
                    "2026 Financial Results for the quarter ending "
                    "June 30, 2026. Second quarter GAAP earnings "
                    "per diluted share of $0.06. Adjusted earnings "
                    "per diluted share of $0.56, compared to $0.45 "
                    "in the prior year."
                ),
                "0.56",
                "1",
            ),
        )

        for parser, rule, document, expected, version in cases:
            with self.subTest(ticker=rule.ticker):
                source = replace(
                    _source(rule),
                    provider=EarningsProvider.COMPANY_IR,
                    form_type="PRESS_RELEASE",
                    items=(),
                    document_type="HTML",
                    source_url=f"https://example.com/{rule.ticker}",
                    filing_url=f"https://example.com/{rule.ticker}",
                )

                result = parser.parse(
                    document,
                    source=source,
                    rule=rule,
                    detected_at=_DETECTED,
                )

                self.assertEqual(result.status, ParseStatus.ACCEPTED)
                assert result.candidate is not None
                self.assertEqual(str(result.candidate.value), expected)
                self.assertEqual(result.candidate.parser_version, version)

    def test_arcc_and_pag_production_release_replays(self) -> None:
        cases = (
            (
                AresCapitalCoreEpsParser(),
                arcc_q2_2026_shadow_rule(),
                (
                    "Ares Capital announces financial results for "
                    "the second quarter ended June 30, 2026. "
                    "<table><tr><th></th><th>Q2-26 (3)</th>"
                    "<th>Q2-25 (3)</th></tr><tr><td>GAAP net "
                    "income per share(1)</td><td>$0.24</td>"
                    "<td>$0.52</td></tr><tr><td>Core EPS(2)</td>"
                    "<td>$0.47</td><td>$0.50</td></tr></table>"
                ),
                "0.47",
                EarningsProvider.SEC,
            ),
            (
                PenskeAutomotiveGaapEpsParser(),
                pag_q2_2026_shadow_rule(),
                (
                    "Penske Automotive reports financial results "
                    "for the second quarter ended June 30, 2026. "
                    "Earnings Per Share of $3.96. Adjusted Earnings "
                    "Per Share of $3.62. For the quarter, revenue "
                    "was $8.5 billion. Net income attributable to "
                    "common stockholders was $260.4 million, and "
                    "related earnings per share was $3.96 compared "
                    "to $4.03 for the same period in 2025."
                ),
                "3.96",
                EarningsProvider.PR_NEWSWIRE,
            ),
        )

        for parser, rule, document, expected, provider in cases:
            with self.subTest(ticker=rule.ticker):
                source = replace(
                    _source(rule),
                    provider=provider,
                    form_type="PRESS_RELEASE",
                    items=(),
                    document_type="HTML",
                )

                result = parser.parse(
                    document,
                    source=source,
                    rule=rule,
                    detected_at=_DETECTED,
                )

                self.assertEqual(result.status, ParseStatus.ACCEPTED)
                assert result.candidate is not None
                self.assertEqual(str(result.candidate.value), expected)
                self.assertEqual(result.candidate.parser_version, "2")

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
            (
                CbreGaapEpsParser(),
                cbre_q2_2026_shadow_rule(),
                (
                    "CBRE second quarter 2026 outlook for the "
                    "quarter ended June 30, 2026. GAAP EPS guidance "
                    "of $1.40 to $1.50."
                ),
            ),
            (
                AresCapitalCoreEpsParser(),
                arcc_q2_2026_shadow_rule(),
                (
                    "Ares Capital second quarter 2026 outlook for "
                    "the period ending June 30, 2026. Core EPS "
                    "guidance is expected to be $0.52."
                ),
            ),
            (
                PenskeAutomotiveGaapEpsParser(),
                pag_q2_2026_shadow_rule(),
                (
                    "Penske Automotive second quarter 2026 outlook "
                    "for the period ending June 30, 2026. Expected "
                    "earnings per share of $3.96."
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
