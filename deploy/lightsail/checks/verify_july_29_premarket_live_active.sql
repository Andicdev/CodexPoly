-- Verify the complete July 29 PRE_MARKET live activation without returning
-- profile, account, market, readiness, or order data.

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
    active_notional numeric;
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-29 09:00:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-29 17:00:00+00' THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET active check is outside its window';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ANY(target_profiles)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until > schedule.activate_at
          AND jsonb_typeof(schedule.readiness_evidence) = 'object'
          AND schedule.readiness_evidence <> '{}'::jsonb
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-pre-market'
          AND profile.status = 'ENABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.quantity = 100
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
    ) <> 9 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET live activation is incomplete';
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
    INTO active_notional
    FROM resolution_execution_profiles
    WHERE profile_key = ANY(target_profiles)
      AND status = 'ENABLED';

    IF active_notional <> 899.1 OR active_notional > 1000 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET active notional is invalid';
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
