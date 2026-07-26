from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from cbr_trading.db_config import DatabaseSelection
from scripts import manage_mstr_btc_audit_schema


class _Store:
    last: "_Store | None" = None

    def __init__(self, *, database_url):
        self.database_url = database_url
        self.migrated = False
        self.ready = False
        self.closed = False
        _Store.last = self

    def migrate(self):
        self.migrated = True

    def ensure_ready(self):
        self.ready = True

    def close(self):
        self.closed = True


class ManageMstrBtcAuditSchemaTests(unittest.TestCase):
    def test_apply_checks_schema_without_printing_database_url(self) -> None:
        output = io.StringIO()
        database_url = "postgresql://user:password@example/app"
        with (
            patch.object(
                manage_mstr_btc_audit_schema,
                "resolve_database_selection",
                return_value=DatabaseSelection(
                    role="primary",
                    target="server_int",
                    source="DATABASE_APP_PASSWORD",
                    url=database_url,
                ),
            ),
            patch.object(
                manage_mstr_btc_audit_schema,
                "SqlAlchemyMstrBtcAuditStore",
                _Store,
            ),
            patch.object(
                manage_mstr_btc_audit_schema,
                "_load_dotenv_if_available",
            ),
            patch("sys.stdout", output),
        ):
            exit_code = manage_mstr_btc_audit_schema.main(("--apply",))

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["applied"])
        self.assertNotIn(database_url, output.getvalue())
        assert _Store.last is not None
        self.assertTrue(_Store.last.migrated)
        self.assertTrue(_Store.last.ready)
        self.assertTrue(_Store.last.closed)


if __name__ == "__main__":
    unittest.main()
