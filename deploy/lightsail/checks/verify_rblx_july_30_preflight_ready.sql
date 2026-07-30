BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-30 19:15:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-30 19:20:00+00'
    THEN
        RAISE EXCEPTION 'RBLX readiness check is outside its valid interval';
    END IF;
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key =
              'schedule:earnings-rblx-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'READY'
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until >
              TIMESTAMPTZ '2026-07-30 19:20:00+00'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.metadata ->> 'reduced_lead_accepted' = 'true'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'RBLX authenticated readiness is not fresh';
    END IF;
END
$verify$;

ROLLBACK;
