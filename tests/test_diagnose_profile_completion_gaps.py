from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from io import StringIO

from scripts.diagnose_profile_completion_gaps import (
    _GAPS_SQL,
    _safe_gap,
    main,
)


class DiagnoseProfileCompletionGapsTests(unittest.TestCase):
    def test_confirmation_is_required_before_database_resolution(
        self,
    ) -> None:
        with redirect_stderr(StringIO()):
            self.assertEqual(
                main(
                    ["--confirm", "WRONG"],
                    environ={},
                ),
                2,
            )

    def test_query_is_read_only_and_returns_no_secret_fields(
        self,
    ) -> None:
        upper = _GAPS_SQL.upper()
        self.assertIn("SCHEDULE.STATE = 'COMPLETED'", upper)
        self.assertIn("PROFILE.STATUS = 'DISABLED'", upper)
        self.assertIn("CLAIM.STATUS = 'EXECUTED'", upper)
        self.assertIn(
            "ORDER_GROUP.STATUS IN ('ACTIVE', 'REPRICING')",
            upper,
        )
        self.assertNotIn("ACCOUNT_NAME", upper)
        self.assertNotIn("ORDER_ID", upper)
        self.assertNotIn("RESULT AS", upper)
        self.assertNotIn("ERROR AS", upper)

    def test_safe_gap_has_fixed_allowlist(self) -> None:
        payload = _safe_gap(
            {
                "schedule_key": "schedule:earnings-example",
                "profile_key": "earnings-example",
                "scope_id": "earnings:EXAMPLE:2026Q2",
                "automation_mode": "AUTO_LIVE",
                "schedule_state": "COMPLETED",
                "profile_status": "DISABLED",
                "completion_reason": "manual",
                "terminal_reason": None,
                "updated_at": datetime(
                    2026,
                    7,
                    30,
                    tzinfo=timezone.utc,
                ),
                "claim_count": 2,
                "accepted_execution_count": 1,
                "expired_claim_count": 1,
                "validated_fact_count": 1,
                "active_order_group_count": 0,
                "lifecycle_events": [
                    {
                        "previous_state": "ACTIVE",
                        "next_state": "COMPLETED",
                        "event_kind": "MANUAL_COMPLETION",
                        "reason_code": "manual",
                        "created_at": datetime(
                            2026,
                            7,
                            30,
                            tzinfo=timezone.utc,
                        ),
                        "unexpected": "not emitted",
                    }
                ],
                "unexpected": "not emitted",
            }
        )

        self.assertEqual(payload["accepted_execution_count"], 1)
        self.assertEqual(
            payload["updated_at"],
            "2026-07-30T00:00:00+00:00",
        )
        self.assertEqual(
            payload["lifecycle_events"][0]["event_kind"],
            "MANUAL_COMPLETION",
        )
        self.assertNotIn(
            "unexpected",
            payload["lifecycle_events"][0],
        )
        self.assertNotIn("unexpected", payload)


if __name__ == "__main__":
    unittest.main()
