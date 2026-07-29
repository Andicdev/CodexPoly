-- Verify successful terminal lifecycle invariants without returning profile,
-- event, source, account, claim, or order data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.state = 'COMPLETED'
          AND (
              profile.status <> 'DISABLED'
              OR schedule.last_error_code IS NOT NULL
          )
    ) THEN
        RAISE EXCEPTION
            'COMPLETED schedule/profile invariant failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        WHERE schedule.state = 'COMPLETED'
          AND NOT EXISTS (
              SELECT 1
              FROM resolution_profile_schedule_events AS event
              WHERE event.schedule_id = schedule.id
                AND event.previous_state = 'ACTIVE'
                AND event.next_state = 'COMPLETED'
                AND event.event_kind =
                    'RESOLUTION_EXECUTION_COMPLETED'
                AND event.reason_code =
                    'resolution_execution_completed'
          )
    ) THEN
        RAISE EXCEPTION
            'COMPLETED schedule audit event is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedule_events AS event
        JOIN resolution_profile_schedules AS schedule
          ON schedule.id = event.schedule_id
        WHERE event.next_state = 'COMPLETED'
          AND schedule.state <> 'COMPLETED'
    ) THEN
        RAISE EXCEPTION
            'COMPLETED lifecycle state was overwritten';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedule_events
        WHERE event_kind = 'RESOLUTION_EXECUTION_COMPLETED'
        GROUP BY schedule_id
        HAVING count(*) <> 1
    ) THEN
        RAISE EXCEPTION
            'COMPLETED lifecycle event is not idempotent';
    END IF;
END
$verification$;

ROLLBACK;
