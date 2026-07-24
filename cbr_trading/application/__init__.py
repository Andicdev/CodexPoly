"""Application services that compose source-neutral trading contracts."""

from cbr_trading.application.coordinator import (
    CoordinationOutcome,
    CoordinationPreparation,
    CoordinationStatus,
    CoordinatorLifecycleError,
    CoordinatorState,
    ResolutionTradingCoordinator,
)
from cbr_trading.application.cbr_compat import (
    CbrPollModeDiscoveryClient,
    pipeline_outcome_from_coordination,
)

__all__ = [
    "CbrPollModeDiscoveryClient",
    "CoordinationOutcome",
    "CoordinationPreparation",
    "CoordinationStatus",
    "CoordinatorLifecycleError",
    "CoordinatorState",
    "ResolutionTradingCoordinator",
    "pipeline_outcome_from_coordination",
]
