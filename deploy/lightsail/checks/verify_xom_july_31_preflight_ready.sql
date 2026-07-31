-- Read-only authenticated-readiness check for XOM before activation.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-31 08:15:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-31 08:30:00+00'
    THEN
        RAISE EXCEPTION 'XOM readiness check is outside its valid interval';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key = 'schedule:earnings-xom-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'READY'
          AND schedule.preflight_request_id IS NOT NULL
          AND schedule.preflight_requested_at IS NOT NULL
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until >
              TIMESTAMPTZ '2026-07-31 08:30:00+00'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM authenticated preflight is not ready';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:XOM:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:XOM:2026Q2'
    ) THEN
        RAISE EXCEPTION 'XOM scope is not clean before activation';
    END IF;
END
$verify$;

ROLLBACK;
