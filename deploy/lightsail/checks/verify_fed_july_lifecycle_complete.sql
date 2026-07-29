BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE profile.source_name = 'fed_fomc'
          AND profile.scope_id LIKE 'fed:fomc:2026-07-29:%'
          AND profile.status = 'DISABLED'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'COMPLETED'
    ) <> 5 THEN
        RAISE EXCEPTION 'FED lifecycle completion set is invalid';
    END IF;
END
$verification$;

ROLLBACK;
