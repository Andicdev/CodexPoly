-- Read-only check for RDDT after scheduler-owned activation and before signal.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-30 18:08:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-30 20:08:00+00'
    THEN
        RAISE EXCEPTION 'RDDT active check is outside its valid interval';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key = 'schedule:earnings-rddt-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-30 18:08:00+00'
          AND schedule.earliest_signal_at =
              TIMESTAMPTZ '2026-07-30 20:08:00+00'
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.metadata ->> 'max_order_quantity_cap' = '100'
          AND schedule.metadata ->> 'per_order_notional_cap' = '100'
          AND schedule.metadata ->> 'aggregate_notional_cap' = '1000'
          AND profile.profile_key = 'earnings-rddt-2026q2'
          AND profile.scope_id = 'earnings:RDDT:2026Q2'
          AND profile.account_name = 'abccbaq'
          AND profile.status = 'ENABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'RDDT active schedule or enabled profile is invalid';
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
        WHERE scope_id = 'earnings:RDDT:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RDDT:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RDDT scope already contains facts or claims';
    END IF;
END
$verify$;

ROLLBACK;
