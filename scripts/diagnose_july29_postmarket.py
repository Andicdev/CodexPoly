from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, text

from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.resolution_hosted.settings import HostedResolutionSettings
from cbr_trading.secret_guard import redact_sensitive_text


_PROFILE_KEYS = (
    "earnings-meta-2026q2",
    "earnings-qcom-2026q3",
    "earnings-way-2026q2",
    "earnings-sbux-2026q3",
    "earnings-msft-2026q4",
    "earnings-hood-2026q2",
    "earnings-ea-2027q1",
)

_SUMMARY_SQL = """
SELECT
    profile.profile_key,
    profile.metadata ->> 'ticker' AS ticker,
    schedule.state AS schedule_state,
    schedule.last_error_code,
    profile.status AS profile_status,
    fact.provider AS source_provider,
    fact.value AS resolved_value,
    fact.published_at AS source_published_at,
    fact.detected_at AS source_detected_at,
    claim.status AS claim_status,
    claim.outcome AS selected_outcome,
    claim.desired_price,
    claim.effective_price,
    claim.quantity,
    claim.created_at AS claim_created_at,
    claim.completed_at AS exchange_completed_at,
    order_group.status AS order_group_status,
    order_group.reprice_count,
    order_group.created_at AS order_group_created_at,
    order_group.updated_at AS order_group_updated_at,
    observation.limit_price AS last_observed_price,
    observation.matched_quantity,
    observation.remaining_quantity,
    observation.remote_state,
    observation.remote_status,
    observation.observed_at AS last_order_observed_at
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
LEFT JOIN LATERAL (
    SELECT candidate.*
    FROM earnings_fact_candidates AS candidate
    WHERE candidate.scope_id = profile.scope_id
      AND candidate.status IN ('VALIDATED', 'EMITTED')
    ORDER BY candidate.detected_at, candidate.id
    LIMIT 1
) AS fact ON true
LEFT JOIN LATERAL (
    SELECT execution.*
    FROM resolution_execution_claims AS execution
    WHERE execution.scope_id = profile.scope_id
      AND execution.status <> 'EXPIRED'
    ORDER BY execution.created_at, execution.id
    LIMIT 1
) AS claim ON true
LEFT JOIN LATERAL (
    SELECT candidate_group.*
    FROM resolution_order_groups AS candidate_group
    WHERE candidate_group.condition_id = profile.condition_id
      AND candidate_group.created_at >=
          schedule.activate_at - interval '15 minutes'
    ORDER BY candidate_group.created_at DESC
    LIMIT 1
) AS order_group ON true
LEFT JOIN LATERAL (
    SELECT item.*
    FROM resolution_order_observations AS item
    WHERE item.order_group_id = order_group.order_group_id
    ORDER BY item.observed_at DESC, item.created_at DESC
    LIMIT 1
) AS observation ON true
WHERE profile.profile_key = ANY(CAST(:profile_keys AS text[]))
ORDER BY profile.profile_key
""".strip()

_SOURCE_SQL = """
SELECT
    profile.profile_key,
    profile.metadata ->> 'ticker' AS ticker,
    event.provider,
    telemetry.source_transport,
    event.status,
    event.source_url,
    event.filing_url,
    event.filed_at,
    event.received_at,
    telemetry.transport_observed_at,
    telemetry.document_fetch_started_at,
    telemetry.document_fetch_completed_at,
    telemetry.document_fetch_route,
    telemetry.parse_completed_at,
    telemetry.fact_persisted_at,
    fact.value,
    fact.detected_at
FROM resolution_execution_profiles AS profile
JOIN earnings_source_events AS event
  ON event.scope_id = profile.scope_id
LEFT JOIN earnings_source_processing_telemetry AS telemetry
  ON telemetry.source_event_id = event.id
LEFT JOIN earnings_fact_candidates AS fact
  ON fact.source_event_id = event.id
WHERE profile.profile_key = ANY(CAST(:profile_keys AS text[]))
  AND event.received_at >= TIMESTAMPTZ '2026-07-29 19:30:00+00'
ORDER BY event.received_at, event.id
""".strip()

_ORDER_SQL = """
SELECT
    profile.profile_key,
    profile.metadata ->> 'ticker' AS ticker,
    tracked.generation,
    tracked.status,
    tracked.effective_price,
    tracked.quantity,
    tracked.opened_at,
    tracked.closed_at
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
JOIN resolution_order_groups AS order_group
  ON order_group.condition_id = profile.condition_id
JOIN resolution_order_group_orders AS tracked
  ON tracked.order_group_id = order_group.order_group_id
WHERE profile.profile_key = ANY(CAST(:profile_keys AS text[]))
  AND order_group.created_at >=
      schedule.activate_at - interval '15 minutes'
ORDER BY profile.profile_key, tracked.generation, tracked.opened_at
""".strip()

