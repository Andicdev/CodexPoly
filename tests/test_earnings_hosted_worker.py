from __future__ import annotations

import unittest
from dataclasses import replace

from cbr_trading.earnings.hosted_worker import (
    EarningsHostedShadowWorker,
    WorkerCycleStatus,
    _watches_from_rules,
)
from cbr_trading.earnings.parsers import checked_in_shadow_rules
from cbr_trading.earnings.parsers.navitas import (
    nvts_q2_2026_shadow_rule,
)
from cbr_trading.earnings.settings import EarningsWorkerSettings


class _Store:
    def __init__(self, rules):
        self.rules = tuple(rules)

    def load_active_rules(self):
        return self.rules


class _EmptyTransport:
    async def stream_once(self):
        if False:
            yield None


def _settings() -> EarningsWorkerSettings:
    return EarningsWorkerSettings(
        database_url="postgresql://configured",
        sec_api_key="configured",
        http_user_agent="CodexPoly test@example.com",
        heartbeat_interval=3600,
    )


class EarningsHostedWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_cycle_loads_shadow_watch(self) -> None:
        captured = []

        def builder(watches):
            captured.extend(watches)
            return _EmptyTransport()

        worker = EarningsHostedShadowWorker(
            settings=_settings(),
            store=_Store([nvts_q2_2026_shadow_rule()]),
            transport_builder=builder,
        )

        result = await worker.run_connection_cycle()

        self.assertEqual(result.status, WorkerCycleStatus.STREAM_CLOSED)
        self.assertEqual(result.watch_count, 1)
        self.assertEqual(captured[0].scope_id, "earnings:NVTS:2026Q2")

    async def test_no_rules_does_not_open_websocket(self) -> None:
        def forbidden_builder(_watches):
            raise AssertionError("transport must not be created")

        worker = EarningsHostedShadowWorker(
            settings=_settings(),
            store=_Store([]),
            transport_builder=forbidden_builder,
        )

        result = await worker.run_connection_cycle()

        self.assertEqual(result.status, WorkerCycleStatus.NO_RULES)
        self.assertEqual(result.watch_count, 0)

    async def test_connection_cycle_watches_all_checked_in_issuers(
        self,
    ) -> None:
        captured = []

        def builder(watches):
            captured.extend(watches)
            return _EmptyTransport()

        worker = EarningsHostedShadowWorker(
            settings=_settings(),
            store=_Store(checked_in_shadow_rules()),
            transport_builder=builder,
        )

        result = await worker.run_connection_cycle()

        self.assertEqual(result.watch_count, 3)
        self.assertEqual(
            {watch.ticker for watch in captured},
            {"BBBY", "NVTS", "WWD"},
        )

    def test_multiple_active_scopes_for_same_cik_are_rejected(self) -> None:
        first = nvts_q2_2026_shadow_rule()
        second = replace(
            first,
            rule_key="nvts-2026q3",
            scope_id="earnings:NVTS:2026Q3",
            fiscal_quarter=3,
        )

        with self.assertRaisesRegex(
            ValueError,
            "multiple active earnings scopes",
        ):
            _watches_from_rules((first, second))


class EarningsWorkerSettingsTests(unittest.TestCase):
    def test_secrets_are_required_but_hidden_from_repr(self) -> None:
        database_url = "postgresql://user:password@example/app"
        sec_key = "sec-credential"
        settings = EarningsWorkerSettings.from_env(
            {
                "CBR_DATABASE_URL": database_url,
                "SEC_API_KEY": sec_key,
                "EARNINGS_WORKER_MODE": "shadow",
                "EARNINGS_HTTP_USER_AGENT": (
                    "CodexPoly test@example.com"
                ),
            }
        )

        rendered = repr(settings)
        self.assertNotIn(database_url, rendered)
        self.assertNotIn(sec_key, rendered)
        self.assertEqual(settings.mode, "shadow")

    def test_non_shadow_mode_and_missing_key_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "remain 'shadow'"):
            EarningsWorkerSettings.from_env(
                {
                    "CBR_DATABASE_URL": "postgresql://configured",
                    "SEC_API_KEY": "configured",
                    "EARNINGS_WORKER_MODE": "live",
                    "EARNINGS_HTTP_USER_AGENT": (
                        "CodexPoly test@example.com"
                    ),
                }
            )
        with self.assertRaisesRegex(ValueError, "SEC_API_KEY"):
            EarningsWorkerSettings.from_env(
                {
                    "CBR_DATABASE_URL": "postgresql://configured",
                    "EARNINGS_HTTP_USER_AGENT": (
                        "CodexPoly test@example.com"
                    ),
                }
            )

    def test_missing_sec_user_agent_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "EARNINGS_HTTP_USER_AGENT",
        ):
            EarningsWorkerSettings.from_env(
                {
                    "CBR_DATABASE_URL": "postgresql://configured",
                    "SEC_API_KEY": "configured",
                }
            )

    def test_accepts_legacy_sec_stream_key_name(self) -> None:
        settings = EarningsWorkerSettings.from_env(
            {
                "CBR_DATABASE_URL": "postgresql://configured",
                "SEC_API_STREAM_KEY": "configured",
                "EARNINGS_HTTP_USER_AGENT": (
                    "CodexPoly test@example.com"
                ),
            }
        )

        self.assertIsNotNone(settings.sec_api_key)


if __name__ == "__main__":
    unittest.main()
