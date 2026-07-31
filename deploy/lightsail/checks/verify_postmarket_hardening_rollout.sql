-- Rollout-specific fail-closed checks for production deployment 33883ce.
-- The cutoff precedes the first production restart guard on 2026-07-31.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        WHERE schedule.state = 'COMPLETED'
          AND schedule.updated_at >=
              timestamptz '2026-07-31 06:14:00+00'
          AND NOT EXISTS (
              SELECT 1
              FROM resolution_profile_schedule_events AS event
              WHERE event.schedule_id = schedule.id
                AND event.next_state = 'COMPLETED'
                AND event.event_kind =
                    'RESOLUTION_EXECUTION_COMPLETED'
          )
    ) THEN
        RAISE EXCEPTION
            'rollout created a completed schedule audit gap';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE status = 'ENABLED'
    ) THEN
        RAISE EXCEPTION
            'execution profile became enabled during rollout';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE status = 'PENDING'
          AND created_at >=
              timestamptz '2026-07-31 06:14:00+00'
    ) THEN
        RAISE EXCEPTION
            'rollout created a pending execution claim';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION
            'rollout left active order supervision';
    END IF;
END
$verification$;

ROLLBACK;
