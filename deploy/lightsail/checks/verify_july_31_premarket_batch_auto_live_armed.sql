-- Read-only pre-activation check for the six-profile July 31 batch.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    schedule_count integer;
    ready_count integer;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-31 08:45:00+00' THEN
        RAISE EXCEPTION 'July 31 batch armed check is only valid before activation';
    END IF;

    SELECT count(*)
    INTO schedule_count
    FROM resolution_profile_schedules AS schedule
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = schedule.profile_key
    WHERE schedule.schedule_key IN (
        'schedule:earnings-ben-2026q3',
        'schedule:earnings-cboe-2026q2',
        'schedule:earnings-cvx-2026q2',
        'schedule:earnings-cl-2026q2',
        'schedule:earnings-mrna-2026q2',
        'schedule:earnings-ares-2026q2'
    )
      AND schedule.automation_mode = 'AUTO_LIVE'
      AND schedule.preflight_at =
          TIMESTAMPTZ '2026-07-31 08:30:00+00'
      AND schedule.activate_at =
          TIMESTAMPTZ '2026-07-31 08:45:00+00'
      AND schedule.metadata ->> 'block_id' = '2026-07-31-pre-market'
      AND schedule.metadata ->> 'armed_for_live' = 'true'
      AND schedule.metadata ->> 'aggregate_notional_cap' = '1000'
      AND profile.status = 'DISABLED'
      AND profile.account_name = 'abccbaq'
      AND profile.quantity = 100;

    IF schedule_count <> 6 THEN
        RAISE EXCEPTION 'July 31 batch armed schedules are invalid';
    END IF;

    IF now() < TIMESTAMPTZ '2026-07-31 08:30:00+00' THEN
        SELECT count(*)
        INTO ready_count
        FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-ben-2026q3',
            'schedule:earnings-cboe-2026q2',
            'schedule:earnings-cvx-2026q2',
            'schedule:earnings-cl-2026q2',
            'schedule:earnings-mrna-2026q2',
            'schedule:earnings-ares-2026q2'
        )
          AND state = 'PENDING'
          AND readiness_checked_at IS NULL
          AND readiness_valid_until IS NULL;
    ELSE
        SELECT count(*)
        INTO ready_count
        FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-ben-2026q3',
            'schedule:earnings-cboe-2026q2',
            'schedule:earnings-cvx-2026q2',
            'schedule:earnings-cl-2026q2',
            'schedule:earnings-mrna-2026q2',
            'schedule:earnings-ares-2026q2'
        )
          AND state = 'READY'
          AND readiness_checked_at IS NOT NULL
          AND readiness_valid_until >
              TIMESTAMPTZ '2026-07-31 08:45:00+00';
    END IF;

    IF ready_count <> 6 THEN
        RAISE EXCEPTION 'July 31 batch readiness state is invalid';
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
            'earnings:BEN:2026Q3',
            'earnings:CBOE:2026Q2',
            'earnings:CVX:2026Q2',
            'earnings:CL:2026Q2',
            'earnings:MRNA:2026Q2',
            'earnings:ARES:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'July 31 batch scopes already contain facts or claims';
    END IF;
END
$verify$;

ROLLBACK;
