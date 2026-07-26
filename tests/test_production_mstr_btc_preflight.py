from __future__ import annotations

import argparse
import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.execution import PolymarketPreflightDetail
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.orchestration import ResolutionExecutionProfile
from cbr_trading.resolution_hosted import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.simulations.production_mstr_btc_preflight import (
    _CHECKED_IN_EXPIRES_AT,
    _expected_profiles,
    _production_guard_error,
    _success_payload,
)
from cbr_trading.sources import MSTR_BTC_SOURCE_NAME


_NOW = datetime(2026, 7, 26, 20, tzinfo=timezone.utc)


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "confirm": "PRODUCTION_MSTR_AUTHENTICATED_PREFLIGHT",
        "profile_key": ["mstr-jul21-27-purchase-any"],
        "all_profiles": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _settings(**overrides: object) -> HostedResolutionSettings:
    values = {
        "mode": HostedResolutionMode.PREFLIGHT,
        "database_url": (
            "postgresql://codexpoly_app:unused@postgres/codexpoly"
        ),
        "database_target": "server_int",
        "database_source": "DATABASE_APP_PASSWORD",
        "supervision_enabled": False,
    }
    values.update(overrides)
    return HostedResolutionSettings(**values)


def _safety(**overrides: object) -> LiveSafetySettings:
    values = {
        "trading_enabled": False,
        "post_only": False,
        "allowed_account": "abccbaq",
        "max_order_quantity": Decimal("50"),
        "max_notional": Decimal("50"),
        "max_total_notional": Decimal("1000"),
        "accounts_master_key": "present",
    }
    values.update(overrides)
    return LiveSafetySettings(**values)


def _profile(
    profile_key: str = "mstr-jul21-27-purchase-any",
) -> ResolutionExecutionProfile:
    expected = _expected_profiles()[profile_key]
    return ResolutionExecutionProfile(
        profile_key=profile_key,
        scope_id=expected.scope_id,
        source_name=MSTR_BTC_SOURCE_NAME,
        source_reference=expected.source_reference,
        account_name="abccbaq",
        condition_id=expected.condition_id,
        yes_desired_price=Decimal("0.999"),
        no_desired_price=Decimal("0.999"),
        quantity=Decimal("50"),
        prepare_from=_NOW - timedelta(minutes=5),
        expires_at=_CHECKED_IN_EXPIRES_AT,
        lifecycle_policy=RepriceOnTickChange(
            old_tick=Decimal("0.01"),
            new_tick=Decimal("0.001"),
            max_reprices=1,
        ),
        metadata={"rule_key": expected.rule_key},
    )


def _environment() -> dict[str, str]:
    return {
        "CODEXPOLY_ENVIRONMENT": "production",
        "TRADING_ACCOUNT_SOURCE": "database_metadata_secret",
        "TRADING_ACCOUNT_NAME": "abccbaq",
    }


def _detail(outcome: str) -> PolymarketPreflightDetail:
    return PolymarketPreflightDetail(
        template_id=f"mstr-template:{outcome}",
        account_name="abccbaq",
        condition_id="0x" + "1" * 64,
        outcome=outcome,
        token_id=f"sensitive-output-token-{outcome}",
        quantity=Decimal("50"),
        desired_price=Decimal("0.999"),
        effective_price=Decimal("0.99"),
        tick_size=Decimal("0.01"),
        minimum_order_size=Decimal("5"),
        best_bid=Decimal("0.42"),
        best_ask=Decimal("0.43"),
        order_presigned=True,
        collateral_sufficient=True,
    )


