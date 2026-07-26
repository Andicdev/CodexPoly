from __future__ import annotations

import unittest
from datetime import datetime, timezone

from cbr_trading.mstr_btc import (
    MSTR_JUL21_27_SCOPE_ID,
    MstrBtcRouter,
    mstr_jul21_27_shadow_watch,
)


_RECEIVED_AT = datetime(
    2026,
    7,
    27,
    12,
    0,
    2,
    tzinfo=timezone.utc,
)


def _filing(**changes: object) -> dict[str, object]:
    filing: dict[str, object] = {
        "ticker": "MSTR",
        "cik": "0001050446",
        "companyName": "Strategy Inc",
        "accessionNo": "0001193125-26-399999",
        "formType": "8-K",
        "filedAt": "2026-07-27T08:00:01-04:00",
        "items": ["Item 8.01: Other Events"],
        "description": "Form 8-K - Item 8.01",
        "linkToFilingDetails": (
            "https://www.sec.gov/Archives/edgar/data/1050446/"
            "filing-index.htm"
        ),
        "documentFormatFiles": [
            {
                "type": "8-K",
                "description": "FORM 8-K",
                "documentUrl": (
                    "https://www.sec.gov/Archives/edgar/data/1050446/"
                    "mstr-20260727.htm"
                ),
                "sequence": "1",
            },
            {
                "type": "EX-99.1",
                "description": "EXHIBIT 99.1",
                "documentUrl": (
                    "https://www.sec.gov/Archives/edgar/data/1050446/"
                    "ex991.htm"
                ),
                "sequence": "2",
            },
        ],
    }
    filing.update(changes)
    return filing


class MstrBtcSecRouterTests(unittest.TestCase):
    def test_routes_primary_8k_without_earnings_item(self) -> None:
        decision = MstrBtcRouter(
            mstr_jul21_27_shadow_watch()
        ).route(
            _filing(),
            received_at=_RECEIVED_AT,
        )

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason, "official_mstr_initial_8k")
        candidate = decision.candidate
        assert candidate is not None
        self.assertEqual(candidate.scope_id, MSTR_JUL21_27_SCOPE_ID)
        self.assertEqual(candidate.ticker, "MSTR")
        self.assertTrue(candidate.source_url.endswith("mstr-20260727.htm"))
        self.assertFalse(candidate.source_url.endswith("ex991.htm"))

    def test_fails_closed_for_amendment_or_outside_window(self) -> None:
        router = MstrBtcRouter(mstr_jul21_27_shadow_watch())
        cases = (
            (_filing(formType="8-K/A"), "not_initial_8k"),
            (
                _filing(filedAt="2026-07-20T08:00:01-04:00"),
                "outside_event_window",
            ),
            (
                _filing(documentFormatFiles=[]),
                "primary_8k_document_missing",
            ),
        )
        for filing, expected_reason in cases:
            with self.subTest(reason=expected_reason):
                decision = router.route(
                    filing,
                    received_at=_RECEIVED_AT,
                )
                self.assertFalse(decision.accepted)
                self.assertEqual(decision.reason, expected_reason)

    def test_issuer_mismatch_is_never_routed(self) -> None:
        decision = MstrBtcRouter(
            mstr_jul21_27_shadow_watch()
        ).route(
            _filing(cik="999999"),
            received_at=_RECEIVED_AT,
        )

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "cik_mismatch")


if __name__ == "__main__":
    unittest.main()
