-- Read-only terminal-state guard for the unconfirmed July 29 EA schedule.

BEGIN TRANSACTION READ ONLY;

DO $verification$
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
    ) <> 1 THEN
        RAISE EXCEPTION 'EA terminal state is invalid';
    END IF;
END
$verification$;

ROLLBACK;
