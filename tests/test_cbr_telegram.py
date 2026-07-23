from __future__ import annotations

import unittest

from cbr_trading.client import DiscoveryResult
from cbr_trading.pipeline import (
    OrderExecutionResult,
    OrderIntent,
    PipelineOutcome,
)
from cbr_trading.settings import CbrSettings
from cbr_trading.telegram import (
    TelegramError,
    TelegramNotifier,
    build_pipeline_message,
    build_release_message,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict,
    ):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[dict] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def _published_release() -> DiscoveryResult:
    return DiscoveryResult(
        ok=True,
        reason="published",
        url=(
            "https://www.cbr.ru/eng/press/pr/"
            "?file=19062026_133000key_e.htm"
        ),
        request_url="https://www.cbr.ru/release?_ts=1",
        status_code=200,
        content_type="text/html",
        title=(
            "Bank of Russia cuts the key rate by 25 bp "
            "to 14.25% p.a."
        ),
        new_rate=14.25,
    )


class TelegramSettingsTests(unittest.TestCase):
    def test_telegram_is_disabled_by_default(self) -> None:
        settings = CbrSettings.from_env({})
        self.assertFalse(settings.telegram_enabled)
        self.assertTrue(settings.dry_run)

    def test_enabled_telegram_requires_credentials(self) -> None:
        with self.assertRaisesRegex(ValueError, "TG_BOT_TOKEN"):
            CbrSettings.from_env({"CBR_TELEGRAM_ENABLED": "1"})

    def test_settings_repr_does_not_expose_token(self) -> None:
        settings = CbrSettings.from_env(
            {
                "CBR_TELEGRAM_ENABLED": "1",
                "TG_BOT_TOKEN": "123456:very-secret-token",
                "TELEGRAM_INGEST_CHAT_ID": "-100123",
            }
        )
        self.assertNotIn("very-secret-token", repr(settings))


class TelegramNotifierTests(unittest.TestCase):
    def test_builds_explicit_dry_run_message(self) -> None:
        message = build_release_message(
            _published_release(),
            dry_run=True,
        )
        self.assertIn("DRY RUN", message)
        self.assertIn("14.25%", message)
        self.assertIn("No orders were sent.", message)

    def test_pipeline_message_includes_order_outcome(self) -> None:
        intent = OrderIntent(
            rule_id=1,
            rule_key="cbr_cut",
            account_name="main",
            condition_id="condition-1",
            action="YES",
            quantity=100,
            limit_price=0.51,
            ready=True,
            reason="ready",
        )
        outcome = PipelineOutcome(
            release=_published_release(),
            previous_rate=14.5,
            change_bps=-25,
            direction="decrease",
            evaluations=(),
            order_results=(
                OrderExecutionResult(
                    intent=intent,
                    status="DRY_RUN",
                    attempted=False,
                    success=None,
                ),
            ),
        )

        message = build_pipeline_message(outcome, dry_run=True)

        self.assertIn("Change: -25 bp (decrease)", message)
        self.assertIn("DRY_RUN: YES", message)
        self.assertIn("No live orders were sent.", message)

    def test_live_message_includes_order_id_and_failure_detail(
        self,
    ) -> None:
        intent = OrderIntent(
            rule_id=1,
            rule_key="cbr_cut",
            account_name="main",
            condition_id="condition-1",
            action="YES",
            quantity=100,
            limit_price=0.20,
            ready=True,
            reason="ready",
        )
        outcome = PipelineOutcome(
            release=_published_release(),
            previous_rate=14.5,
            change_bps=-25,
            direction="decrease",
            evaluations=(),
            order_results=(
                OrderExecutionResult(
                    intent=intent,
                    status="LIVE",
                    attempted=True,
                    success=True,
                    order_id="order-123",
                ),
                OrderExecutionResult(
                    intent=intent,
                    status="SKIPPED",
                    attempted=False,
                    success=None,
                    error="safety:buy_would_cross_current_ask",
                ),
            ),
        )

        message = build_pipeline_message(outcome, dry_run=False)

        self.assertIn("order_id=order-123", message)
        self.assertIn(
            "detail: safety:buy_would_cross_current_ask",
            message,
        )

    def test_pipeline_message_reports_database_rule_failure(self) -> None:
        outcome = PipelineOutcome(
            release=_published_release(),
            previous_rate=14.5,
            change_bps=-25,
            direction="decrease",
            evaluations=(),
            order_results=(),
            rules_load_error="Failed to load rules: OperationalError",
        )

        message = build_pipeline_message(outcome, dry_run=True)

        self.assertIn("rule database unavailable", message)
        self.assertIn("Trading skipped", message)
        self.assertIn("No live orders were sent.", message)

    def test_pipeline_message_reports_no_active_rules(self) -> None:
        outcome = PipelineOutcome(
            release=_published_release(),
            previous_rate=14.5,
            change_bps=-25,
            direction="decrease",
            evaluations=(),
            order_results=(),
        )

        message = build_pipeline_message(outcome, dry_run=True)

        self.assertIn("Trading skipped: no active rules.", message)

    def test_sends_plain_text_message(self) -> None:
        session = FakeSession(
            FakeResponse(
                status_code=200,
                payload={
                    "ok": True,
                    "result": {"message_id": 42},
                },
            )
        )
        notifier = TelegramNotifier(
            bot_token="123456:test-token",
            chat_id="-100123",
            session=session,
        )

        result = notifier.notify_release(
            _published_release(),
            dry_run=True,
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.message_id, 42)
        self.assertEqual(len(session.calls), 1)
        payload = session.calls[0]["json"]
        self.assertNotIn("parse_mode", payload)
        self.assertIn("DRY RUN", payload["text"])
        self.assertNotIn("test-token", repr(notifier))

    def test_error_does_not_expose_token(self) -> None:
        session = FakeSession(
            FakeResponse(
                status_code=401,
                payload={
                    "ok": False,
                    "description": "Unauthorized",
                },
            )
        )
        notifier = TelegramNotifier(
            bot_token="123456:very-secret-token",
            chat_id="-100123",
            session=session,
        )

        with self.assertRaises(TelegramError) as raised:
            notifier.send_text("test")

        self.assertNotIn("very-secret-token", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
