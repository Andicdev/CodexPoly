from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.orchestration import ResolutionExecutionProfile
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
)


def validate_profile_batch_notional(
    profiles: Sequence[ResolutionExecutionProfile],
    *,
    mode: HostedResolutionMode,
    safety: LiveSafetySettings,
) -> Decimal:
    """Enforce one aggregate worst-case budget across hosted profiles."""

    if mode is HostedResolutionMode.SHADOW:
        return Decimal("0")
    if safety.max_total_notional is None:
        raise ValueError(
            "aggregate notional cap is required for preflight or live mode"
        )
    maximum_selected_notional = sum(
        (
            profile.quantity
            * max(
                profile.yes_desired_price,
                profile.no_desired_price,
            )
            for profile in profiles
        ),
        start=Decimal("0"),
    )
    if maximum_selected_notional > safety.max_total_notional:
        raise ValueError(
            "enabled profile batch exceeds aggregate notional cap"
        )
    return maximum_selected_notional
