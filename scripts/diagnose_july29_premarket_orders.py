from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine, text

from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.resolution_hosted.settings import HostedResolutionSettings
from cbr_trading.secret_guard import redact_sensitive_text


_SQL = """
SELECT
    profile.profile_key,
    profile.metadata ->> 'ticker' AS ticker,
    schedule.state AS schedule_state,
    profile.status AS profile_status,
    fact.provider AS fact_provider,
    source_event.filed_at AS source_filed_at,
    source_event.received_at AS source_received_at,
    source_event.status AS source_event_status,
    fact.detected_at,
    claim.status AS claim_status,
    claim.outcome AS claim_outcome,
    claim.desired_price AS claim_desired_price,
    claim.effective_price AS claim_effective_price,
    claim.quantity AS claim_quantity,
    claim.created_at AS claim_created_at,
    claim.completed_at AS claim_completed_at,
    groups.status AS group_status,
    groups.desired_price AS group_desired_price,
    groups.reprice_count,
    groups.max_reprices,
    groups.created_at AS group_created_at,
    groups.updated_at AS group_updated_at,
    groups.last_error AS group_last_error,
    current_order.generation AS current_generation,
    current_order.status AS current_order_status,
    current_order.effective_price AS current_order_price,
    current_order.opened_at AS current_order_opened_at,
    current_order.closed_at AS current_order_closed_at,
    supervision.event_count AS supervision_event_count,
    supervision.event_type AS last_supervision_event_type,
    supervision.status AS last_supervision_status,
    supervision.old_tick AS last_observed_old_tick,
    supervision.new_tick AS last_observed_new_tick,
    supervision.observed_at AS last_supervision_observed_at,
    supervision.error AS last_supervision_error,
    observation.observation_count,
    observation.remote_state AS last_remote_state,
    observation.remote_status AS last_remote_status,
    observation.limit_price AS last_observed_price,
    observation.matched_quantity AS last_matched_quantity,
    observation.remaining_quantity AS last_remaining_quantity,
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
LEFT JOIN earnings_source_events AS source_event
  ON source_event.id = fact.source_event_id
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
) AS groups ON true
LEFT JOIN LATERAL (
    SELECT order_row.*
    FROM resolution_order_group_orders AS order_row
    WHERE order_row.order_group_id = groups.order_group_id
    ORDER BY order_row.generation DESC, order_row.id DESC
    LIMIT 1
) AS current_order ON true
LEFT JOIN LATERAL (
    SELECT
        count(*) AS event_count,
        latest.event_type,
        latest.status,
        latest.old_tick,
        latest.new_tick,
        latest.observed_at,
        latest.error
    FROM resolution_supervision_events AS event
    LEFT JOIN LATERAL (
        SELECT selected.*
        FROM resolution_supervision_events AS selected
        WHERE selected.order_group_id = groups.order_group_id
        ORDER BY selected.observed_at DESC, selected.event_id DESC
        LIMIT 1
    ) AS latest ON true
    WHERE event.order_group_id = groups.order_group_id
    GROUP BY
        latest.event_type,
        latest.status,
        latest.old_tick,
        latest.new_tick,
        latest.observed_at,
        latest.error
) AS supervision ON true
LEFT JOIN LATERAL (
    SELECT
        count(*) AS observation_count,
        latest.remote_state,
        latest.remote_status,
        latest.limit_price,
        latest.matched_quantity,
        latest.remaining_quantity,
        latest.observed_at
    FROM resolution_order_observations AS item
    LEFT JOIN LATERAL (
        SELECT selected.*
        FROM resolution_order_observations AS selected
        WHERE selected.order_group_id = groups.order_group_id
        ORDER BY selected.observed_at DESC, selected.created_at DESC
        LIMIT 1
    ) AS latest ON true
    WHERE item.order_group_id = groups.order_group_id
    GROUP BY
        latest.remote_state,
        latest.remote_status,
        latest.limit_price,
        latest.matched_quantity,
        latest.remaining_quantity,
        latest.observed_at
) AS observation ON true
WHERE profile.profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-wing-2026q2',
    'earnings-arcc-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2',
    'earnings-cbre-2026q2',
    'earnings-pag-2026q2'
)
ORDER BY profile.profile_key
""".strip()

_REPRICE_EVENT_SQL = """
SELECT
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
JOIN resolution_order_groups AS groups
  ON groups.condition_id = profile.condition_id
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
JOIN resolution_supervision_events AS event
  ON event.order_group_id = groups.order_group_id
WHERE profile.profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2'
)
  AND groups.created_at >=
      schedule.activate_at - interval '15 minutes'
ORDER BY ticker, event.created_at, event.event_id
""".strip()

