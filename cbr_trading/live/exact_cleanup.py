from __future__ import annotations

from typing import Any, Callable

from cbr_trading.execution.supervision_gateway import (
    RemoteOrderState,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.secret_guard import redact_sensitive_text


def cleanup_exact_order(
    *,
    database_url: str,
    safety: LiveSafetySettings,
    account_name: str,
    order_id: str,
    gateway_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Inspect, cancel only the supplied order ID, and confirm terminal."""

    normalized_order_id = str(order_id or "").strip()
    if not normalized_order_id:
        raise ValueError("order_id is required for exact cleanup")
    factory = (
        gateway_factory
        if gateway_factory is not None
        else PolymarketSupervisionOrderGateway
    )
    gateway = factory(
        database_url=database_url,
        safety=safety,
    )
    initial_state: RemoteOrderState | None = None
    final_state: RemoteOrderState | None = None
    cancel_requested = False
    cancel_acknowledged = False
    failure_types: list[str] = []
    terminal_states = {
        RemoteOrderState.CANCELLED,
        RemoteOrderState.FILLED,
    }
    try:
        try:
            initial = gateway.inspect_orders(
                account_name=account_name,
                order_ids=(normalized_order_id,),
            )
            initial_state = single_inspection_state(initial)
        except Exception as exc:
            failure_types.append(
                "initial inspection " + type(exc).__name__
            )

        final_state = initial_state
        if initial_state not in terminal_states:
            cancel_requested = True
            try:
                cancellation = gateway.cancel_orders(
                    account_name=account_name,
                    order_ids=(normalized_order_id,),
                )
                cancel_acknowledged = (
                    normalized_order_id
                    in cancellation.cancelled_order_ids
                )
                if not cancel_acknowledged:
                    failure_types.append(
                        "cancellation not acknowledged"
                    )
            except Exception as exc:
                failure_types.append(
                    "cancellation " + type(exc).__name__
                )

            try:
                final = gateway.inspect_orders(
                    account_name=account_name,
                    order_ids=(normalized_order_id,),
                )
                final_state = single_inspection_state(final)
                if final_state is None:
                    failure_types.append(
                        "final inspection not confirmed"
                    )
            except Exception as exc:
                final_state = None
                failure_types.append(
                    "final inspection " + type(exc).__name__
                )
    finally:
        try:
            gateway.close()
        except Exception as exc:
            failure_types.append(
                "gateway close " + type(exc).__name__
            )

    confirmed_terminal = final_state in terminal_states
    error = None
    if not confirmed_terminal:
        error = redact_sensitive_text(
            "Exact-order cleanup was not confirmed"
            + (
                ": " + "; ".join(dict.fromkeys(failure_types))
                if failure_types
                else ""
            )
        )
    return {
        "required": True,
        "attempted": True,
        "order_id": normalized_order_id,
        "cancel_requested": cancel_requested,
        "cancel_acknowledged": cancel_acknowledged,
        "initial_state": remote_state_value(initial_state),
        "final_state": remote_state_value(final_state),
        "confirmed_terminal": confirmed_terminal,
        "error": error,
    }


def single_inspection_state(
    inspection: Any,
) -> RemoteOrderState | None:
    snapshots = tuple(inspection.snapshots)
    failed = tuple(inspection.failed_order_ids)
    if failed or len(snapshots) != 1:
        return None
    state = snapshots[0].state
    return (
        state
        if isinstance(state, RemoteOrderState)
        else RemoteOrderState(str(state).upper())
    )


def remote_state_value(
    state: RemoteOrderState | None,
) -> str | None:
    return state.value if state is not None else None
