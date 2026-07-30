-- Read-only terminal-state guard for the July 29 MSFT parser quarantine.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-msft-2026q4'
          AND schedule.state = 'COMPLETED'
          AND profile.status = 'DISABLED'
          AND schedule.metadata ->> 'parser_error' =
              'conflicting_microsoft_gaap_eps_values'
          AND schedule.metadata ->> 'investigation_required' = 'true'
    ) <> 1 THEN
        RAISE EXCEPTION 'MSFT parser quarantine is not safely closed';
    END IF;
END
$verification$;

ROLLBACK;
