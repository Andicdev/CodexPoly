from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "009_schedule_july_28_auto_preflight.sql"
)
_BASE_COMPOSE = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "workers"
    / "compose.production.yml"
)
_TRADING_COMPOSE = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "workers"
    / "compose.production.trading.yml"
)


class LightsailProfileLifecycleTests(unittest.TestCase):
    def test_seed_schedules_exact_batch_without_enabling_profiles(
        self,
    ) -> None:
        text = _SEED.read_text(encoding="utf-8")

        self.assertEqual(
            text.count("('earnings-"),
            15,
        )
        self.assertIn("'AUTO_PREFLIGHT'", text)
        self.assertNotIn("SET status = 'ENABLED'", text)
        self.assertIn("expected 15 AUTO_PREFLIGHT schedules", text)

    def test_base_scheduler_has_no_trading_secrets_and_auto_live_off(
        self,
    ) -> None:
        text = _BASE_COMPOSE.read_text(encoding="utf-8")
        service = text.split("  profile-scheduler-worker:", 1)[1]
        service = service.split("  resolution-worker:", 1)[0]

        self.assertIn(
            'PROFILE_SCHEDULER_AUTO_LIVE_ENABLED: "0"',
            service,
        )
        self.assertNotIn("ACCOUNTS_MASTER_KEY", service)
        self.assertNotIn("TRADING_ACCOUNT_PRIVATE_KEY", service)

    def test_readiness_worker_is_non_submitting_trading_overlay(
        self,
    ) -> None:
        text = _TRADING_COMPOSE.read_text(encoding="utf-8")
        service = text.split("  profile-readiness-worker:", 1)[1]
        service = service.split("\nsecrets:", 1)[0]

        self.assertIn(
            "cbr_trading.profile_lifecycle.readiness_main",
            service,
        )
        self.assertIn('CBR_LIVE_TRADING_ENABLED: "0"', service)
        self.assertIn("ACCOUNTS_MASTER_KEY_FILE", service)
        self.assertIn(
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED_FILE",
            service,
        )


if __name__ == "__main__":
    unittest.main()
