from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsProvider,
    ParseStatus,
    SourceAuthority,
)
from cbr_trading.earnings.parsers import (
    MastercardAdjustedDilutedEpsParser,
    VirtuNormalizedAdjustedEpsParser,
    checked_in_shadow_rules,
    earnings_parser_registry,
    mastercard_q2_2026_shadow_rule,
    virt_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 30, 11, 0, 1, tzinfo=timezone.utc)


def _source(rule=None) -> EarningsDocumentCandidate:
    rule = rule or virt_q2_2026_shadow_rule()
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=EarningsProvider.SEC,
        provider_event_id="test:VIRT:final",
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


class July30SecParserTests(unittest.TestCase):
    def test_mastercard_release_accepts_headline_adjusted_diluted_eps(
        self,
    ) -> None:
        rule = mastercard_q2_2026_shadow_rule()
        result = MastercardAdjustedDilutedEpsParser().parse(
            (
                "Mastercard Incorporated Reports Second Quarter "
                "2026 Financial Results. Second quarter net income "
                "of $4.2 billion, and diluted earnings per share "
                "(EPS) of $4.51. Second quarter adjusted net income "
                "of $4.5 billion, and adjusted diluted EPS of $4.83. "
                "Adjusted - Non-GAAP $4.83 $4.10."
            ),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(str(result.candidate.value), "4.83")
        self.assertEqual(
            result.candidate.attributes["resolution_basis"],
            "primary_headline_adjusted_diluted_eps",
        )

    def test_mastercard_gaap_or_table_only_document_does_not_match(
        self,
    ) -> None:
        rule = mastercard_q2_2026_shadow_rule()
        result = MastercardAdjustedDilutedEpsParser().parse(
            (
                "Mastercard second quarter 2026 diluted EPS of $4.51. "
                "Adjusted diluted EPS $4.83 $4.10."
            ),
            source=_source(rule),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertIsNone(result.candidate)

    def test_final_virtu_release_accepts_normalized_adjusted_eps(self) -> None:
        result = VirtuNormalizedAdjustedEpsParser().parse(
            (
                "Virtu Announces Second Quarter 2026 Results for "
                "the quarter ended June 30, 2026. Basic and diluted "
                "earnings per share of $1.68; Normalized Adjusted "
                "EPS of $1.87. Reconciliation to Non-GAAP Operating "
                "Data. Normalized Adjusted EPS $1.87 $1.53."
            ),
            source=_source(),
            rule=virt_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(str(result.candidate.value), "1.87")
        self.assertEqual(
            result.candidate.attributes["resolution_basis"],
            "primary_normalized_adjusted_non_gaap_eps",
        )

    def test_preliminary_virtu_release_is_quarantined(self) -> None:
        result = VirtuNormalizedAdjustedEpsParser().parse(
            (
                "Virtu Announces Preliminary Estimated Second "
                "Quarter 2026 Results for the quarter ended "
                "June 30, 2026. Normalized Adjusted EPS of $1.82. "
                "The foregoing estimates are subject to revision "
                "and are not a substitute for full financial "
                "statements."
            ),
            source=_source(),
            rule=virt_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "virtu_preliminary_results_not_final",
        )
        self.assertIsNone(result.candidate)

    def test_gaap_only_document_does_not_match(self) -> None:
        result = VirtuNormalizedAdjustedEpsParser().parse(
            (
                "Virtu Announces Second Quarter 2026 Results for "
                "the quarter ended June 30, 2026. Basic and diluted "
                "earnings per share of $1.68."
            ),
            source=_source(),
            rule=virt_q2_2026_shadow_rule(),
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertIsNone(result.candidate)

    def test_rule_and_registry_are_checked_in(self) -> None:
        rule = virt_q2_2026_shadow_rule()
        self.assertEqual(rule.condition_id, (
            "0xe51d31ccfbad36c133152ce07533e5ba"
            "ee5db4bf2b02f76df7192fce363ac770"
        ))
        self.assertEqual(str(rule.strike), "1.82")
        self.assertTrue(
            rule.source_policy["reject_preliminary_results"]
        )
        self.assertEqual(
            rule.source_policy["press_wire"]["provider"],
            "globenewswire",
        )
        self.assertIn("VIRT", earnings_parser_registry())
        self.assertEqual(
            sum(
                candidate.scope_id == "earnings:VIRT:2026Q2"
                for candidate in checked_in_shadow_rules()
            ),
            1,
        )

        mastercard = mastercard_q2_2026_shadow_rule()
        self.assertEqual(mastercard.condition_id, (
            "0x9aa5ff923c2669e27ce9be9631deb177"
            "19afd08d877237e9bf24d853b75893a1"
        ))
        self.assertEqual(str(mastercard.strike), "4.77")
        self.assertEqual(
            mastercard.source_policy["press_wire"]["provider"],
            "businesswire",
        )
        self.assertIn("MA", earnings_parser_registry())
        self.assertEqual(
            sum(
                candidate.scope_id == "earnings:MA:2026Q2"
                for candidate in checked_in_shadow_rules()
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
