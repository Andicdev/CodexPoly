-- Read-only verification after the MA early-window correction.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key = 'schedule:earnings-ma-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.activate_at - schedule.preflight_at =
              interval '3 minutes'
          AND (
              schedule.metadata ->> 'earliest_signal_at'
          )::timestamptz - schedule.activate_at =
              interval '5 minutes'
          AND schedule.metadata ->> 'timing_recovered_by' =
              '036_recover_ma_early_preflight'
          AND schedule.state IN ('PREFLIGHTING', 'READY', 'ACTIVE')
          AND (
              (
                  schedule.state IN ('PREFLIGHTING', 'READY')
                  AND profile.status = 'DISABLED'
              ) OR (
                  schedule.state = 'ACTIVE'
                  AND profile.status = 'ENABLED'
              )
          )
          AND profile.quantity = 100
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
    ) <> 1 THEN
        RAISE EXCEPTION 'MA early-window lifecycle mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:MA:2026Q2'
    ) THEN
        RAISE EXCEPTION 'MA execution claim already exists';
    END IF;
END
$verification$;

ROLLBACK;
