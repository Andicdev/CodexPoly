-- Read-only terminal-state guard for the July 29 HOOD incident.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-hood-2026q2'
          AND schedule.state = 'COMPLETED'
          AND profile.status = 'DISABLED'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'investigation_required' = 'true'
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD terminal state is invalid';
    END IF;
END
$verification$;

ROLLBACK;
