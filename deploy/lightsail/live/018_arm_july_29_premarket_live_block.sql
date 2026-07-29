-- Arm only the reviewed July 29 PRE_MARKET block. The scheduler will request
-- authenticated preflight at 08:45 UTC and may activate profiles at 09:00 UTC
-- only after fresh readiness evidence exists. This migration never enables an
-- execution profile directly.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
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
    IF now() >= TIMESTAMPTZ '2026-07-29 08:45:00+00' THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET arming deadline has passed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key = ANY(target_profiles)
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'PENDING'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-29 08:45:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-29 09:00:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-29 17:00:00+00'
          AND schedule.metadata ->> 'live_block' = 'PRE_MARKET'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-pre-market'
          AND profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND profile.lifecycle_kind = 'reprice_on_tick_change'
          AND profile.old_tick = 0.01
          AND profile.new_tick = 0.001
          AND profile.max_reprices = 1
          AND profile.prepare_from =
              TIMESTAMPTZ '2026-07-29 09:00:00+00'
          AND profile.expires_at =
              TIMESTAMPTZ '2026-07-29 17:00:00+00'
          AND rule.status = 'SHADOW'
    ) <> 9 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET profiles do not match reviewed disabled set';
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
            'July 29 PRE_MARKET block already contains facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.account_name = order_group.account_name
         AND profile.condition_id = order_group.condition_id
        WHERE profile.profile_key = ANY(target_profiles)
          AND order_group.status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET block has an active order group';
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
            'live resolution heartbeat is missing or stale';
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

    IF reviewed_notional > 1000 OR reviewed_notional <> 899.1 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET aggregate notional is invalid: %',
            reviewed_notional;
    END IF;

    UPDATE resolution_execution_profiles
    SET
        metadata = metadata || jsonb_build_object(
            'profile_template_key', 'default',
            'quantity_policy', '100_shares',
            'live_block', 'PRE_MARKET',
            'block_id', '2026-07-29-pre-market'
        ),
        updated_at = now()
    WHERE profile_key = ANY(target_profiles)
      AND status = 'DISABLED';

    UPDATE resolution_profile_schedules
    SET
        automation_mode = 'AUTO_LIVE',
        state = 'PENDING',
        preflight_request_id = NULL,
        preflight_requested_at = NULL,
        preflight_lease_until = NULL,
        readiness_checked_at = NULL,
        readiness_valid_until = NULL,
        readiness_evidence = '{}'::jsonb,
        last_error_code = NULL,
        metadata = metadata || jsonb_build_object(
            'temporarily_paused', false,
            'armed_for_live', true,
            'quantity_policy', '100_shares',
            'aggregate_notional_cap', 1000,
            'armed_by',
            '018_arm_july_29_premarket_live_block'
        ),
        updated_at = now()
    WHERE profile_key = ANY(target_profiles);
END
$guard$;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key IN (
            'earnings-sofi-2026q2',
            'earnings-pg-2026q4',
            'earnings-hum-2026q2',
            'earnings-wing-2026q2',
            'earnings-arcc-2026q2',
            'earnings-iart-2026q2',
            'earnings-grmn-2026q2',
            'earnings-cbre-2026q2',
            'earnings-pag-2026q2'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'PENDING'
          AND schedule.preflight_request_id IS NULL
          AND schedule.readiness_valid_until IS NULL
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
    ) <> 9 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET block arming verification failed';
    END IF;
END
$verify$;

COMMIT;
