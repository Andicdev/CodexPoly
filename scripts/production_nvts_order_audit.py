from __future__ import annotations

import json
import sys
from typing import Any

from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionSettings,
)
from cbr_trading.secret_guard import redact_sensitive_text


_SCOPE_ID = "earnings:NVTS:2026Q2"
_PROFILE_KEY = "earnings-nvts-2026q2"


def main() -> int:
    engine: Any | None = None
    gateway: PolymarketSupervisionOrderGateway | None = None
    try:
        from sqlalchemy import create_engine, text

        hosted = HostedResolutionSettings.from_env()
        safety = LiveSafetySettings.from_env()
        engine = create_engine(
            hosted.database_url,
            pool_pre_ping=True,
            hide_parameters=True,
        )
        with engine.connect() as connection:
            event = connection.execute(
                text(
                    """
                    SELECT
                        event.provider,
                        event.status AS event_status,
                        event.source_url,
                        fact.value,
                        fact.status AS fact_status
                    FROM earnings_source_events AS event
                    JOIN earnings_fact_candidates AS fact
                      ON fact.source_event_id = event.id
                    WHERE event.scope_id = :scope_id
                    ORDER BY fact.id DESC
                    LIMIT 1
                    """
                ),
                {"scope_id": _SCOPE_ID},
            ).mappings().one()
            claims = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                            outcome,
                            desired_price,
                            effective_price,
                            quantity,
                            status,
                            result ->> 'attempted' AS attempted,
                            result ->> 'accepted' AS accepted,
                            result ->> 'status' AS result_status,
                            result ->> 'reason' AS reason,
                            result -> 'order_ids' ->> 0 AS order_id
                        FROM resolution_execution_claims
                        WHERE scope_id = :scope_id
                        ORDER BY id
                        """
                    ),
                    {"scope_id": _SCOPE_ID},
                ).mappings()
            )
            group = connection.execute(
                text(
                    """
                    SELECT
                        groups.status AS group_status,
                        groups.outcome,
                        groups.desired_price,
                        groups.quantity,
                        groups.reprice_count,
                        groups.last_error,
                        tracked.status AS tracked_status,
                        tracked.effective_price,
                        tracked.quantity AS tracked_quantity
                    FROM resolution_order_groups AS groups
                    JOIN resolution_order_group_orders AS tracked
                      ON tracked.order_group_id = groups.order_group_id
                    WHERE groups.account_name = 'abccbaq'
                      AND groups.condition_id = (
                          SELECT condition_id
                          FROM resolution_execution_profiles
                          WHERE profile_key = :profile_key
                      )
                    ORDER BY tracked.id DESC
                    LIMIT 1
                    """
                ),
                {"profile_key": _PROFILE_KEY},
            ).mappings().one()
            supervision_events = tuple(
                connection.execute(
                text(
                    """
                    SELECT
                        events.event_type,
                        events.status,
                        events.old_tick,
                        events.new_tick,
                        events.error
                    FROM resolution_supervision_events AS events
                    JOIN resolution_order_groups AS groups
                      ON groups.order_group_id = events.order_group_id
                    WHERE groups.account_name = 'abccbaq'
                      AND groups.condition_id = (
                          SELECT condition_id
                          FROM resolution_execution_profiles
                          WHERE profile_key = :profile_key
                      )
                    ORDER BY events.created_at, events.event_id
                    """
                ),
                {"profile_key": _PROFILE_KEY},
                ).mappings()
            )
            observations = tuple(
                connection.execute(
                    text(
                        """
                        SELECT
                            observations.phase,
                            observations.remote_state,
                            observations.remote_status,
                            observations.limit_price,
                            observations.original_quantity,
                            observations.matched_quantity,
                            observations.remaining_quantity
                        FROM resolution_order_observations AS observations
                        JOIN resolution_order_groups AS groups
                          ON groups.order_group_id =
                             observations.order_group_id
                        WHERE groups.account_name = 'abccbaq'
                          AND groups.condition_id = (
                              SELECT condition_id
                              FROM resolution_execution_profiles
                              WHERE profile_key = :profile_key
                          )
                        ORDER BY
                            observations.created_at,
                            observations.order_id,
                            observations.phase
                        """
                    ),
                    {"profile_key": _PROFILE_KEY},
                ).mappings()
            )
            lifecycle = connection.execute(
                text(
                    """
                    SELECT
                        profile.status AS profile_status,
                        schedule.state AS schedule_state
                    FROM resolution_execution_profiles AS profile
                    JOIN resolution_profile_schedules AS schedule
                      ON schedule.profile_key = profile.profile_key
                    WHERE profile.profile_key = :profile_key
                    """
                ),
                {"profile_key": _PROFILE_KEY},
            ).mappings().one()

        executed = tuple(
            claim for claim in claims if claim["status"] == "EXECUTED"
        )
        if len(claims) != 2 or len(executed) != 1:
            raise RuntimeError("nvts_execution_claim_set_mismatch")
        order_id = str(executed[0].get("order_id") or "").strip()
        if not order_id:
            raise RuntimeError("nvts_executed_order_missing")

        gateway = PolymarketSupervisionOrderGateway(
            database_url=hosted.database_url or "",
            safety=safety,
        )
        inspection = gateway.inspect_orders(
            account_name="abccbaq",
            order_ids=(order_id,),
        )
        snapshots = tuple(inspection.snapshots)
        if inspection.failed_order_ids or len(snapshots) != 1:
            raise RuntimeError("nvts_remote_order_inspection_failed")
        snapshot = snapshots[0]

        payload = {
            "ok": (
                str(event["provider"]) == "sec"
                and str(event["value"]) == "-0.0400000000"
                and str(executed[0]["outcome"]) == "NO"
                and str(executed[0]["accepted"]).casefold() == "true"
                and str(executed[0]["result_status"]) == "SUBMITTED"
            ),
            "source": {
                "provider": str(event["provider"]),
                "event_status": str(event["event_status"]),
                "fact_status": str(event["fact_status"]),
                "value": str(event["value"]),
                "url": str(event["source_url"]),
            },
            "decision": {
                "outcome": str(executed[0]["outcome"]),
                "desired_price": str(executed[0]["desired_price"]),
                "effective_price": str(executed[0]["effective_price"]),
                "quantity": str(executed[0]["quantity"]),
                "claim_status": str(executed[0]["status"]),
                "result_status": str(executed[0]["result_status"]),
            },
            "supervision": {
                "group_status": str(group["group_status"]),
                "tracked_status": str(group["tracked_status"]),
                "tracked_effective_price": str(
                    group["effective_price"]
                ),
                "tracked_quantity": str(group["tracked_quantity"]),
                "reprice_count": int(group["reprice_count"]),
                "last_error": _safe_text(group["last_error"]),
                "events": [
                    {
                        "event_type": str(item["event_type"]),
                        "event_status": str(item["status"]),
                        "old_tick": _string_or_none(item["old_tick"]),
                        "new_tick": _string_or_none(item["new_tick"]),
                        "error": _safe_text(item["error"]),
                    }
                    for item in supervision_events
                ],
                "observations": [
                    {
                        "phase": str(item["phase"]),
                        "remote_state": str(item["remote_state"]),
                        "remote_status": str(item["remote_status"]),
                        "limit_price": _string_or_none(
                            item["limit_price"]
                        ),
                        "original_quantity": _string_or_none(
                            item["original_quantity"]
                        ),
                        "matched_quantity": _string_or_none(
                            item["matched_quantity"]
                        ),
                        "remaining_quantity": _string_or_none(
                            item["remaining_quantity"]
                        ),
                    }
                    for item in observations
                ],
            },
            "remote_order": {
                "state": snapshot.state.value,
                "original_quantity": _string_or_none(
                    snapshot.original_quantity
                ),
                "matched_quantity": _string_or_none(
                    snapshot.matched_quantity
                ),
                "remaining_quantity": _string_or_none(
                    snapshot.remaining_quantity
                ),
            },
            "lifecycle": {
                "profile_status": str(lifecycle["profile_status"]),
                "schedule_state": str(lifecycle["schedule_state"]),
            },
        }
        print(
            json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0 if payload["ok"] else 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_code": type(exc).__name__,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if gateway is not None:
            try:
                gateway.close()
            except Exception:
                pass
        if engine is not None:
            engine.dispose()


def _string_or_none(value: object) -> str | None:
    return None if value is None else str(value)


def _safe_text(value: object) -> str | None:
    if value is None:
        return None
    return redact_sensitive_text(str(value), max_length=500)


if __name__ == "__main__":
    raise SystemExit(main())
