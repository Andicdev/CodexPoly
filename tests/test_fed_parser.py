from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from cbr_trading.fed import (
    FedDecisionParseError,
    html_visible_text,
    parse_fomc_target_range,
)


_RELEASE_DATE = date(2026, 7, 29)


class FedParserTests(unittest.TestCase):
    def test_parses_fractional_statement_range(self) -> None:
        decision = parse_fomc_target_range(
            """
            July 29, 2026
            The Committee decided to maintain the target range for the
            federal funds rate at 3-1/2 to 3-3/4 percent.
            """,
            expected_release_date=_RELEASE_DATE,
        )

        self.assertEqual(decision.lower, Decimal("3.5"))
        self.assertEqual(decision.upper, Decimal("3.75"))

    def test_parses_implementation_note_word_order(self) -> None:
        decision = parse_fomc_target_range(
            """
            July 29, 2026
            Undertake open market operations as necessary to maintain the
            federal funds rate in a target range of 3-3/4 to 4 percent.
            """,
            expected_release_date=_RELEASE_DATE,
        )

        self.assertEqual(decision.lower, Decimal("3.75"))
        self.assertEqual(decision.upper, Decimal("4"))

    def test_parses_cut_statement_wording(self) -> None:
        decision = parse_fomc_target_range(
            """
            September 17, 2025
            The Committee decided to lower the target range for the
            federal funds rate by 1/4 percentage point to
            4 to 4-1/4 percent.
            """,
            expected_release_date=date(2025, 9, 17),
        )

        self.assertEqual(decision.lower, Decimal("4"))
        self.assertEqual(decision.upper, Decimal("4.25"))

    def test_parses_basis_point_change_wording(self) -> None:
        decision = parse_fomc_target_range(
            """
            July 29, 2026
            The Committee decided to raise the target range for the
            federal funds rate by 25 basis points, to
            3-3/4 to 4 percent.
            """,
            expected_release_date=_RELEASE_DATE,
        )

        self.assertEqual(decision.lower, Decimal("3.75"))
        self.assertEqual(decision.upper, Decimal("4"))

    def test_accepts_duplicate_identical_ranges_in_pdf_bundle(self) -> None:
        decision = parse_fomc_target_range(
            """
            July 29 2026
            target range for the federal funds rate at 3.50 to 3.75 percent
            federal funds rate in a target range of 3-1/2 to 3-3/4 percent
            """,
            expected_release_date=_RELEASE_DATE,
        )

        self.assertEqual(decision.upper, Decimal("3.75"))

    def test_supports_unicode_fraction_glyphs(self) -> None:
        decision = parse_fomc_target_range(
            """
            2026-07-29
            target range for the federal funds rate at 3½ to 3¾ percent
            """,
            expected_release_date=_RELEASE_DATE,
        )

        self.assertEqual(decision.lower, Decimal("3.5"))
        self.assertEqual(decision.upper, Decimal("3.75"))

    def test_rejects_wrong_release_date(self) -> None:
        with self.assertRaisesRegex(
            FedDecisionParseError,
            "expected release date",
        ):
            parse_fomc_target_range(
                """
                June 17, 2026
                target range for the federal funds rate
                at 3-1/2 to 3-3/4 percent
                """,
                expected_release_date=_RELEASE_DATE,
            )

    def test_rejects_conflicting_ranges(self) -> None:
        with self.assertRaisesRegex(
            FedDecisionParseError,
            "conflicting",
        ):
            parse_fomc_target_range(
                """
                July 29, 2026
                target range for the federal funds rate
                at 3-1/2 to 3-3/4 percent.
                federal funds rate in a target range
                of 3-3/4 to 4 percent.
                """,
                expected_release_date=_RELEASE_DATE,
            )

    def test_html_extractor_ignores_scripts(self) -> None:
        text = html_visible_text(
            b"""
            <html><head><script>
            target range for the federal funds rate at 1 to 2 percent
            </script></head><body>
            July 29, 2026. The Committee decided to maintain the
            target range for the federal funds rate at
            3-1/2 to 3-3/4 percent.
            </body></html>
            """
        )

        self.assertNotIn("1 to 2", text)
        self.assertIn("3-1/2 to 3-3/4", text)


if __name__ == "__main__":
    unittest.main()
