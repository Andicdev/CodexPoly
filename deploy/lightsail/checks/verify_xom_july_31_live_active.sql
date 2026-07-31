-- Read-only post-activation check for the XOM live profile.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-31 08:30:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-31 10:30:00+00'
    THEN
        RAISE EXCEPTION 'XOM active check is outside its valid interval';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key = 'schedule:earnings-xom-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND schedule.readiness_valid_until > now()
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'ENABLED'
          AND profile.scope_id = 'earnings:XOM:2026Q2'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM live profile is not active';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at >= now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'live resolution heartbeat is missing or stale';
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
        RAISE EXCEPTION 'XOM scope is not clean before the release';
    END IF;
END
$verify$;

ROLLBACK;
