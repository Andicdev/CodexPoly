-- Verify the additive COMPLETED lifecycle state without returning rows,
-- profile data, account data, claims, orders, or secret values.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM pg_constraint
        WHERE conrelid = to_regclass('resolution_profile_schedules')
          AND conname =
              'resolution_profile_schedules_state_check'
          AND pg_get_constraintdef(oid) LIKE '%COMPLETED%'
    ) <> 1 THEN
        RAISE EXCEPTION
            'COMPLETED schedule state constraint is not ready';
    END IF;

    IF (
        SELECT count(*)
        FROM pg_constraint
        WHERE conrelid =
              to_regclass('resolution_profile_schedule_events')
          AND conname IN (
              'resolution_profile_schedule_events_previous_state_check',
              'resolution_profile_schedule_events_next_state_check'
          )
          AND pg_get_constraintdef(oid) LIKE '%COMPLETED%'
    ) <> 2 THEN
        RAISE EXCEPTION
            'COMPLETED schedule event constraints are not ready';
    END IF;
END
$verification$;

ROLLBACK;
