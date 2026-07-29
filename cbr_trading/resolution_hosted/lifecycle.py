from __future__ import annotations

import logging
from typing import Any

from cbr_trading.application import CoordinationStatus


_TERMINAL_FAILURE_REASONS = {
    CoordinationStatus.SOURCE_ERROR: "live_source_contract_failed",
    CoordinationStatus.STRATEGY_ERROR: (
        "live_strategy_evaluation_failed"
    ),
    CoordinationStatus.EXECUTION_ERROR: "live_execution_failed",
}


def complete_profile_lifecycle(
    lifecycle_store: Any | None,
    *,
    profile_key: str,
    logger: logging.Logger,
) -> bool:
    """Complete after execution without touching submitted orders."""

    if lifecycle_store is None:
        return True
    try:
        lifecycle_store.complete_active_profile(
            profile_key=profile_key,
            reason_code="resolution_execution_completed",
        )
    except Exception as exc:
        logger.warning(
            "Profile lifecycle completion deferred profile=%s "
            "error_type=%s",
            profile_key,
            type(exc).__name__,
        )
        return False
    return True


def block_terminal_profile_failure(
    lifecycle_store: Any | None,
    *,
    profile_key: str,
    status: CoordinationStatus,
    logger: logging.Logger,
) -> bool:
    if lifecycle_store is None:
        return True
    reason = _TERMINAL_FAILURE_REASONS.get(status)
    if reason is None:
        return True
    try:
        lifecycle_store.block_active_profile(
            profile_key=profile_key,
            reason_code=reason,
        )
    except Exception as exc:
        logger.warning(
            "Profile lifecycle failure block deferred profile=%s "
            "status=%s error_type=%s",
            profile_key,
            status.value,
            type(exc).__name__,
        )
        return False
    return True
