from __future__ import annotations

import argparse
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from cbr_trading.resolution_hosted import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.simulations.staging_earnings_shadow import (
    _build_fixture,
    _staging_guard_error,
)


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "confirm": "STAGING_SHADOW",
        "eps": Decimal("1.25"),
        "run_id": "unit-smoke-001",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _settings(**overrides: object) -> HostedResolutionSettings:
    values = {
        "mode": HostedResolutionMode.SHADOW,
        "database_url": (
            "postgresql://codexpoly_app:unused@postgres/codexpoly"
        ),
        "database_target": "server_int",
        "database_source": "DATABASE_APP_PASSWORD",
    }
    values.update(overrides)
    return HostedResolutionSettings(**values)


class StagingEarningsShadowSmokeTests(unittest.TestCase):
    def test_guard_accepts_only_internal_shadow_staging(self) -> None:
        error = _staging_guard_error(
            args=_args(),
            settings=_settings(),
            environ={
                "CODEXPOLY_ENVIRONMENT": "staging",
                "CBR_LIVE_TRADING_ENABLED": "0",
            },
        )

        self.assertIsNone(error)

    def test_guard_rejects_non_staging_or_live_configuration(self) -> None:
        self.assertIsNotNone(
            _staging_guard_error(
                args=_args(),
                settings=_settings(),
                environ={"CODEXPOLY_ENVIRONMENT": "production"},
            )
        )
        self.assertIsNotNone(
            _staging_guard_error(
                args=_args(),
                settings=_settings(mode=HostedResolutionMode.LIVE),
                environ={"CODEXPOLY_ENVIRONMENT": "staging"},
            )
        )
        self.assertIsNotNone(
            _staging_guard_error(
                args=_args(),
                settings=_settings(
                    database_url=(
                        "postgresql://codexpoly_app:unused@"
                        "production-db/codexpoly"
                    )
                ),
                environ={"CODEXPOLY_ENVIRONMENT": "staging"},
            )
        )

    def test_fixture_is_isolated_non_submitting_configuration(self) -> None:
        fixture = _build_fixture(
            run_id="unit-smoke-001",
            now=datetime(2026, 7, 25, tzinfo=timezone.utc),
            eps=Decimal("1.25"),
        )

        self.assertTrue(
            fixture.rule.rule_key.startswith("staging-smoke-")
        )
        self.assertTrue(fixture.profile.metadata["staging_smoke"])
        self.assertEqual(fixture.profile.account_name, "abccbaq")
        self.assertEqual(
            fixture.profile.yes_desired_price,
            Decimal("0.999"),
        )
        self.assertEqual(fixture.profile.quantity, Decimal("50"))
        self.assertTrue(fixture.fact.attributes["parser_bypassed"])
        self.assertGreater(
            fixture.profile.expires_at,
            fixture.profile.prepare_from,
        )


if __name__ == "__main__":
    unittest.main()
