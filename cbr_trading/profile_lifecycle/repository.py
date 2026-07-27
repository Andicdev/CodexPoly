from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from cbr_trading.profile_lifecycle.contracts import (
    ProfileAutomationMode,
    ProfilePreflightClaim,
    ProfileScheduleState,
    ProfileScheduleTransition,
    ResolutionProfileSchedule,
)


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "012_add_resolution_profile_schedules.sql"
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('resolution_profile_schedules') IS NOT NULL
        AS schedules_table,
    (
        SELECT count(*) = 18
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_profile_schedules'
    ) AS schedules_columns,
    to_regclass('resolution_profile_schedule_events') IS NOT NULL
        AS events_table,
    (
        SELECT count(*) = 12
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'resolution_profile_schedule_events'
    ) AS events_columns,
    to_regclass('ux_resolution_profile_schedules_key') IS NOT NULL
        AS schedule_key_index,
    to_regclass('ux_resolution_profile_schedules_profile') IS NOT NULL
        AS schedule_profile_index,
    to_regclass('ux_resolution_profile_schedule_events_key') IS NOT NULL
        AS event_key_index,
    to_regclass('ix_resolution_profile_schedule_events_notify') IS NOT NULL
        AS event_notify_index
""".strip()

_UPSERT_SQL = """
INSERT INTO resolution_profile_schedules (
    schedule_key,
    profile_key,
    automation_mode,
    preflight_at,
    activate_at,
    deactivate_at,
    metadata,
    state
)
VALUES (
    :schedule_key,
    :profile_key,
    :automation_mode,
    :preflight_at,
    :activate_at,
    :deactivate_at,
    CAST(:metadata AS jsonb),
    'PENDING'
)
ON CONFLICT (schedule_key) DO UPDATE
SET
    profile_key = EXCLUDED.profile_key,
    automation_mode = EXCLUDED.automation_mode,
    preflight_at = EXCLUDED.preflight_at,
    activate_at = EXCLUDED.activate_at,
    deactivate_at = EXCLUDED.deactivate_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
WHERE resolution_profile_schedules.state = 'PENDING'
RETURNING id
""".strip()

_SELECT_DUE_PREFLIGHT_SQL = """
SELECT
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.automation_mode,
    schedule.activate_at,
    schedule.deactivate_at,
    profile.scope_id,
    profile.source_reference
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.state = 'PENDING'
  AND schedule.automation_mode IN ('AUTO_PREFLIGHT', 'AUTO_LIVE')
  AND schedule.preflight_at <= :now
  AND schedule.deactivate_at > :now
ORDER BY schedule.preflight_at, schedule.id
FOR UPDATE OF schedule SKIP LOCKED
LIMIT 1
""".strip()

_SELECT_DUE_BLOCK_SQL = """
SELECT
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.automation_mode,
    schedule.state,
    schedule.activate_at,
    schedule.deactivate_at,
    profile.scope_id,
    profile.source_reference
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.state IN ('PENDING', 'PREFLIGHTING')
  AND schedule.automation_mode IN ('AUTO_PREFLIGHT', 'AUTO_LIVE')
  AND schedule.activate_at
        + CAST(:grace_seconds AS double precision) * interval '1 second'
      <= :now
  AND schedule.deactivate_at > :now
ORDER BY schedule.activate_at, schedule.id
FOR UPDATE OF schedule SKIP LOCKED
LIMIT 1
""".strip()

_SELECT_DUE_ACTIVATION_SQL = """
SELECT
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.automation_mode,
    schedule.state,
    schedule.activate_at,
    schedule.deactivate_at,
    schedule.readiness_valid_until,
    profile.scope_id,
    profile.source_reference,
    profile.status AS profile_status,
    profile.quantity * GREATEST(
        profile.yes_desired_price,
        profile.no_desired_price
    ) AS profile_notional
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.state = 'READY'
  AND schedule.automation_mode = 'AUTO_LIVE'
  AND schedule.activate_at <= :now
  AND schedule.deactivate_at > :now
