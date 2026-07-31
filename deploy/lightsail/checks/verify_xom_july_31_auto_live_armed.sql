-- Read-only pre-activation check for the XOM AUTO_LIVE schedule.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    schedule_state text;
    profile_state text;
    readiness_checked timestamptz;
    readiness_until timestamptz;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-31 08:30:00+00' THEN
        RAISE EXCEPTION 'XOM armed check is only valid before activation';
    END IF;

    SELECT
        schedule.state,
        profile.status,
        schedule.readiness_checked_at,
        schedule.readiness_valid_until
    INTO
        schedule_state,
        profile_state,
        readiness_checked,
        readiness_until
    FROM resolution_profile_schedules AS schedule
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = schedule.profile_key
    WHERE schedule.schedule_key = 'schedule:earnings-xom-2026q2'
      AND schedule.profile_key = 'earnings-xom-2026q2'
      AND schedule.automation_mode = 'AUTO_LIVE'
      AND schedule.preflight_at =
          TIMESTAMPTZ '2026-07-31 08:15:00+00'
      AND schedule.activate_at =
          TIMESTAMPTZ '2026-07-31 08:30:00+00'
      AND schedule.earliest_signal_at =
          TIMESTAMPTZ '2026-07-31 10:30:00+00'
      AND schedule.activation_safety_lead_seconds = 7200
      AND schedule.timing_basis = 'OFFICIAL_EXACT'
      AND schedule.timing_contract_version = 1
      AND schedule.metadata ->> 'armed_for_live' = 'true'
      AND schedule.metadata ->> 'max_order_quantity_cap' = '100'
      AND schedule.metadata ->> 'per_order_notional_cap' = '100'
      AND schedule.metadata ->> 'aggregate_notional_cap' = '1000'
      AND profile.scope_id = 'earnings:XOM:2026Q2'
      AND profile.account_name = 'abccbaq'
      AND profile.quantity = 100;

    IF schedule_state IS NULL OR profile_state <> 'DISABLED' THEN
        RAISE EXCEPTION 'XOM armed schedule or disabled profile is invalid';
    END IF;

    IF now() < TIMESTAMPTZ '2026-07-31 08:15:00+00' THEN
        IF schedule_state <> 'PENDING'
           OR readiness_checked IS NOT NULL
           OR readiness_until IS NOT NULL
        THEN
            RAISE EXCEPTION 'XOM state is invalid before preflight';
        END IF;
    ELSE
        IF schedule_state <> 'READY'
           OR readiness_checked IS NULL
           OR readiness_until IS NULL
           OR readiness_until <=
               TIMESTAMPTZ '2026-07-31 08:30:00+00'
        THEN
            RAISE EXCEPTION 'XOM authenticated readiness is not fresh';
        END IF;
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
        RAISE EXCEPTION 'XOM scope already contains facts or claims';
    END IF;
END
$verify$;

ROLLBACK;
