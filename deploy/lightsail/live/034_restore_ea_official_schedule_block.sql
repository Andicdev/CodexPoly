-- Restore the operator-selected EA block after the old scheduler converted
-- every non-COMPLETED terminal state to EXPIRED at window close.

BEGIN;

DO $guard$
BEGIN
    PERFORM schedule.id
    FROM resolution_profile_schedules AS schedule
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = schedule.profile_key
    WHERE schedule.profile_key = 'earnings-ea-2027q1'
    FOR UPDATE OF schedule, profile;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-ea-2027q1'
          AND schedule.state = 'EXPIRED'
          AND profile.status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'EA expired-state restore guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key =
              'schedule-block:earnings-ea-2027q1:2026-07-29'
          AND previous_state = 'ACTIVE'
          AND next_state = 'BLOCKED'
          AND reason_code = 'official_schedule_unconfirmed'
    ) <> 1 THEN
        RAISE EXCEPTION 'EA original operator block is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:EA:2027Q1'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:EA:2027Q1'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) THEN
        RAISE EXCEPTION 'EA source or execution evidence changed';
    END IF;
END
$guard$;

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
SELECT
    'schedule-restore-block:earnings-ea-2027q1:2026-07-30',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'BLOCKED',
    'OPERATOR_BLOCK_RESTORED',
    'official_schedule_unconfirmed',
    jsonb_build_object(
        'original_event_key',
        'schedule-block:earnings-ea-2027q1:2026-07-29',
        'scheduler_fix',
        'blocked_schedules_are_terminal',
        'fail_closed',
        true
    )
FROM resolution_profile_schedules AS schedule
WHERE schedule.profile_key = 'earnings-ea-2027q1'
  AND schedule.state = 'EXPIRED'
ON CONFLICT (event_key) DO NOTHING;

UPDATE resolution_profile_schedules
SET
    state = 'BLOCKED',
    last_error_code = 'official_schedule_unconfirmed',
    metadata = metadata || jsonb_build_object(
        'block_reason',
        'official_schedule_unconfirmed',
        'scheduler_fix',
        'blocked_schedules_are_terminal'
    ),
    updated_at = now()
WHERE profile_key = 'earnings-ea-2027q1'
  AND state = 'EXPIRED';

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-ea-2027q1'
          AND schedule.state = 'BLOCKED'
          AND profile.status = 'DISABLED'
          AND schedule.last_error_code =
              'official_schedule_unconfirmed'
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key =
              'schedule-restore-block:earnings-ea-2027q1:2026-07-30'
          AND previous_state = 'EXPIRED'
          AND next_state = 'BLOCKED'
          AND reason_code = 'official_schedule_unconfirmed'
    ) <> 1 THEN
        RAISE EXCEPTION 'EA operator block restore verification failed';
    END IF;
END
$verify$;

COMMIT;
