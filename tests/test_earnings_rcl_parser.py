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
from cbr_trading.earnings.parsers.royal_caribbean import (
    ROYAL_CARIBBEAN_CIK,
    RoyalCaribbeanAdjustedEpsParser,
    rcl_q2_2026_shadow_rule,
)


_DETECTED = datetime(2026, 7, 28, 10, 30, 5, tzinfo=timezone.utc)


def _source(
    *,
    provider: EarningsProvider = EarningsProvider.SEC,
) -> EarningsDocumentCandidate:
    rule = rcl_q2_2026_shadow_rule()
    return EarningsDocumentCandidate(
        scope_id=rule.scope_id,
        provider=provider,
        provider_event_id="rcl-q2-2026-document",
        ticker="RCL",
        cik=ROYAL_CARIBBEAN_CIK,
        form_type="8-K",
        items=("Item 2.02", "Item 9.01"),
        document_type="EX-99.1",
        source_url="https://www.sec.gov/rcl-q2.htm",
        filing_url="https://www.sec.gov/rcl-q2-index.htm",
        filed_at=_DETECTED,
        received_at=_DETECTED,
        authority=SourceAuthority.OFFICIAL_COMPANY,
        transport_fingerprint="transport-fingerprint",
    )


class RoyalCaribbeanAdjustedEpsParserTests(unittest.TestCase):
    def test_accepts_primary_adjusted_eps_headline(self) -> None:
        rule = rcl_q2_2026_shadow_rule()
        result = RoyalCaribbeanAdjustedEpsParser().parse(
            """
            <h1>
              Royal Caribbean Group Reports Second Quarter Results
            </h1>
            <p>MIAMI - July 28, 2026 - Royal Caribbean Group today
              reported second quarter Earnings per Share ("EPS") of
              $3.88 and Adjusted EPS of $4.02.</p>
            <p>
              The company expects third quarter Adjusted EPS to be in
              the range of $5.80 to $5.90.
            </p>
            """,
            source=_source(),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.ACCEPTED)
        assert result.candidate is not None
        self.assertEqual(result.candidate.value, Decimal("4.02"))
        self.assertEqual(
            result.candidate.metric.value,
            "non_gaap_eps",
        )
        self.assertEqual(result.candidate.basis.value, "diluted")

    def test_guidance_is_not_substituted_for_reported_eps(self) -> None:
        rule = rcl_q2_2026_shadow_rule()
        result = RoyalCaribbeanAdjustedEpsParser().parse(
            """
            <h1>Royal Caribbean Group Second Quarter 2026 Update</h1>
            <p>The quarter ended June 30, 2026.</p>
            <p>
              The company expects third quarter Adjusted EPS in the
              range of $5.80 to $5.90.
            </p>
            """,
            source=_source(),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.NO_MATCH)
        self.assertEqual(
            result.reason,
            "royal_caribbean_adjusted_eps_headline_not_found",
        )

    def test_conflicting_headline_values_are_quarantined(self) -> None:
        rule = rcl_q2_2026_shadow_rule()
        result = RoyalCaribbeanAdjustedEpsParser().parse(
            """
            <h1>Royal Caribbean Second Quarter 2026 Results</h1>
            <p>
              The company reported second quarter Earnings per Share
              ("EPS") of $3.88 and Adjusted EPS of $4.02.
            </p>
            <p>
              A duplicate section reported second quarter Earnings per
              Share ("EPS") of $3.88 and Adjusted EPS of $4.03.
            </p>
            """,
            source=_source(),
            rule=rule,
            detected_at=_DETECTED,
        )

        self.assertEqual(result.status, ParseStatus.QUARANTINED)
        self.assertEqual(
            result.reason,
            "conflicting_royal_caribbean_adjusted_eps_values",
        )


if __name__ == "__main__":
    unittest.main()
