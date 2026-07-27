from __future__ import annotations

import unittest
from pathlib import Path


_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "cbr_trading"
    / "migrations"
    / "010_add_source_notification_outbox.sql"
)


class SourceNotificationMigrationTests(unittest.TestCase):
    def test_migration_is_additive_and_idempotent(self) -> None:
        text = _MIGRATION.read_text(encoding="utf-8").lower()

        self.assertIn(
            "create table if not exists source_notification_outbox",
            text,
        )
        self.assertIn(
            "create unique index if not exists "
            "ux_source_notification_outbox_key",
            text,
        )
        self.assertNotIn("drop table", text)
        self.assertNotIn("alter table", text)


if __name__ == "__main__":
    unittest.main()
