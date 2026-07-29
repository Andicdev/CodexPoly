-- Fail closed without returning profile, account, market, or order data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    target_profiles constant text[] := ARRAY[
        'earnings-sofi-2026q2',
        'earnings-pg-2026q4',
        'earnings-hum-2026q2',
        'earnings-wing-2026q2',
        'earnings-arcc-2026q2',
        'earnings-iart-2026q2',
        'earnings-grmn-2026q2',
        'earnings-cbre-2026q2',
        'earnings-pag-2026q2'
    ];
    target_scopes constant text[] := ARRAY[
        'earnings:SOFI:2026Q2',
        'earnings:PG:2026Q4',
        'earnings:HUM:2026Q2',
        'earnings:WING:2026Q2',
        'earnings:ARCC:2026Q2',
        'earnings:IART:2026Q2',
        'earnings:GRMN:2026Q2',
        'earnings:CBRE:2026Q2',
        'earnings:PAG:2026Q2'
    ];
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key = ANY(target_profiles)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'PENDING'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-29 08:45:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-29 09:00:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-29 17:00:00+00'
          AND schedule.preflight_request_id IS NULL
          AND schedule.preflight_requested_at IS NULL
          AND schedule.readiness_checked_at IS NULL
          AND schedule.readiness_valid_until IS NULL
          AND schedule.metadata ->> 'live_block' = 'PRE_MARKET'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-pre-market'
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND rule.status = 'SHADOW'
    ) <> 9 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET AUTO_LIVE set is not safely armed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules
        WHERE metadata ->> 'block_id' = '2026-07-29-pre-market'
          AND profile_key <> ALL(target_profiles)
    ) THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET block contains an unreviewed profile';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = ANY(target_scopes)
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ANY(target_scopes)
    ) THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET facts or claims already exist';
    END IF;

    SELECT sum(
        quantity * greatest(
            yes_desired_price,
            no_desired_price
        )
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = ANY(target_profiles);

    IF reviewed_notional <> 899.1 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET reviewed notional is invalid';
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
        RAISE EXCEPTION
            'fresh fully-live resolution heartbeat is missing';
    END IF;
END
$verification$;

ROLLBACK;
