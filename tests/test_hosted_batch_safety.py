from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from cbr_trading.domain import KeepOpenPolicy
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.orchestration import ResolutionExecutionProfile
from cbr_trading.resolution_hosted.batch_safety import (
    validate_profile_batch_notional,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.resolution_hosted.mstr_btc import (
    MstrBtcHostedResolutionWorker,
)
from cbr_trading.sources import MSTR_BTC_SOURCE_NAME


_NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def _profile(suffix: str) -> ResolutionExecutionProfile:
    return ResolutionExecutionProfile(
        profile_key=f"batch-{suffix}",
        scope_id=f"batch:{suffix}",
        source_name="test_source",
        source_reference=f"https://example.com/{suffix}",
        account_name="abccbaq",
        condition_id="0x" + suffix.zfill(64),
        yes_desired_price=Decimal("0.999"),
        no_desired_price=Decimal("0.999"),
        quantity=Decimal("50"),
        prepare_from=_NOW,
        expires_at=_NOW + timedelta(hours=1),
        lifecycle_policy=KeepOpenPolicy(),
    )


def _safety(cap: str | None) -> LiveSafetySettings:
    return LiveSafetySettings(
        max_total_notional=(
            Decimal(cap) if cap is not None else None
        ),
    )


class _AuditStore:
    def ensure_ready(self) -> None:
        return None


class _ProfileStore:
    def __init__(
        self,
        profiles: tuple[ResolutionExecutionProfile, ...],
    ):
        self._profiles = profiles
        self.loaded_sources: list[str | None] = []

    def ensure_ready(self) -> None:
        return None

    def load_enabled(
        self,
        *,
        source_name: str | None = None,
    ) -> tuple[ResolutionExecutionProfile, ...]:
        self.loaded_sources.append(source_name)
        if source_name is None:
            return self._profiles
        return tuple(
            profile
            for profile in self._profiles
            if profile.source_name.casefold()
            == source_name.casefold()
        )


class HostedBatchSafetyTests(unittest.TestCase):
    def test_one_profile_uses_only_one_selected_outcome_budget(
        self,
    ) -> None:
        maximum = validate_profile_batch_notional(
            (_profile("1"),),
            mode=HostedResolutionMode.PREFLIGHT,
            safety=_safety("100"),
        )

        self.assertEqual(maximum, Decimal("49.950"))

    def test_three_profiles_exceed_the_reviewed_aggregate_cap(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "enabled profile batch exceeds aggregate notional cap",
        ):
            validate_profile_batch_notional(
                (
                    _profile("1"),
                    _profile("2"),
                    _profile("3"),
                ),
                mode=HostedResolutionMode.LIVE,
                safety=_safety("100"),
            )

    def test_preflight_requires_cap_but_shadow_does_not(
        self,
    ) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "aggregate notional cap is required",
        ):
            validate_profile_batch_notional(
                (_profile("1"),),
                mode=HostedResolutionMode.PREFLIGHT,
                safety=_safety(None),
            )

        self.assertEqual(
            validate_profile_batch_notional(
                (_profile("1"), _profile("2"), _profile("3")),
                mode=HostedResolutionMode.SHADOW,
                safety=_safety(None),
            ),
            Decimal("0"),
        )

    def test_hosted_worker_counts_enabled_profiles_from_other_sources(
        self,
    ) -> None:
        profiles = (
            _profile("1"),
            _profile("2"),
            _profile("3"),
        )
        profiles = (
            ResolutionExecutionProfile(
                **{
                    **vars(profile),
                    "source_name": (
                        MSTR_BTC_SOURCE_NAME
                        if index == 0
                        else "earnings_sec_non_gaap_eps"
                    ),
                }
            )
            for index, profile in enumerate(profiles)
        )
        profile_store = _ProfileStore(tuple(profiles))
        worker = MstrBtcHostedResolutionWorker(
            settings=HostedResolutionSettings(
                mode=HostedResolutionMode.PREFLIGHT,
                database_url="postgresql://unused",
            ),
            audit_store=_AuditStore(),
            profile_store=profile_store,
        )

        with patch(
            "cbr_trading.resolution_hosted.mstr_btc."
            "LiveSafetySettings.from_env",
            return_value=_safety("100"),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "enabled profile batch exceeds aggregate notional cap",
            ):
                worker.prepare()

        self.assertEqual(
            profile_store.loaded_sources,
            [MSTR_BTC_SOURCE_NAME, None],
        )


if __name__ == "__main__":
    unittest.main()
