from __future__ import annotations

import unittest

from cbr_trading.secret_guard import (
    PROTECTED_RUNTIME_KEYS,
    redact_exception,
    redact_sensitive_text,
    secret_presence,
)


class SecretGuardTests(unittest.TestCase):
    def test_redacts_sensitive_assignments_and_credentials(self) -> None:
        telegram_token = "123456789:" + "A" * 35
        database_url = "postgresql://worker:password@db.example/app"
        private_key = "0x" + "a" * 64
        source = (
            f"TG_BOT_TOKEN={telegram_token} "
            f"url={database_url} key={private_key}"
        )

        result = redact_sensitive_text(source)

        self.assertNotIn(telegram_token, result)
        self.assertNotIn("password", result)
        self.assertNotIn(private_key, result)
        self.assertIn("TG_BOT_TOKEN=[REDACTED]", result)
        self.assertIn("postgresql://[REDACTED]@db.example/app", result)

    def test_redacts_telegram_bot_url(self) -> None:
        token = "123456789:" + "B" * 35
        source = f"https://api.telegram.org/bot{token}/sendMessage"

        result = redact_sensitive_text(source)

        self.assertNotIn(token, result)
        self.assertIn("/bot[REDACTED]/sendMessage", result)

    def test_exception_preserves_type_but_not_secret(self) -> None:
        secret = "postgresql://user:password@db.example/app"

        result = redact_exception(RuntimeError(f"failed for {secret}"))

        self.assertTrue(result.startswith("RuntimeError:"))
        self.assertNotIn("password", result)

    def test_can_preserve_safe_multiline_notification_layout(self) -> None:
        token = "123456789:" + "C" * 35
        source = (
            "Source document: https://www.sec.gov/example.htm\n"
            f"TG_BOT_TOKEN={token}\n"
            "Rule: value > 1 -> YES"
        )

        result = redact_sensitive_text(
            source,
            max_length=4_000,
            preserve_newlines=True,
        )

        self.assertEqual(result.count("\n"), 2)
        self.assertIn(
            "Source document: https://www.sec.gov/example.htm",
            result,
        )
        self.assertIn("Rule: value > 1 -> YES", result)
        self.assertNotIn(token, result)
        self.assertIn("TG_BOT_TOKEN=[REDACTED]", result)

    def test_redacts_sec_api_key_assignment(self) -> None:
        secret = "sec-api-credential"

        result = redact_sensitive_text(
            f"SEC_API_STREAM_KEY={secret}"
        )

        self.assertNotIn(secret, result)
        self.assertEqual(
            result,
            "SEC_API_STREAM_KEY=[REDACTED]",
        )

    def test_redacts_encrypted_trading_key_assignment(self) -> None:
        secret = "encrypted-private-key"

        result = redact_sensitive_text(
            f"TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED={secret}"
        )

        self.assertNotIn(secret, result)
        self.assertEqual(
            result,
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED=[REDACTED]",
        )

    def test_redacts_account_specific_encrypted_key_assignment(
        self,
    ) -> None:
        secret = "account-specific-encrypted-key"

        result = redact_sensitive_text(
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_KINDERSMAN="
            f"{secret}"
        )

        self.assertNotIn(secret, result)
        self.assertEqual(
            result,
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_KINDERSMAN="
            "[REDACTED]",
        )

    def test_presence_report_contains_names_only(self) -> None:
        values = {
            "DATABASE_URL_SERVER_EXT": "database-secret",
            "ACCOUNTS_MASTER_KEY": "master-secret",
            "TG_BOT_TOKEN": "telegram-secret",
        }

        report = secret_presence(values)
        payload = report.as_dict()

        self.assertFalse(report.ok)
        self.assertEqual(
            payload["missing_keys"],
            ["TELEGRAM_INGEST_CHAT_ID"],
        )
        rendered = str(payload)
        for value in values.values():
            self.assertNotIn(value, rendered)
        self.assertEqual(report.required_keys, PROTECTED_RUNTIME_KEYS)


if __name__ == "__main__":
    unittest.main()