class ProductionMstrBtcPreflightTests(unittest.TestCase):
    def test_guard_accepts_one_exact_internal_production_profile(
        self,
    ) -> None:
        error = _production_guard_error(
            args=_args(),
            settings=_settings(),
            safety=_safety(),
            profiles=(_profile(),),
            environ=_environment(),
            now=_NOW,
        )

        self.assertIsNone(error)

    def test_guard_accepts_all_three_profiles_with_cap_1000(
        self,
    ) -> None:
        profiles = tuple(
            _profile(profile_key)
            for profile_key in _expected_profiles()
        )

        error = _production_guard_error(
            args=_args(profile_key=None, all_profiles=True),
            settings=_settings(),
            safety=_safety(),
            profiles=profiles,
            environ=_environment(),
            now=_NOW,
        )

        self.assertIsNone(error)

    def test_guard_rejects_live_mode_profile_set_and_cap_drift(
        self,
    ) -> None:
        self.assertIsNotNone(
            _production_guard_error(
                args=_args(),
                settings=_settings(mode=HostedResolutionMode.LIVE),
                safety=_safety(),
                profiles=(_profile(),),
                environ=_environment(),
                now=_NOW,
            )
        )
        self.assertIsNotNone(
            _production_guard_error(
                args=_args(),
                settings=_settings(),
                safety=_safety(),
                profiles=(_profile(), _profile()),
                environ=_environment(),
                now=_NOW,
            )
        )
        self.assertIsNotNone(
            _production_guard_error(
                args=_args(),
                settings=_settings(),
                safety=_safety(max_total_notional=Decimal("150")),
                profiles=(_profile(),),
                environ=_environment(),
                now=_NOW,
            )
        )

    def test_guard_rejects_live_activation_and_profile_drift(
        self,
    ) -> None:
        self.assertIsNotNone(
            _production_guard_error(
                args=_args(),
                settings=_settings(),
                safety=_safety(trading_enabled=True),
                profiles=(_profile(),),
                environ=_environment(),
                now=_NOW,
            )
        )
        drifted = ResolutionExecutionProfile(
            **{
                **vars(_profile()),
                "quantity": Decimal("51"),
            }
        )
        self.assertIsNotNone(
            _production_guard_error(
                args=_args(),
                settings=_settings(),
                safety=_safety(),
                profiles=(drifted,),
                environ=_environment(),
                now=_NOW,
            )
        )

    def test_payload_proves_non_submission_without_token_output(
        self,
    ) -> None:
        executor = SimpleNamespace(
            details=(_detail("YES"), _detail("NO")),
            maximum_notional=Decimal("99.00"),
        )
        preparation = SimpleNamespace(
            profile_key="mstr-jul21-27-purchase-any",
            ready=True,
            template_count=2,
        )

        payload = _success_payload(
            profiles=(_profile(),),
            preparations=(preparation,),
            executors={
                "mstr-jul21-27-purchase-any": executor,
            },
            safety=_safety(),
            database_target="server_int",
        )
        rendered = json.dumps(payload)

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["order_submitted"])
        self.assertFalse(payload["source_fact_polled"])
        self.assertFalse(payload["executor_execute_called"])
        self.assertEqual(len(payload["market"]), 2)
        self.assertEqual(
            payload["preparation"]["maximum_selected_notional"],
            "49.950",
        )
        self.assertNotIn("sensitive-output-token", rendered)
        self.assertNotIn("token_id", rendered)
        self.assertNotIn("signature", rendered)

    def test_combined_payload_covers_six_alternatives_under_cap(
        self,
    ) -> None:
        profiles = tuple(
            _profile(profile_key)
            for profile_key in _expected_profiles()
        )
        executors = {
            profile.profile_key: SimpleNamespace(
                details=(_detail("YES"), _detail("NO")),
                maximum_notional=Decimal("99.00"),
            )
            for profile in profiles
        }
        preparations = tuple(
            SimpleNamespace(
                profile_key=profile.profile_key,
                ready=True,
                template_count=2,
            )
            for profile in profiles
        )

        payload = _success_payload(
            profiles=profiles,
            preparations=preparations,
            executors=executors,
            safety=_safety(),
            database_target="server_int",
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["enabled_profile_count"], 3)
        self.assertEqual(len(payload["market"]), 6)
        self.assertEqual(
            payload["preparation"]["maximum_prepared_notional"],
            "297.00",
        )
        self.assertEqual(
            payload["preparation"]["maximum_selected_notional"],
            "149.850",
        )


if __name__ == "__main__":
    unittest.main()
