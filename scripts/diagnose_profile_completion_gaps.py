from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime

from cbr_trading.db_config import resolve_database_selection
from cbr_trading.secret_guard import redact_exception


_CONFIRMATION = "READ_ONLY_COMPLETION_GAPS"

_GAPS_SQL = """
SELECT
    schedule.schedule_key,
    schedule.profile_key,
    profile.scope_id,
    schedule.automation_mode,
    schedule.state AS schedule_state,
    profile.status AS profile_status,
    schedule.metadata ->> 'completion_reason'
        AS completion_reason,
    schedule.metadata ->> 'terminal_reason'
        AS terminal_reason,
    schedule.updated_at,
    (
        SELECT count(*)
        FROM resolution_execution_claims AS claim
        WHERE claim.scope_id = profile.scope_id
    ) AS claim_count,
    (
        SELECT count(*)
        FROM resolution_execution_claims AS claim
        WHERE claim.scope_id = profile.scope_id
          AND claim.status = 'EXECUTED'
          AND claim.result ->> 'attempted' = 'true'
          AND claim.result ->> 'accepted' = 'true'
    ) AS accepted_execution_count,
    (
        SELECT count(*)
        FROM resolution_execution_claims AS claim
        WHERE claim.scope_id = profile.scope_id
          AND claim.status = 'EXPIRED'
    ) AS expired_claim_count,
    (
        SELECT count(*)
        FROM earnings_fact_candidates AS fact
        WHERE fact.scope_id = profile.scope_id
          AND fact.status IN ('VALIDATED', 'EMITTED')
    ) AS validated_fact_count,
    (
        SELECT count(*)
        FROM resolution_order_groups AS order_group
        WHERE order_group.condition_id = profile.condition_id
          AND order_group.status IN ('ACTIVE', 'REPRICING')
    ) AS active_order_group_count,
    COALESCE(
        (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'previous_state', event.previous_state,
                    'next_state', event.next_state,
                    'event_kind', event.event_kind,
                    'reason_code', event.reason_code,
                    'created_at', event.created_at
                )
                ORDER BY event.created_at, event.id
            )
            FROM resolution_profile_schedule_events AS event
            WHERE event.schedule_id = schedule.id
        ),
        '[]'::jsonb
    ) AS lifecycle_events
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.state = 'COMPLETED'
  AND profile.status = 'DISABLED'
  AND schedule.last_error_code IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_profile_schedule_events AS event
      WHERE event.schedule_id = schedule.id
        AND event.next_state = 'COMPLETED'
        AND event.event_kind = 'RESOLUTION_EXECUTION_COMPLETED'
        AND (
            (
                event.previous_state = 'ACTIVE'
                AND event.reason_code =
                    'resolution_execution_completed'
            )
            OR (
                event.previous_state IN ('ACTIVE', 'BLOCKED')
                AND event.reason_code =
                    'historical_executed_claim_reconciled'
                AND event.metadata
                    ->> 'historical_reconciliation' = 'true'
                AND event.metadata
                    ->> 'existing_orders_left_unchanged' = 'true'
            )
        )
  )
ORDER BY schedule.schedule_key
""".strip()


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    if args.confirm != _CONFIRMATION:
        _emit(
            {
                "ok": False,
                "error": "explicit read-only confirmation is required",
            },
            stream=sys.stderr,
        )
        return 2

    runtime_environ = os.environ if environ is None else environ
    database = resolve_database_selection("primary", runtime_environ)
    if not database.url:
        _emit(
            {
                "ok": False,
                "error": database.error or "database is not configured",
            },
            stream=sys.stderr,
        )
        return 3

    engine = None
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(
            database.url,
            pool_pre_ping=True,
            hide_parameters=True,
        )
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(
                    text("SET TRANSACTION READ ONLY")
                )
                rows = connection.execute(
                    text(_GAPS_SQL)
                ).mappings().all()
        gaps = [_safe_gap(row) for row in rows]
        _emit(
            {
                "ok": True,
                "database_target": database.target,
                "gap_count": len(gaps),
                "gaps": gaps,
            }
        )
        return 0
    except Exception as exc:
        _emit(
            {
                "ok": False,
                "error": redact_exception(exc),
            },
            stream=sys.stderr,
        )
        return 4
    finally:
        if engine is not None:
            engine.dispose()


def _safe_gap(row: Mapping[str, object]) -> dict[str, object]:
    allowed = (
        "schedule_key",
        "profile_key",
        "scope_id",
        "automation_mode",
        "schedule_state",
        "profile_status",
        "completion_reason",
        "terminal_reason",
        "updated_at",
        "claim_count",
        "accepted_execution_count",
        "expired_claim_count",
        "validated_fact_count",
        "active_order_group_count",
        "lifecycle_events",
    )
    payload: dict[str, object] = {}
    for key in allowed:
        value = row.get(key)
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
        elif key.endswith("_count"):
            payload[key] = int(value or 0)
        elif key == "lifecycle_events":
            payload[key] = _safe_lifecycle_events(value)
        else:
            payload[key] = value
    return payload


def _safe_lifecycle_events(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    allowed = (
        "previous_state",
        "next_state",
        "event_kind",
        "reason_code",
        "created_at",
    )
    events: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        event: dict[str, object] = {}
        for key in allowed:
            field = item.get(key)
            event[key] = (
                field.isoformat()
                if isinstance(field, datetime)
                else field
            )
        events.append(event)
    return events


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "List only non-secret identifiers and aggregate evidence for "
            "COMPLETED schedules missing an accepted "
            "execution-completion audit event."
        )
    )
    parser.add_argument("--confirm", required=True)
    return parser


def _emit(
    payload: object,
    *,
    stream: object = sys.stdout,
) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
