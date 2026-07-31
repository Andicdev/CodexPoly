-- Read-only authenticated-preflight check for all seven July 31 profiles.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-31 08:30:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-31 08:45:00+00'
    THEN
        RAISE EXCEPTION 'July 31 seven-profile preflight check is outside its window';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key IN (
            'schedule:earnings-xom-2026q2',
            'schedule:earnings-ben-2026q3',
            'schedule:earnings-cboe-2026q2',
            'schedule:earnings-cvx-2026q2',
            'schedule:earnings-cl-2026q2',
            'schedule:earnings-mrna-2026q2',
            'schedule:earnings-ares-2026q2'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'READY'
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until > schedule.activate_at
          AND schedule.last_error_code IS NULL
          AND profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.quantity = 100
    ) <> 7 THEN
        RAISE EXCEPTION 'July 31 seven-profile authenticated readiness is invalid';
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
        WHERE scope_id IN (
            'earnings:XOM:2026Q2',
            'earnings:BEN:2026Q3',
            'earnings:CBOE:2026Q2',
            'earnings:CVX:2026Q2',
            'earnings:CL:2026Q2',
            'earnings:MRNA:2026Q2',
            'earnings:ARES:2026Q2'
        )
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:XOM:2026Q2',
            'earnings:BEN:2026Q3',
            'earnings:CBOE:2026Q2',
            'earnings:CVX:2026Q2',
            'earnings:CL:2026Q2',
            'earnings:MRNA:2026Q2',
            'earnings:ARES:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'July 31 seven-profile scopes already contain facts or claims';
    END IF;
END
$verify$;

ROLLBACK;