ORDER BY schedule.activate_at, schedule.id
FOR UPDATE OF schedule, profile SKIP LOCKED
LIMIT 1
""".strip()

_SELECT_DUE_EXPIRY_SQL = """
SELECT
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.automation_mode,
    schedule.state,
    schedule.activate_at,
    schedule.deactivate_at,
    profile.scope_id,
    profile.source_reference,
    profile.status AS profile_status
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.state NOT IN ('EXPIRED')
  AND schedule.automation_mode IN ('AUTO_PREFLIGHT', 'AUTO_LIVE')
  AND schedule.deactivate_at <= :now
ORDER BY schedule.deactivate_at, schedule.id
FOR UPDATE OF schedule, profile SKIP LOCKED
LIMIT 1
""".strip()

_SELECT_PREFLIGHT_CLAIM_SQL = """
SELECT
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.preflight_request_id,
    schedule.activate_at,
    schedule.deactivate_at
FROM resolution_profile_schedules AS schedule
WHERE schedule.state = 'PREFLIGHTING'
  AND schedule.preflight_request_id IS NOT NULL
  AND (
      schedule.preflight_lease_until IS NULL
      OR schedule.preflight_lease_until < :now
  )
  AND schedule.deactivate_at > :now
ORDER BY schedule.preflight_requested_at, schedule.id
FOR UPDATE OF schedule SKIP LOCKED
LIMIT 1
""".strip()

_SELECT_EVENT_SQL = """
SELECT
    event.id AS event_id,
    event.event_key,
    event.schedule_key,
    event.profile_key,
    event.previous_state,
    event.next_state,
    event.event_kind,
    event.reason_code,
    schedule.automation_mode,
    schedule.activate_at,
    schedule.deactivate_at,
    profile.scope_id,
    profile.source_reference
