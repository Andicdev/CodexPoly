from __future__ import annotations

import unittest
import json
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
_SECRET_MANIFEST = (
    _ROOT / "deploy" / "lightsail" / "secret-manifest.json"
)
_VERIFY_SQL = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_profile_lifecycle_auto_preflight.sql"
)
_AUTO_LIVE_SEED = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "seeds"
    / "010_arm_july_28_auto_live.sql"
)
_AUTO_LIVE_VERIFY_SQL = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_profile_lifecycle_auto_live_armed.sql"
)
_LIVE_RUNTIME_VERIFY_SQL = (
    _ROOT
    / "deploy"
    / "lightsail"
    / "checks"
    / "verify_resolution_runtime_live.sql"
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

    def test_base_scheduler_has_no_trading_secrets_and_defaults_live_off(
        self,
    ) -> None:
        text = _BASE_COMPOSE.read_text(encoding="utf-8")
        service = text.split("  profile-scheduler-worker:", 1)[1]
        service = service.split("  resolution-worker:", 1)[0]

        self.assertIn(
            "PROFILE_SCHEDULER_AUTO_LIVE_ENABLED: "
            '"${PROFILE_SCHEDULER_AUTO_LIVE_ENABLED:-0}"',
            service,
        )
        self.assertIn(
            "PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL: "
            '"${PROFILE_SCHEDULER_MAX_TOTAL_NOTIONAL:-}"',
            service,
        )
        self.assertIn(
            'PROFILE_SCHEDULER_LIVE_HEARTBEAT_STALE_SEC: "15"',
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

    def test_secret_manifest_keeps_scheduler_db_only(self) -> None:
        manifest = json.loads(
            _SECRET_MANIFEST.read_text(encoding="utf-8")
        )
        services = manifest["environments"]["production"]

        self.assertEqual(
            services["profile-scheduler-worker"],
            ["DATABASE_APP_PASSWORD"],
        )
        self.assertEqual(
            services["profile-readiness-worker"],
            [
                "DATABASE_APP_PASSWORD",
                "ACCOUNTS_MASTER_KEY",
                "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED",
            ],
        )

    def test_production_check_fails_closed_on_live_or_enabled_state(
        self,
    ) -> None:
        text = _VERIFY_SQL.read_text(encoding="utf-8")

        self.assertIn("expected 15 pending AUTO_PREFLIGHT", text)
        self.assertIn("status <> 'DISABLED'", text)
        self.assertIn("automation_mode = 'AUTO_LIVE'", text)
        self.assertIn("state = 'ACTIVE'", text)

    def test_auto_live_seed_arms_exact_reviewed_batch_only(self) -> None:
        text = _AUTO_LIVE_SEED.read_text(encoding="utf-8")

        self.assertEqual(text.count("'earnings-"), 45)
        self.assertIn("expected 15 pending AUTO_PREFLIGHT", text)
        self.assertIn("automation_mode = 'AUTO_LIVE'", text)
        self.assertIn("state = 'PENDING'", text)
        self.assertNotIn("SET status = 'ENABLED'", text)
        self.assertIn("reviewed_notional > 1000", text)

    def test_auto_live_check_requires_heartbeat_schema_and_cap(
        self,
    ) -> None:
        text = _AUTO_LIVE_VERIFY_SQL.read_text(encoding="utf-8")

        self.assertIn("resolution_runtime_heartbeats", text)
        self.assertIn("expected 15 pending AUTO_LIVE", text)
        self.assertIn("status <> 'DISABLED'", text)
        self.assertIn("reviewed_notional > 1000", text)

    def test_live_runtime_check_requires_fresh_trading_heartbeat(
        self,
    ) -> None:
        text = _LIVE_RUNTIME_VERIFY_SQL.read_text(encoding="utf-8")

        self.assertIn("runtime_key = 'hosted-resolution'", text)
        self.assertIn("mode = 'live'", text)
        self.assertIn("supervision_enabled", text)
        self.assertIn("trading_enabled", text)
        self.assertIn("interval '15 seconds'", text)


if __name__ == "__main__":
    unittest.main()
