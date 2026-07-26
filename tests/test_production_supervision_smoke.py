from __future__ import annotations

import argparse
import asyncio
import unittest
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.execution import TickSizeWatch
from cbr_trading.resolution_hosted import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.simulations.production_supervision_smoke import (
    _guard_error,
    _smoke_market_channel,
    _watches_for_snapshots,
)


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "confirm": "PRODUCTION_MSTR_SUPERVISION_NO_SUBMIT",
        "duration": 1.0,
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
        "supervision_enabled": False,
    }
    values.update(overrides)
    return HostedResolutionSettings(**values)


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "CODEXPOLY_ENVIRONMENT": "production",
        "CBR_LIVE_TRADING_ENABLED": "0",
    }
    values.update(overrides)
    return values


class _Channel:
    def __init__(self, **_kwargs: object):
        self.closed = asyncio.Event()

    async def run(self) -> tuple:
        await self.closed.wait()
        return ()

    async def close(self) -> None:
        self.closed.set()


class ProductionSupervisionSmokeTests(unittest.TestCase):
    def test_guard_accepts_base_internal_production_worker(self) -> None:
        error = _guard_error(
            args=_args(),
            settings=_settings(),
            environ=_environment(),
        )

        self.assertIsNone(error)

    def test_guard_rejects_trading_or_trading_secret_mounts(self) -> None:
        self.assertIsNotNone(
            _guard_error(
                args=_args(),
                settings=_settings(),
                environ=_environment(
                    CBR_LIVE_TRADING_ENABLED="1"
                ),
            )
        )
        self.assertIsNotNone(
            _guard_error(
                args=_args(),
                settings=_settings(),
                environ=_environment(
                    ACCOUNTS_MASTER_KEY_FILE="/run/secrets/key"
                ),
            )
        )
        self.assertIsNotNone(
            _guard_error(
                args=_args(),
                settings=_settings(
                    mode=HostedResolutionMode.LIVE
                ),
                environ=_environment(),
            )
        )

    def test_builds_watches_only_for_coarse_tick_assets(self) -> None:
        snapshots = tuple(
            SimpleNamespace(
                token_id=f"asset-{index}",
                tick_size=(
                    Decimal("0.01")
                    if index < 4
                    else Decimal("0.001")
                ),
            )
            for index in range(6)
        )

        watches = _watches_for_snapshots(snapshots)

        self.assertEqual(len(watches), 4)
        self.assertTrue(
            all(
                watch.old_tick == Decimal("0.01")
                and watch.new_tick == Decimal("0.001")
                for watch in watches
            )
        )

    def test_public_channel_smoke_stays_non_submitting(self) -> None:
        result = asyncio.run(
            _smoke_market_channel(
                (
                    TickSizeWatch(
                        asset_id="asset-1",
                        old_tick=Decimal("0.01"),
                        new_tick=Decimal("0.001"),
                    ),
                ),
                duration=0.01,
                channel_factory=_Channel,
            )
        )

        self.assertTrue(result["connected"])
        self.assertEqual(result["tick_event_count"], 0)


if __name__ == "__main__":
    unittest.main()
