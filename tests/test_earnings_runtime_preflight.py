from __future__ import annotations

import contextlib
import io
import json
import unittest

from cbr_trading.earnings.parsers import checked_in_shadow_rules
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from scripts.check_earnings_shadow_runtime import main


class _Store:
    def __init__(self, *, database_url=None, rules=()):
        self.database_url = database_url
        self.rules = tuple(rules)
        self.closed = False
        self.ready = False

    def ensure_ready(self):
        self.ready = True

    def load_active_rules(self):
        return self.rules

    def close(self):
        self.closed = True


class EarningsRuntimePreflightTests(unittest.TestCase):
    def test_reports_names_and_counts_without_secret_values(self) -> None:
        database_url = "postgresql://user:password@example/app"
        sec_key = "sec-credential"
        created = []

        def factory(**kwargs):
            store = _Store(
                **kwargs,
                rules=[nvts_q2_2026_shadow_rule()],
            )
            created.append(store)
            return store

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                environ={
                    "CBR_DATABASE_URL": database_url,
                    "SEC_API_KEY": sec_key,
                    "EARNINGS_HTTP_USER_AGENT": (
                        "CodexPoly test@example.com"
                    ),
                },
                store_factory=factory,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["active_rule_count"], 1)
        self.assertEqual(payload["watch_count"], 1)
        self.assertNotIn(database_url, stdout.getvalue())
        self.assertNotIn(sec_key, stdout.getvalue())
        self.assertTrue(created[0].ready)
        self.assertTrue(created[0].closed)

    def test_missing_credential_still_checks_non_secret_runtime(self) -> None:
        created = []

        def factory(**kwargs):
            store = _Store(
                **kwargs,
                rules=[nvts_q2_2026_shadow_rule()],
            )
            created.append(store)
            return store

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(
                environ={
                    "CBR_DATABASE_URL": "postgresql://configured",
                    "EARNINGS_HTTP_USER_AGENT": (
                        "CodexPoly test@example.com"
                    ),
                },
                store_factory=factory,
            )

        payload = json.loads(stderr.getvalue())
        self.assertEqual(exit_code, 5)
        self.assertFalse(payload["sec_credential_present"])
        self.assertEqual(payload["watch_count"], 1)
        self.assertNotIn("postgresql://configured", stderr.getvalue())
        self.assertTrue(created[0].ready)

    def test_all_checked_in_rules_have_runtime_parsers(self) -> None:
        stdout = io.StringIO()

        def factory(**kwargs):
            return _Store(
                **kwargs,
                rules=checked_in_shadow_rules(),
            )

        with contextlib.redirect_stdout(stdout):
            exit_code = main(
                environ={
                    "CBR_DATABASE_URL": "postgresql://configured",
                    "SEC_API_KEY": "configured",
                    "EARNINGS_HTTP_USER_AGENT": (
                        "CodexPoly test@example.com"
                    ),
                },
                store_factory=factory,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["active_rule_count"], 8)
        self.assertEqual(payload["watch_count"], 8)
        self.assertEqual(payload["missing_parsers"], [])


if __name__ == "__main__":
    unittest.main()
