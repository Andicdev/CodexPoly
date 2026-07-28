BEGIN;

DO $guard$
DECLARE
    target_profiles constant text[] := ARRAY[
        'earnings-csgp-2026q2',
        'earnings-czr-2026q2',
        'earnings-f-2026q2',
        'earnings-nxpi-2026q2',
        'earnings-v-2026q3'
    ];
    target_scopes constant text[] := ARRAY[
        'earnings:CSGP:2026Q2',
        'earnings:CZR:2026Q2',
        'earnings:F:2026Q2',
        'earnings:NXPI:2026Q2',
        'earnings:V:2026Q3'
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
          AND schedule.automation_mode = 'MANUAL'
          AND schedule.state = 'PENDING'
          AND schedule.metadata ->> 'live_block' = 'POST_MARKET'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-28-post-market'
          AND profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 50
          AND profile.lifecycle_kind = 'reprice_on_tick_change'
          AND profile.old_tick = 0.01
          AND profile.new_tick = 0.001
          AND profile.max_reprices = 1
          AND rule.status = 'SHADOW'
    ) <> 5 THEN
        RAISE EXCEPTION
            'POST_MARKET profiles do not match the reviewed disabled set';
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
            'POST_MARKET block already contains facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.metadata ->> 'live_block' = 'PRE_MARKET'
          AND (
              schedule.state <> 'EXPIRED'
              OR schedule.automation_mode <> 'MANUAL'
              OR profile.status <> 'DISABLED'
          )
    ) THEN
        RAISE EXCEPTION 'PRE_MARKET block is not fully closed';
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

    UPDATE resolution_execution_profiles
    SET
        quantity = 100,
        metadata = metadata || jsonb_build_object(
            'profile_template_key', 'default',
            'quantity_policy', '100_shares',
            'live_block', 'POST_MARKET',
            'block_id', '2026-07-28-post-market'
        ),
        updated_at = now()
    WHERE profile_key = ANY(target_profiles)
      AND status = 'DISABLED';

    SELECT sum(
        quantity * greatest(
            yes_desired_price,
            no_desired_price
        )
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = ANY(target_profiles);

    IF reviewed_notional > 1000 OR reviewed_notional <> 499.5 THEN
        RAISE EXCEPTION
            'POST_MARKET aggregate notional is invalid: %',
            reviewed_notional;
    END IF;

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
            '015_arm_july_28_postmarket_live_block'
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
            'earnings-csgp-2026q2',
            'earnings-czr-2026q2',
            'earnings-f-2026q2',
            'earnings-nxpi-2026q2',
            'earnings-v-2026q3'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'PENDING'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
    ) <> 5 THEN
        RAISE EXCEPTION
            'POST_MARKET block arming verification failed';
    END IF;
END
$verify$;

COMMIT;
