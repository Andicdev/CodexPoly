from __future__ import annotations

import unittest
from pathlib import Path

from scripts import check_no_secrets


class SecretScanTests(unittest.TestCase):
    def test_detects_without_returning_the_value(self) -> None:
        secret = "postgresql://worker:password@db.example/app"

        findings = check_no_secrets.scan_text(
            f"DATABASE_URL_SERVER_EXT={secret}",
            path=Path("sample.env"),
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].detector, "sensitive-assignment")
        self.assertNotIn(secret, repr(findings))

    def test_allows_blank_example_values(self) -> None:
        findings = check_no_secrets.scan_text(
            "TG_BOT_TOKEN=\nACCOUNTS_MASTER_KEY=",
            path=Path(".env.example"),
        )

        self.assertEqual(findings, [])

    def test_allows_python_environment_lookup_and_topic_hash(self) -> None:
        text = (
            'DATABASE_URL_SERVER_EXT = os.getenv("DATABASE_URL_SERVER_EXT")\n'
            f'ORDER_FILLED_TOPIC0 = "0x{"a" * 64}"'
        )

        findings = check_no_secrets.scan_text(
            text,
            path=Path("config.py"),
        )

        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
