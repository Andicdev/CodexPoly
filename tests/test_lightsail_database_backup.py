from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = (
    ROOT / "deploy" / "lightsail" / "database" / "backup-postgres.sh"
)


class LightsailDatabaseBackupTests(unittest.TestCase):
    def test_backs_up_core_and_neg_risk_databases(self) -> None:
        script = BACKUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("CODEXPOLY_BACKUP_DATABASES", script)
        self.assertIn(
            "${CODEXPOLY_BACKUP_DATABASES:-codexpoly codexpoly_neg_risk}",
            script,
        )
        self.assertIn("readonly database_names", script)

    def test_rejects_invalid_configured_database_names(self) -> None:
        script = BACKUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("^[a-z][a-z0-9_]*$", script)
        self.assertIn("Invalid PostgreSQL database name", script)

    def test_pg_dump_streams_to_host_and_rejects_empty_output(self) -> None:
        script = BACKUP_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("--file -", script)
        self.assertIn('if [[ ! -s "${temporary_file}" ]]', script)
        self.assertIn('--no-owner >"${temporary_file}"', script)


if __name__ == "__main__":
    unittest.main()
