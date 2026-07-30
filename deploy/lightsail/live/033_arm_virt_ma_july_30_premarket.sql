-- Arm only VIRT and MA for their reviewed July 30 PRE_MARKET windows.
-- Authenticated preflight and profile activation remain scheduler-owned.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    virt_state text;
    virt_readiness_until timestamptz;
    ma_state text;
    ma_readiness_until timestamptz;
    reviewed_notional numeric;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 10:30:00+00' THEN
        RAISE EXCEPTION 'VIRT live arming deadline has passed';
    END IF;

    IF now() >= TIMESTAMPTZ '2026-07-30 11:00:00+00' THEN
        RAISE EXCEPTION 'MA live arming deadline has passed';
    END IF;

    SELECT state, readiness_valid_until
    INTO virt_state, virt_readiness_until
    FROM resolution_profile_schedules
    WHERE schedule_key = 'schedule:earnings-virt-2026q2'
      AND profile_key = 'earnings-virt-2026q2'
      AND automation_mode = 'AUTO_PREFLIGHT'
      AND state IN ('PENDING', 'READY')
      AND preflight_at = TIMESTAMPTZ '2026-07-30 10:00:00+00'
      AND activate_at = TIMESTAMPTZ '2026-07-30 10:30:00+00'
      AND deactivate_at = TIMESTAMPTZ '2026-07-30 13:30:00+00'
      AND metadata ->> 'block_id' =
          '2026-07-30-virt-pre-market'
      AND coalesce(
          (metadata ->> 'temporarily_paused')::boolean,
          false
      ) = false
      AND last_error_code IS NULL
    FOR UPDATE;

    IF virt_state IS NULL THEN
        RAISE EXCEPTION 'VIRT reviewed schedule is missing';
    END IF;

    SELECT state, readiness_valid_until
    INTO ma_state, ma_readiness_until
    FROM resolution_profile_schedules
    WHERE schedule_key = 'schedule:earnings-ma-2026q2'
      AND profile_key = 'earnings-ma-2026q2'
      AND automation_mode = 'AUTO_PREFLIGHT'
      AND state IN ('PENDING', 'READY')
      AND preflight_at = TIMESTAMPTZ '2026-07-30 10:30:00+00'
      AND activate_at = TIMESTAMPTZ '2026-07-30 11:00:00+00'
      AND deactivate_at = TIMESTAMPTZ '2026-07-30 14:30:00+00'
      AND metadata ->> 'block_id' = '2026-07-30-ma-pre-market'
      AND coalesce(
          (metadata ->> 'temporarily_paused')::boolean,
          false
      ) = false
      AND last_error_code IS NULL
    FOR UPDATE;

    IF ma_state IS NULL THEN
        RAISE EXCEPTION 'MA reviewed schedule is missing';
    END IF;

    IF now() >= TIMESTAMPTZ '2026-07-30 10:00:00+00'
       AND (
           virt_state <> 'READY'
           OR virt_readiness_until IS NULL
           OR virt_readiness_until <=
               TIMESTAMPTZ '2026-07-30 10:30:00+00'
       )
    THEN
        RAISE EXCEPTION 'VIRT authenticated readiness is not fresh';
    END IF;

    IF now() >= TIMESTAMPTZ '2026-07-30 10:30:00+00'
       AND (
           ma_state <> 'READY'
           OR ma_readiness_until IS NULL
           OR ma_readiness_until <=
               TIMESTAMPTZ '2026-07-30 11:00:00+00'
       )
    THEN
        RAISE EXCEPTION 'MA authenticated readiness is not fresh';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE (
            (
                profile.profile_key = 'earnings-virt-2026q2'
                AND profile.scope_id = 'earnings:VIRT:2026Q2'
                AND profile.condition_id =
                    '0xe51d31ccfbad36c133152ce07533e5baee5db4bf2b02f76df7192fce363ac770'
                AND rule.rule_key =
                    'virt-2026q2-nongaap-eps-1pt82'
            ) OR (
                profile.profile_key = 'earnings-ma-2026q2'
                AND profile.scope_id = 'earnings:MA:2026Q2'
                AND profile.condition_id =
                    '0x9aa5ff923c2669e27ce9be9631deb17719afd08d877237e9bf24d853b75893a1'
                AND rule.rule_key = 'ma-2026q2-nongaap-eps-4pt77'
            )
        )
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND profile.lifecycle_kind = 'reprice_on_tick_change'
          AND profile.old_tick = 0.01
          AND profile.new_tick = 0.001
          AND profile.max_reprices = 1
          AND profile.status = 'DISABLED'
          AND rule.status = 'SHADOW'
    ) <> 2 THEN
        RAISE EXCEPTION 'reviewed VIRT/MA disabled profiles are invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id IN (
            'earnings:VIRT:2026Q2',
            'earnings:MA:2026Q2'
        )
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:VIRT:2026Q2',
            'earnings:MA:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'VIRT/MA scopes already contain facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id IN (
              '0xe51d31ccfbad36c133152ce07533e5baee5db4bf2b02f76df7192fce363ac770',
              '0x9aa5ff923c2669e27ce9be9631deb17719afd08d877237e9bf24d853b75893a1'
          )
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'VIRT/MA market has an active order group';
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

    SELECT sum(
        quantity * greatest(yes_desired_price, no_desired_price)
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-virt-2026q2',
        'earnings-ma-2026q2'
    );

    IF reviewed_notional <> 199.8 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'VIRT/MA reviewed notional is invalid';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        automation_mode = 'AUTO_LIVE',
        metadata = metadata || jsonb_build_object(
            'armed_for_live', true,
            'armed_by', '033_arm_virt_ma_july_30_premarket',
            'aggregate_notional_cap', 1000
        ),
        updated_at = now()
    WHERE schedule_key IN (
        'schedule:earnings-virt-2026q2',
        'schedule:earnings-ma-2026q2'
    );
END
$guard$;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key IN (
            'schedule:earnings-virt-2026q2',
            'schedule:earnings-ma-2026q2'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 2 THEN
        RAISE EXCEPTION 'VIRT/MA live arming verification failed';
    END IF;
END
$verify$;

COMMIT;
