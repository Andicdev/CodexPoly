from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "021_reconcile_july_29_executed_profiles.sql"
)
_DIAGNOSTIC = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "diagnose_july_29_completion_reconciliation.sql"
)
_VERIFY = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_july_29_completion_reconciliation.sql"
)
_GENERIC_VERIFY = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_profile_completion_runtime_invariants.sql"
)


class July29CompletionReconciliationSqlTests(unittest.TestCase):
    def test_migration_is_exact_guarded_and_order_preserving(
        self,
    ) -> None:
        text = _MIGRATION.read_text(encoding="utf-8")
        upper = text.upper()
        profiles = (
            "EARNINGS-SOFI-2026Q2",
            "EARNINGS-PG-2026Q4",
            "EARNINGS-HUM-2026Q2",
            "EARNINGS-IART-2026Q2",
            "EARNINGS-GRMN-2026Q2",
        )

        self.assertIn("BEGIN;", upper)
        self.assertIn("COMMIT;", upper)
        self.assertIn("FOR UPDATE OF SCHEDULE, PROFILE", upper)
        self.assertIn("STATUS = 'EXECUTED'", upper)
        self.assertIn("RESULT ->> 'ATTEMPTED' = 'TRUE'", upper)
        self.assertIn("RESULT ->> 'ACCEPTED' = 'TRUE'", upper)
        self.assertIn("STATUS = 'EXPIRED'", upper)
        self.assertIn("STATE = 'COMPLETED'", upper)
        self.assertIn("STATUS = 'DISABLED'", upper)
        self.assertIn(
            "'HISTORICAL_EXECUTED_CLAIM_RECONCILED'",
            upper,
        )
        self.assertIn("'EXISTING_ORDERS_LEFT_UNCHANGED'", upper)
        self.assertIn("ON CONFLICT (EVENT_KEY) DO NOTHING", upper)
        for profile in profiles:
            self.assertIn(f"'{profile}'", upper)

        self.assertNotIn("UPDATE RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertNotIn("RESOLUTION_ORDER_GROUP", upper)
        self.assertNotIn("UPDATE EARNINGS_MARKET_RULES", upper)
        self.assertNotIn("UPDATE EARNINGS_RELEASE_CATALOG", upper)
        self.assertNotIn("UPDATE RESOLUTION_RUN_JOURNAL", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL", upper)

    def test_diagnostic_and_verification_are_read_only(self) -> None:
        for path in (_DIAGNOSTIC, _VERIFY, _GENERIC_VERIFY):
            upper = path.read_text(encoding="utf-8").upper()

            self.assertIn("BEGIN TRANSACTION READ ONLY", upper)
            self.assertIn("ROLLBACK;", upper)
            self.assertNotIn("UPDATE ", upper)
            self.assertNotIn("INSERT ", upper)
            self.assertNotIn("DELETE ", upper)
            self.assertNotIn("CANCEL", upper)

    def test_generic_completion_invariant_distinguishes_live_and_historical(
        self,
    ) -> None:
        upper = _GENERIC_VERIFY.read_text(encoding="utf-8").upper()

        self.assertIn("'RESOLUTION_EXECUTION_COMPLETED'", upper)
        self.assertIn("'HISTORICAL_EXECUTED_CLAIM_RECONCILED'", upper)
        self.assertIn("EVENT.PREVIOUS_STATE = 'ACTIVE'", upper)
        self.assertIn(
            "EVENT.PREVIOUS_STATE IN (\n"
            "                            'ACTIVE',\n"
            "                            'BLOCKED'\n"
            "                        )",
            upper,
        )
        self.assertIn("'HISTORICAL_RECONCILIATION' = 'TRUE'", upper)
        self.assertIn(
            "'EXISTING_ORDERS_LEFT_UNCHANGED' = 'TRUE'",
            upper,
        )
        self.assertIn(
            "'POST_EVENT_RECONCILIATION_COMPLETED'",
            upper,
        )
        self.assertIn(
            "'OFFICIAL_RESULT_OBSERVED_EXECUTION_MISSING'",
            upper,
        )
        self.assertIn(
            "'OFFICIAL_RESULT_PARSER_QUARANTINED'",
            upper,
        )
        self.assertIn(
            "NOT EXISTS (\n"
            "                            SELECT 1\n"
            "                            FROM RESOLUTION_EXECUTION_CLAIMS",
            upper,
        )
        self.assertIn(
            "SOURCE.STATUS =\n"
            "                                          'QUARANTINED'",
            upper,
        )


if __name__ == "__main__":
    unittest.main()