_JOURNAL_SQL = """
SELECT
    profile_key,
    source_provider,
    selected_outcome,
    execution_status,
    latency_status,
    overall_result,
    desired_price,
    effective_price,
    quantity,
    matched_quantity,
    source_published_at,
    source_detected_at,
    claim_created_at,
    exchange_completed_at,
    first_order_observed_at,
    last_order_observed_at,
    source_latency_ms,
    decision_latency_ms,
    exchange_latency_ms,
    error_stage,
    error_code,
    classification_reason
FROM resolution_run_journal
WHERE profile_key = ANY(CAST(:profile_keys AS text[]))
ORDER BY profile_key
""".strip()

_REMOTE_ORDER_SQL = """
SELECT
    profile.profile_key,
    profile.metadata ->> 'ticker' AS ticker,
    order_group.account_name,
    tracked.order_id
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
JOIN resolution_order_groups AS order_group
  ON order_group.condition_id = profile.condition_id
JOIN resolution_order_group_orders AS tracked
  ON tracked.order_group_id = order_group.order_group_id
WHERE profile.profile_key = ANY(CAST(:profile_keys AS text[]))
  AND order_group.created_at >=
      schedule.activate_at - interval '15 minutes'
  AND tracked.status = 'LIVE'
ORDER BY profile.profile_key, tracked.generation, tracked.opened_at
""".strip()

_SUPERVISION_SQL = """
SELECT
    profile.profile_key,
    profile.metadata ->> 'ticker' AS ticker,
    event.event_type,
    event.status,
    event.old_tick,
    event.new_tick,
    event.observed_at,
    event.created_at,
    event.updated_at,
    event.error
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
JOIN resolution_order_groups AS order_group
  ON order_group.condition_id = profile.condition_id
JOIN resolution_supervision_events AS event
  ON event.order_group_id = order_group.order_group_id
WHERE profile.profile_key = ANY(CAST(:profile_keys AS text[]))
  AND order_group.created_at >=
      schedule.activate_at - interval '15 minutes'
ORDER BY profile.profile_key, event.created_at, event.event_id
""".strip()


def _safe(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return redact_sensitive_text(value)


def _emit(prefix: str, rows) -> None:
    for row in rows:
        print(
            prefix
            + " "
            + json.dumps(
                {
                    key: _safe(value)
                    for key, value in dict(row).items()
                },
                sort_keys=True,
            )
        )


def main() -> int:
    settings = HostedResolutionSettings.from_env(os.environ)
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
    )
    params = {"profile_keys": list(_PROFILE_KEYS)}
    gateway = None
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                summaries = connection.execute(
                    text(_SUMMARY_SQL), params
                ).mappings().all()
                sources = connection.execute(
                    text(_SOURCE_SQL), params
                ).mappings().all()
                orders = connection.execute(
                    text(_ORDER_SQL), params
                ).mappings().all()
                journals = connection.execute(
                    text(_JOURNAL_SQL), params
                ).mappings().all()
                remote_orders = connection.execute(
                    text(_REMOTE_ORDER_SQL), params
                ).mappings().all()
                supervision = connection.execute(
                    text(_SUPERVISION_SQL), params
                ).mappings().all()
        _emit("POSTMARKET_SUMMARY", summaries)
        _emit("POSTMARKET_SOURCE", sources)
        _emit("POSTMARKET_ORDER", orders)
        _emit("POSTMARKET_JOURNAL", journals)
        _emit("POSTMARKET_SUPERVISION", supervision)
        gateway = PolymarketSupervisionOrderGateway(
            database_url=settings.database_url or "",
            safety=LiveSafetySettings.from_env(os.environ),
        )
        for row in remote_orders:
            inspection = gateway.inspect_orders(
                account_name=str(row["account_name"]),
                order_ids=(str(row["order_id"]),),
            )
            if inspection.failed_order_ids:
                payload = {
                    "profile_key": str(row["profile_key"]),
                    "ticker": str(row["ticker"]),
                    "inspection": "FAILED",
                    "orders_changed": False,
                    "error": _safe(inspection.error),
                }
            else:
                snapshot = inspection.snapshots[0]
                payload = {
                    "profile_key": str(row["profile_key"]),
                    "ticker": str(row["ticker"]),
                    "inspection": "OK",
                    "orders_changed": False,
                    "state": snapshot.state.value,
                    "remote_status": snapshot.remote_status,
                    "limit_price": str(snapshot.limit_price),
                    "original_quantity": str(
                        snapshot.original_quantity
                    ),
                    "matched_quantity": str(
                        snapshot.matched_quantity
                    ),
                    "remaining_quantity": str(
                        snapshot.remaining_quantity
                    ),
                    "observed_at": snapshot.observed_at.isoformat(),
                }
            print(
                "POSTMARKET_REMOTE "
                + json.dumps(payload, sort_keys=True)
            )
    finally:
        if gateway is not None:
            gateway.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
