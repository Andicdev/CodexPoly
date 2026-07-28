from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _ROOT
    / "cbr_trading"
    / "migrations"
    / "014_add_resolution_run_journal.sql"
)
_BACKFILL = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "006_backfill_july_28_run_journal.sql"
)
_KO_IVZ = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "007_record_ko_ivz_run_journal.sql"
)
_KO_COMPLETE = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "008_complete_ko_premarket_profile.sql"
)
_PYPL_JBLU = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "009_record_pypl_jblu_run_journal.sql"
)
_PYPL_JBLU_COMPLETE = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "010_complete_pypl_jblu_premarket_profiles.sql"
)
_JBLU_PARTIAL_FILL = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "live"
    / "011_record_jblu_partial_fill.sql"
)


class ResolutionRunJournalSchemaTests(unittest.TestCase):
    def test_migration_is_additive_and_tracks_required_outcomes(self) -> None:
        text = _MIGRATION.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("CREATE TABLE IF NOT EXISTS RESOLUTION_RUN_JOURNAL", upper)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS RESOLUTION_RUN_JOURNAL_EVENTS",
            upper,
        )
        for value in (
            "SUCCESS",
            "LATENCY_MISS",
            "MISSED_EXECUTION",
            "WRONG_DIRECTION",
            "ERROR",
            "ACCEPTED_OPEN",
            "FILLED",
            "TOO_SLOW",
        ):
            self.assertIn(f"'{value}'", upper)
        self.assertIn("SOURCE_LATENCY_MS", upper)
        self.assertIn("DECISION_LATENCY_MS", upper)
        self.assertIn("EXCHANGE_LATENCY_MS", upper)
        self.assertIn("ERRORS JSONB", upper)
        self.assertNotIn("ALTER TABLE", upper)
        self.assertNotIn("DROP TABLE", upper)
        self.assertNotIn("DELETE FROM", upper)

    def test_backfill_classifies_current_runs_without_touching_orders(self) -> None:
        text = _BACKFILL.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'EARNINGS:UPS:2026Q2'", upper)
        self.assertIn("'EARNINGS:HLT:2026Q2'", upper)
        self.assertIn("'EARNINGS:RCL:2026Q2'", upper)
        self.assertIn("'LATENCY_MISS'", upper)
        self.assertIn("'MISSED_EXECUTION'", upper)
        self.assertIn("'ACCEPTED_OPEN'", upper)
        self.assertIn("MATCHED_QUANTITY", upper)
        self.assertIn("ON CONFLICT (JOURNAL_KEY) DO UPDATE", upper)
        self.assertNotIn("UPDATE RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertNotIn("RESOLUTION_ORDER_GROUP", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL", upper)

    def test_ko_ivz_followup_records_reprice_and_parser_error(self) -> None:
        text = _KO_IVZ.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'EARNINGS:KO:2026Q2'", upper)
        self.assertIn("'EARNINGS:IVZ:2026Q2'", upper)
        self.assertIn("'DOCUMENT_ENCODING_INVALID'", upper)
        self.assertIn("'CURRENT_EFFECTIVE_PRICE'", upper)
        self.assertIn("'REPRICE_COUNT'", upper)
        self.assertIn("'RECOVERY_PENDING'", upper)
        self.assertNotIn("UPDATE RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL", upper)

    def test_ko_completion_does_not_touch_accepted_order(self) -> None:
        text = _KO_COMPLETE.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("AUTOMATION_MODE = 'MANUAL'", upper)
        self.assertIn("STATE = 'EXPIRED'", upper)
        self.assertIn("'ACCEPTED_ORDER_LEFT_UNCHANGED'", upper)
        self.assertNotIn("RESOLUTION_ORDER_GROUP", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL", upper)

    def test_pypl_jblu_followup_accepts_either_live_tick(self) -> None:
        text = _PYPL_JBLU.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("'EARNINGS:PYPL:2026Q2'", upper)
        self.assertIn("'EARNINGS:JBLU:2026Q2'", upper)
        self.assertIn("EFFECTIVE_PRICE IN (0.99, 0.999)", upper)
        self.assertIn("'CURRENT_EFFECTIVE_PRICE'", upper)
        self.assertNotIn("UPDATE RESOLUTION_EXECUTION_CLAIMS", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL", upper)

    def test_pypl_jblu_completion_leaves_order_groups_alone(self) -> None:
        text = _PYPL_JBLU_COMPLETE.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("AUTOMATION_MODE = 'MANUAL'", upper)
        self.assertIn("STATE = 'EXPIRED'", upper)
        self.assertIn("'ACCEPTED_ORDER_LEFT_UNCHANGED'", upper)
        self.assertNotIn("RESOLUTION_ORDER_GROUP", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL", upper)

    def test_jblu_partial_fill_is_success_with_slow_remainder(self) -> None:
        text = _JBLU_PARTIAL_FILL.read_text(encoding="utf-8")
        upper = text.upper()

        self.assertIn("EXECUTION_STATUS = 'PARTIALLY_FILLED'", upper)
        self.assertIn("OVERALL_RESULT = 'SUCCESS'", upper)
        self.assertIn("LATENCY_STATUS = 'TOO_SLOW'", upper)
        self.assertIn("'PARTIAL_FILL_OBSERVED'", upper)
        self.assertIn("MATCHED_QUANTITY = 16", upper)
        self.assertIn("REMAINING_QUANTITY = 34", upper)
        self.assertNotIn("UPDATE RESOLUTION_ORDER_GROUP_ORDERS", upper)
        self.assertNotIn("UPDATE RESOLUTION_ORDER_GROUPS", upper)
        self.assertNotIn("DELETE FROM", upper)
        self.assertNotIn("CANCEL_ORDERS", upper)


if __name__ == "__main__":
    unittest.main()