_REPRICE_ORDER_SQL = """
SELECT
    profile.metadata ->> 'ticker' AS ticker,
    tracked.generation,
    tracked.status,
    tracked.effective_price,
    tracked.quantity,
    tracked.opened_at,
    tracked.closed_at
FROM resolution_execution_profiles AS profile
JOIN resolution_order_groups AS groups
  ON groups.condition_id = profile.condition_id
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
JOIN resolution_order_group_orders AS tracked
  ON tracked.order_group_id = groups.order_group_id
WHERE profile.profile_key IN (
    'earnings-pg-2026q4',
    'earnings-grmn-2026q2'
)
  AND groups.created_at >=
      schedule.activate_at - interval '15 minutes'
ORDER BY ticker, tracked.generation, tracked.opened_at
""".strip()

_REMOTE_ORDER_SQL = """
SELECT
    profile.metadata ->> 'ticker' AS ticker,
    groups.account_name,
    tracked.order_id
FROM resolution_execution_profiles AS profile
JOIN resolution_order_groups AS groups
  ON groups.condition_id = profile.condition_id
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
JOIN resolution_order_group_orders AS tracked
  ON tracked.order_group_id = groups.order_group_id
WHERE profile.profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2'
)
  AND groups.created_at >=
      schedule.activate_at - interval '15 minutes'
  AND tracked.status = 'LIVE'
ORDER BY ticker, tracked.generation, tracked.opened_at
""".strip()

_RUN_JOURNAL_SQL = """
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
WHERE profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-wing-2026q2',
    'earnings-arcc-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2',
    'earnings-cbre-2026q2',
    'earnings-pag-2026q2'
)
ORDER BY profile_key
""".strip()

_SOURCE_FAILURE_SQL = """
SELECT
    profile.metadata ->> 'ticker' AS ticker,
    event.provider,
    event.status,
    event.source_url,
    event.filing_url,
    event.filed_at,
    event.received_at,
    event.error
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
JOIN earnings_source_events AS event
  ON event.scope_id = profile.scope_id
WHERE profile.profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-wing-2026q2',
    'earnings-arcc-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2',
    'earnings-cbre-2026q2',
    'earnings-pag-2026q2'
)
  AND event.status IN ('NO_MATCH', 'QUARANTINED', 'ERROR')
  AND event.received_at >=
      schedule.activate_at - interval '15 minutes'
ORDER BY ticker, event.received_at, event.id
""".strip()


def _safe(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return redact_sensitive_text(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-remote",
        action="store_true",
        help="skip read-only remote order inspection",
    )
    args = parser.parse_args(argv)
    settings = HostedResolutionSettings.from_env(os.environ)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    gateway = None
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                rows = connection.execute(text(_SQL)).mappings().all()
                event_rows = connection.execute(
                    text(_REPRICE_EVENT_SQL)
                ).mappings().all()
                order_rows = connection.execute(
                    text(_REPRICE_ORDER_SQL)
                ).mappings().all()
                remote_order_rows = connection.execute(
                    text(_REMOTE_ORDER_SQL)
                ).mappings().all()
                journal_rows = connection.execute(
                    text(_RUN_JOURNAL_SQL)
                ).mappings().all()
                failure_rows = connection.execute(
                    text(_SOURCE_FAILURE_SQL)
                ).mappings().all()
        for row in rows:
            print(
                "AUDIT "
                + json.dumps(
                    {
                        key: _safe(value)
                        for key, value in dict(row).items()
                    },
                    sort_keys=True,
                )
            )
        for row in event_rows:
            print(
                "REPRICE_EVENT "
                + json.dumps(
                    {
                        key: _safe(value)
                        for key, value in dict(row).items()
                    },
                    sort_keys=True,
                )
            )
        for row in order_rows:
            print(
                "REPRICE_ORDER "
                + json.dumps(
                    {
                        key: _safe(value)
                        for key, value in dict(row).items()
                    },
                    sort_keys=True,
                )
            )
        for row in journal_rows:
            print(
                "RUN_JOURNAL "
                + json.dumps(
                    {
                        key: _safe(value)
                        for key, value in dict(row).items()
                    },
                    sort_keys=True,
                )
            )
        for row in failure_rows:
            print(
                "SOURCE_FAILURE "
                + json.dumps(
                    {
                        key: _safe(value)
                        for key, value in dict(row).items()
                    },
                    sort_keys=True,
                )
            )
        if not args.skip_remote:
            safety = LiveSafetySettings.from_env(os.environ)
            gateway = PolymarketSupervisionOrderGateway(
                database_url=settings.database_url or "",
                safety=safety,
            )
            for row in remote_order_rows:
                inspection = gateway.inspect_orders(
                    account_name=str(row["account_name"]),
                    order_ids=(str(row["order_id"]),),
                )
                if inspection.failed_order_ids:
                    payload = {
                        "ticker": str(row["ticker"]),
                        "inspection": "FAILED",
                        "error": _safe(inspection.error),
                    }
                else:
                    snapshot = inspection.snapshots[0]
                    payload = {
                        "ticker": str(row["ticker"]),
                        "inspection": "OK",
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
                    "REMOTE_ORDER "
                    + json.dumps(payload, sort_keys=True)
                )
    finally:
        if gateway is not None:
            gateway.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
