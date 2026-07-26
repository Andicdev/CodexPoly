from __future__ import annotations

import argparse
import unittest
from datetime import datetime, timezone

from cbr_trading.mstr_btc import (
    MstrBtcHoldingsBaseline,
    MstrBtcProvider,
)
from cbr_trading.resolution_hosted import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.simulations.staging_mstr_btc_shadow import (
    _build_fixture,
    _staging_guard_error,
)


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "confirm": "STAGING_MSTR_SHADOW",
        "run_id": "unit-mstr-smoke-001",
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


def _baseline() -> MstrBtcHoldingsBaseline:
    return MstrBtcHoldingsBaseline(
        state_id="42",
        holdings_btc=843_775,
        as_of=datetime(2026, 7, 20, tzinfo=timezone.utc),
        provider=MstrBtcProvider.STRATEGY_LEDGER,
        provider_event_id="baseline-row",
        source_url="https://www.strategy.com/purchases",
    )


class StagingMstrBtcShadowSmokeTests(unittest.TestCase):
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

    def test_guard_rejects_non_staging_live_or_external_database(
        self,
    ) -> None:
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
                    ),
                ),
                environ={"CODEXPOLY_ENVIRONMENT": "staging"},
            )
        )

    def test_fixture_uses_three_synthetic_scopes_and_default_template(
        self,
    ) -> None:
        fixture = _build_fixture(
            run_id="unit-mstr-smoke-001",
            now=datetime(2026, 7, 27, 12, tzinfo=timezone.utc),
            baseline=_baseline(),
        )

        self.assertTrue(
            fixture.weekly_scope_id.startswith(
                "staging-mstr-smoke-"
            )
        )
        self.assertEqual(len(fixture.rules), 3)
        self.assertEqual(len(fixture.bindings), 3)
        self.assertEqual(len(fixture.profiles), 3)
        self.assertEqual(
            {rule.signal_id for rule in fixture.rules},
            {binding.signal_id for binding in fixture.bindings},
        )
        self.assertEqual(
            {profile.scope_id for profile in fixture.profiles},
            {rule.signal_id for rule in fixture.rules},
        )
        self.assertTrue(fixture.fact.attributes["parser_bypassed"])
        self.assertEqual(fixture.fact.acquired_btc, 1_500)
        self.assertEqual(fixture.fact.baseline_state_id, "42")
        for profile in fixture.profiles:
            self.assertEqual(profile.account_name, "abccbaq")
            self.assertEqual(str(profile.yes_desired_price), "0.999")
            self.assertEqual(str(profile.no_desired_price), "0.999")
            self.assertEqual(str(profile.quantity), "50")


if __name__ == "__main__":
    unittest.main()
