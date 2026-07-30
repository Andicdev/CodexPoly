BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-30 18:30:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-30 18:45:00+00'
    THEN
        RAISE EXCEPTION 'RIVN readiness check is outside its valid interval';
    END IF;
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key =
              'schedule:earnings-rivn-2026q2'
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'READY'
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until >
              TIMESTAMPTZ '2026-07-30 18:45:00+00'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'armed_for_live' = 'false'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN authenticated readiness is not fresh';
    END IF;
    IF EXISTS (
        SELECT 1 FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RIVN:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RIVN:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RIVN has unexpected facts or claims';
    END IF;
END
$verify$;

ROLLBACK;