FROM resolution_profile_schedule_events AS event
JOIN resolution_profile_schedules AS schedule
  ON schedule.id = event.schedule_id
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = event.profile_key
WHERE event.notification_enqueued_at IS NULL
ORDER BY event.id
LIMIT 1
""".strip()

_INSERT_EVENT_SQL = """
INSERT INTO resolution_profile_schedule_events (
    event_key,
    schedule_id,
    schedule_key,
    profile_key,
    previous_state,
    next_state,
    event_kind,
    reason_code,
    metadata
)
VALUES (
    :event_key,
    :schedule_id,
    :schedule_key,
    :profile_key,
    :previous_state,
    :next_state,
    :event_kind,
    :reason_code,
    CAST(:metadata AS jsonb)
)
RETURNING id
""".strip()


class ProfileLifecycleStoreError(RuntimeError):
    """Sanitized persistence failure for scheduled profile state."""


@dataclass(frozen=True)
class StoredProfileSchedule:
    row_id: int


class SqlAlchemyProfileLifecycleStore:
    """Atomic lifecycle transitions with an append-only audit trail."""

    def __init__(
        self,
        *,
        database_url: str | None = None,
        session_factory: Callable[[], Any] | None = None,
        text_factory: Callable[[str], Any] | None = None,
    ):
        self._database_url = str(database_url or "").strip()
        self._session_factory = session_factory
        self._text_factory = text_factory
        self._engine: Any | None = None

    def migrate(self) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(
                    text_factory(
                        _MIGRATION_PATH.read_text(encoding="utf-8")
                    )
                )
                session.commit()
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to apply profile lifecycle migration: "
                f"{type(exc).__name__}"
            ) from None

    def ensure_ready(self) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SCHEMA_READY_SQL)
                ).mappings().one()
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to verify profile lifecycle schema: "
                f"{type(exc).__name__}"
            ) from None
        if not all(bool(value) for value in row.values()):
            raise ProfileLifecycleStoreError(
                "Profile lifecycle schema is not ready"
            )

    def save(
        self,
        schedule: ResolutionProfileSchedule,
    ) -> StoredProfileSchedule:
        params = {
            "schedule_key": schedule.schedule_key,
            "profile_key": schedule.profile_key,
            "automation_mode": schedule.automation_mode.value,
            "preflight_at": schedule.preflight_at,
            "activate_at": schedule.activate_at,
            "deactivate_at": schedule.deactivate_at,
            "metadata": json.dumps(
                dict(schedule.metadata),
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_UPSERT_SQL),
                    params,
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    raise ProfileLifecycleStoreError(
                        "Only a pending profile schedule can be updated"
                    )
                session.commit()
        except ProfileLifecycleStoreError:
            raise
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to save profile schedule: "
                f"{type(exc).__name__}"
            ) from None
        return StoredProfileSchedule(row_id=int(row["id"]))

    def request_due_preflight(
        self,
        *,
        now: datetime,
    ) -> ProfileScheduleTransition | None:
        current = _as_utc(now)
        request_id = uuid.uuid4().hex
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SELECT_DUE_PREFLIGHT_SQL),
                    {"now": current},
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    return None
                session.execute(
                    text_factory(
                        """
                        UPDATE resolution_profile_schedules
                        SET
                            state = 'PREFLIGHTING',
                            preflight_request_id = :request_id,
                            preflight_requested_at = :now,
                            preflight_lease_until = NULL,
                            readiness_checked_at = NULL,
                            readiness_valid_until = NULL,
                            readiness_evidence = '{}'::jsonb,
                            last_error_code = NULL,
                            updated_at = now()
                        WHERE id = :schedule_id
                        """
                    ),
                    {
                        "request_id": request_id,
                        "now": current,
                        "schedule_id": int(row["id"]),
                    },
                )
                transition = self._insert_event(
                    session,
                    text_factory,
                    row=row,
                    previous_state=ProfileScheduleState.PENDING,
                    next_state=ProfileScheduleState.PREFLIGHTING,
                    event_kind="PREFLIGHT_REQUESTED",
                    reason_code=None,
                    event_suffix=request_id,
                )
                session.commit()
                return transition
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to request due profile preflight: "
                f"{type(exc).__name__}"
            ) from None

    def block_due_unready(
        self,
        *,
        now: datetime,
        grace_seconds: float,
    ) -> ProfileScheduleTransition | None:
        current = _as_utc(now)
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SELECT_DUE_BLOCK_SQL),
                    {
                        "now": current,
                        "grace_seconds": float(grace_seconds),
                    },
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    return None
                previous = ProfileScheduleState(str(row["state"]))
                reason = (
                    "preflight_not_requested"
                    if previous is ProfileScheduleState.PENDING
                    else "authenticated_preflight_not_ready"
                )
                self._set_schedule_state(
                    session,
                    text_factory,
                    schedule_id=int(row["id"]),
                    state=ProfileScheduleState.BLOCKED,
                    error_code=reason,
                )
                transition = self._insert_event(
                    session,
                    text_factory,
                    row=row,
                    previous_state=previous,
                    next_state=ProfileScheduleState.BLOCKED,
                    event_kind="ACTIVATION_BLOCKED",
                    reason_code=reason,
                )
                session.commit()
                return transition
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to block unready profile schedule: "
                f"{type(exc).__name__}"
            ) from None

    def activate_due_ready(
        self,
        *,
        now: datetime,
        max_total_notional: Decimal,
    ) -> ProfileScheduleTransition | None:
        current = _as_utc(now)
        cap = Decimal(str(max_total_notional))
        if not cap.is_finite() or cap <= 0:
            raise ValueError("max_total_notional must be positive")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                session.execute(
                    text_factory(
                        "LOCK TABLE resolution_execution_profiles "
                        "IN SHARE ROW EXCLUSIVE MODE"
                    )
                )
                row = session.execute(
                    text_factory(_SELECT_DUE_ACTIVATION_SQL),
                    {"now": current},
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    return None
                reason: str | None = None
                valid_until = row.get("readiness_valid_until")
                if valid_until is None or _as_utc(valid_until) <= current:
                    reason = "authenticated_preflight_expired"
                elif str(row["profile_status"]) != "DISABLED":
                    reason = "profile_not_disabled"
                else:
                    active_notional = session.execute(
                        text_factory(
                            """
                            SELECT COALESCE(
                                SUM(
                                    quantity * GREATEST(
                                        yes_desired_price,
                                        no_desired_price
                                    )
                                ),
                                0
                            ) AS total
                            FROM resolution_execution_profiles
                            WHERE status = 'ENABLED'
                            """
                        )
                    ).mappings().one()
                    prospective = Decimal(
                        str(active_notional["total"])
                    ) + Decimal(str(row["profile_notional"]))
                    if prospective > cap:
                        reason = "aggregate_notional_cap_exceeded"
                if reason is not None:
                    self._set_schedule_state(
                        session,
                        text_factory,
                        schedule_id=int(row["id"]),
                        state=ProfileScheduleState.BLOCKED,
                        error_code=reason,
                    )
                    transition = self._insert_event(
                        session,
                        text_factory,
                        row=row,
                        previous_state=ProfileScheduleState.READY,
                        next_state=ProfileScheduleState.BLOCKED,
                        event_kind="ACTIVATION_BLOCKED",
                        reason_code=reason,
                    )
                    session.commit()
                    return transition
                session.execute(
                    text_factory(
                        """
                        UPDATE resolution_execution_profiles
                        SET status = 'ENABLED', updated_at = now()
                        WHERE profile_key = :profile_key
                          AND status = 'DISABLED'
                        """
                    ),
                    {"profile_key": str(row["profile_key"])},
                )
                self._set_schedule_state(
                    session,
                    text_factory,
                    schedule_id=int(row["id"]),
                    state=ProfileScheduleState.ACTIVE,
                    error_code=None,
                )
                transition = self._insert_event(
                    session,
                    text_factory,
                    row=row,
                    previous_state=ProfileScheduleState.READY,
                    next_state=ProfileScheduleState.ACTIVE,
                    event_kind="PROFILE_ENABLED",
                    reason_code=None,
                )
                session.commit()
                return transition
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to activate ready profile schedule: "
                f"{type(exc).__name__}"
            ) from None

    def expire_due(
        self,
        *,
        now: datetime,
    ) -> ProfileScheduleTransition | None:
        current = _as_utc(now)
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SELECT_DUE_EXPIRY_SQL),
                    {"now": current},
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    return None
                previous = ProfileScheduleState(str(row["state"]))
                if str(row["profile_status"]) == "ENABLED":
                    session.execute(
                        text_factory(
                            """
                            UPDATE resolution_execution_profiles
                            SET status = 'DISABLED', updated_at = now()
                            WHERE profile_key = :profile_key
                              AND status = 'ENABLED'
                            """
                        ),
                        {"profile_key": str(row["profile_key"])},
                    )
                self._set_schedule_state(
                    session,
                    text_factory,
                    schedule_id=int(row["id"]),
                    state=ProfileScheduleState.EXPIRED,
                    error_code=None,
                )
                transition = self._insert_event(
                    session,
                    text_factory,
                    row=row,
                    previous_state=previous,
                    next_state=ProfileScheduleState.EXPIRED,
                    event_kind="WINDOW_EXPIRED",
                    reason_code=None,
                )
                session.commit()
                return transition
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to expire profile schedule: "
                f"{type(exc).__name__}"
            ) from None

    def claim_preflight(
        self,
        *,
        now: datetime,
        lease_seconds: float,
    ) -> ProfilePreflightClaim | None:
        current = _as_utc(now)
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SELECT_PREFLIGHT_CLAIM_SQL),
                    {"now": current},
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    return None
                session.execute(
                    text_factory(
                        """
                        UPDATE resolution_profile_schedules
                        SET
                            preflight_lease_until = :lease_until,
                            updated_at = now()
                        WHERE id = :schedule_id
                        """
                    ),
                    {
                        "lease_until": current
                        + timedelta(seconds=float(lease_seconds)),
                        "schedule_id": int(row["id"]),
                    },
                )
                session.commit()
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to claim profile preflight: "
                f"{type(exc).__name__}"
            ) from None
        return ProfilePreflightClaim(
            schedule_key=str(row["schedule_key"]),
            profile_key=str(row["profile_key"]),
            request_id=str(row["preflight_request_id"]),
            activate_at=row["activate_at"],
            deactivate_at=row["deactivate_at"],
        )

    def complete_preflight(
        self,
        claim: ProfilePreflightClaim,
        *,
        checked_at: datetime,
        valid_until: datetime,
        evidence: Mapping[str, object] | None = None,
    ) -> None:
        checked = _as_utc(checked_at)
        valid = _as_utc(valid_until)
        if valid <= checked:
            raise ValueError("valid_until must be after checked_at")
        bounded_valid = min(valid, claim.deactivate_at)
        if bounded_valid <= checked:
            raise ValueError(
                "preflight validity cannot extend past the schedule window"
            )
        self._finish_preflight(
            claim,
            checked_at=checked,
            valid_until=bounded_valid,
            evidence=evidence or {},
            next_state=ProfileScheduleState.READY,
            event_kind="PREFLIGHT_READY",
            error_code=None,
        )

    def fail_preflight(
        self,
        claim: ProfilePreflightClaim,
        *,
        checked_at: datetime,
        error_code: str,
    ) -> None:
        normalized = str(error_code or "").strip()
        if not normalized:
            raise ValueError("error_code is required")
        self._finish_preflight(
            claim,
            checked_at=_as_utc(checked_at),
            valid_until=None,
            evidence={},
            next_state=ProfileScheduleState.BLOCKED,
            event_kind="PREFLIGHT_BLOCKED",
            error_code=normalized[:100],
        )

    def load_unnotified_event(
        self,
    ) -> ProfileScheduleTransition | None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SELECT_EVENT_SQL)
                ).mappings().one_or_none()
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to load lifecycle notification event: "
                f"{type(exc).__name__}"
            ) from None
        return None if row is None else _transition_from_row(row)

    def mark_event_notified(self, event_id: int) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(
                        """
                        UPDATE resolution_profile_schedule_events
                        SET notification_enqueued_at = now()
                        WHERE id = :event_id
                          AND notification_enqueued_at IS NULL
                        RETURNING id
                        """
                    ),
                    {"event_id": int(event_id)},
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    return
                session.commit()
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to mark lifecycle event notified: "
                f"{type(exc).__name__}"
            ) from None

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _finish_preflight(
        self,
        claim: ProfilePreflightClaim,
        *,
        checked_at: datetime,
        valid_until: datetime | None,
        evidence: Mapping[str, object],
        next_state: ProfileScheduleState,
        event_kind: str,
        error_code: str | None,
    ) -> None:
        session_factory, text_factory = self._resolve_dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(
                        """
                        SELECT
                            schedule.id,
                            schedule.schedule_key,
                            schedule.profile_key,
                            schedule.automation_mode,
                            schedule.activate_at,
                            schedule.deactivate_at,
                            profile.scope_id,
                            profile.source_reference
                        FROM resolution_profile_schedules AS schedule
                        JOIN resolution_execution_profiles AS profile
                          ON profile.profile_key = schedule.profile_key
                        WHERE schedule.schedule_key = :schedule_key
                          AND schedule.profile_key = :profile_key
                          AND schedule.preflight_request_id = :request_id
                          AND schedule.state = 'PREFLIGHTING'
                        FOR UPDATE OF schedule
                        """
                    ),
                    {
                        "schedule_key": claim.schedule_key,
                        "profile_key": claim.profile_key,
                        "request_id": claim.request_id,
                    },
                ).mappings().one_or_none()
                if row is None:
                    session.rollback()
                    raise ProfileLifecycleStoreError(
                        "Profile preflight claim is no longer current"
                    )
                session.execute(
                    text_factory(
                        """
                        UPDATE resolution_profile_schedules
                        SET
                            state = :state,
                            preflight_lease_until = NULL,
                            readiness_checked_at = :checked_at,
                            readiness_valid_until = :valid_until,
                            readiness_evidence = CAST(:evidence AS jsonb),
                            last_error_code = :error_code,
                            updated_at = now()
                        WHERE id = :schedule_id
                        """
                    ),
                    {
                        "state": next_state.value,
                        "checked_at": checked_at,
                        "valid_until": valid_until,
                        "evidence": json.dumps(
                            dict(evidence),
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ),
                        "error_code": error_code,
                        "schedule_id": int(row["id"]),
                    },
                )
                self._insert_event(
                    session,
                    text_factory,
                    row=row,
                    previous_state=ProfileScheduleState.PREFLIGHTING,
                    next_state=next_state,
                    event_kind=event_kind,
                    reason_code=error_code,
                    event_suffix=claim.request_id,
                    metadata=evidence,
                )
                session.commit()
        except ProfileLifecycleStoreError:
            raise
        except Exception as exc:
            raise ProfileLifecycleStoreError(
                "Failed to finish profile preflight: "
                f"{type(exc).__name__}"
            ) from None

    def _set_schedule_state(
        self,
        session: Any,
        text_factory: Callable[[str], Any],
        *,
        schedule_id: int,
        state: ProfileScheduleState,
        error_code: str | None,
    ) -> None:
        session.execute(
            text_factory(
                """
                UPDATE resolution_profile_schedules
                SET
                    state = :state,
                    preflight_lease_until = NULL,
                    last_error_code = :error_code,
                    updated_at = now()
                WHERE id = :schedule_id
                """
            ),
            {
                "state": state.value,
                "error_code": error_code,
                "schedule_id": schedule_id,
            },
        )

    def _insert_event(
        self,
        session: Any,
        text_factory: Callable[[str], Any],
        *,
        row: Mapping[str, Any],
        previous_state: ProfileScheduleState | None,
        next_state: ProfileScheduleState,
        event_kind: str,
        reason_code: str | None,
        event_suffix: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ProfileScheduleTransition:
        suffix = event_suffix or uuid.uuid4().hex
        event_key = (
            f"profile-lifecycle:{row['schedule_key']}:"
            f"{event_kind.lower()}:{suffix}"
        )
        inserted = session.execute(
            text_factory(_INSERT_EVENT_SQL),
            {
                "event_key": event_key,
                "schedule_id": int(row["id"]),
                "schedule_key": str(row["schedule_key"]),
                "profile_key": str(row["profile_key"]),
                "previous_state": (
                    previous_state.value
                    if previous_state is not None
                    else None
                ),
                "next_state": next_state.value,
                "event_kind": event_kind,
                "reason_code": reason_code,
                "metadata": json.dumps(
                    dict(metadata or {}),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ),
            },
        ).mappings().one()
        data = dict(row)
        data.update(
            {
                "event_id": inserted["id"],
                "event_key": event_key,
                "previous_state": (
                    previous_state.value
                    if previous_state is not None
                    else None
                ),
                "next_state": next_state.value,
                "event_kind": event_kind,
                "reason_code": reason_code,
            }
        )
        return _transition_from_row(data)

    def _resolve_dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            if not self._database_url:
                raise ProfileLifecycleStoreError(
                    "Profile lifecycle database URL is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise ProfileLifecycleStoreError(
                    "Profile lifecycle requires SQLAlchemy "
                    "and a PostgreSQL driver"
                ) from None
            try:
                self._engine = create_engine(
                    _normalize_database_url(self._database_url),
                    pool_pre_ping=True,
                    pool_recycle=300,
                    pool_reset_on_return="rollback",
                    hide_parameters=True,
                )
                session_factory = sessionmaker(
                    bind=self._engine,
                    expire_on_commit=False,
                )
            except Exception as exc:
                raise ProfileLifecycleStoreError(
                    "Failed to initialize profile lifecycle database: "
                    f"{type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise ProfileLifecycleStoreError(
                    "Profile lifecycle requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _transition_from_row(
    row: Mapping[str, Any],
) -> ProfileScheduleTransition:
    previous = row.get("previous_state")
    return ProfileScheduleTransition(
        event_id=int(row["event_id"]),
        event_key=str(row["event_key"]),
        schedule_key=str(row["schedule_key"]),
        profile_key=str(row["profile_key"]),
        scope_id=str(row["scope_id"]),
        source_reference=str(row["source_reference"]),
        automation_mode=ProfileAutomationMode(
            str(row["automation_mode"])
        ),
        previous_state=(
            ProfileScheduleState(str(previous))
            if previous is not None
            else None
        ),
        next_state=ProfileScheduleState(str(row["next_state"])),
        event_kind=str(row["event_kind"]),
        reason_code=(
            str(row["reason_code"])
            if row.get("reason_code") is not None
            else None
        ),
        activate_at=row["activate_at"],
        deactivate_at=row["deactivate_at"],
    )


def _as_utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("lifecycle clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    return url
