from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "deploy" / "lightsail" / "database"
CHECKS_DIR = ROOT / "neg_risk_trading" / "checks"


class NegRiskMigrationRunnerTests(unittest.TestCase):
    def test_shared_runner_whitelists_only_two_databases(
        self,
    ) -> None:
        script = (
            DATABASE_DIR / "run-postgres-migration.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "codexpoly|codexpoly_neg_risk)",
            script,
        )
        self.assertIn(
            '--dbname "${database_name}"',
            script,
        )
        self.assertIn(
            "MIGRATION_REASON=invalid-database",
            script,
        )

    def test_neg_risk_wrappers_fix_environment_and_database(
        self,
    ) -> None:
        staging = (
            DATABASE_DIR
            / "codexpoly-staging-neg-risk-migrate"
        ).read_text(encoding="utf-8")
        production = (
            DATABASE_DIR
            / "codexpoly-production-neg-risk-migrate"
        ).read_text(encoding="utf-8")

        self.assertIn("arguments-not-allowed", staging)
        self.assertIn("staging \\\n    codexpoly_neg_risk", staging)
        self.assertIn("arguments-not-allowed", production)
        self.assertIn(
            "production \\\n    codexpoly_neg_risk",
            production,
        )

    def test_production_wrapper_has_narrow_sudo_rule(
        self,
    ) -> None:
        sudoers = (
            DATABASE_DIR
            / "codexpoly-production-migrations.sudoers"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "NOPASSWD: "
            "/usr/local/sbin/"
            "codexpoly-production-neg-risk-migrate",
            sudoers,
        )

    def test_active_recorder_check_is_value_safe(
        self,
    ) -> None:
        sql = (
            CHECKS_DIR
            / "verify_staging_recorder_active.sql"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "latest_status <> 'READY'",
            sql,
        )
        self.assertIn(
            "latest_live_orders_enabled",
            sql,
        )
        self.assertIn(
            "persisted_message_count < 1",
            sql,
        )
        self.assertIn(
            "persisted_route_count < 1",
            sql,
        )
        self.assertNotIn("SELECT *", sql.upper())


if __name__ == "__main__":
    unittest.main()
