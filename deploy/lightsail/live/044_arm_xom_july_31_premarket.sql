-- Arm only XOM for its reviewed July 31 PRE_MARKET release window.
-- Authenticated preflight and profile activation remain scheduler-owned.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    schedule_state text;
    readiness_until timestamptz;
    reviewed_notional numeric;
    approved_order_quantity_cap numeric := 100;
    approved_per_order_notional_cap numeric := 100;
    approved_aggregate_notional_cap numeric := 1000;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-31 08:30:00+00' THEN
        RAISE EXCEPTION 'XOM live arming deadline has passed';
    END IF;

    SELECT state, readiness_valid_until
    INTO schedule_state, readiness_until
    FROM resolution_profile_schedules
    WHERE schedule_key = 'schedule:earnings-xom-2026q2'
      AND profile_key = 'earnings-xom-2026q2'
      AND automation_mode = 'AUTO_PREFLIGHT'
      AND state IN ('PENDING', 'READY')
      AND preflight_at = TIMESTAMPTZ '2026-07-31 08:15:00+00'
      AND activate_at = TIMESTAMPTZ '2026-07-31 08:30:00+00'
      AND deactivate_at = TIMESTAMPTZ '2026-07-31 14:00:00+00'
      AND earliest_signal_at =
          TIMESTAMPTZ '2026-07-31 10:30:00+00'
      AND activation_safety_lead_seconds = 7200
      AND timing_basis = 'OFFICIAL_EXACT'
      AND timing_contract_version = 1
      AND metadata ->> 'block_id' = '2026-07-31-pre-market'
      AND coalesce(
          (metadata ->> 'temporarily_paused')::boolean,
          false
      ) = false
      AND last_error_code IS NULL
    FOR UPDATE;

    IF schedule_state IS NULL THEN
        RAISE EXCEPTION 'XOM reviewed schedule is missing';
    END IF;

    IF now() >= TIMESTAMPTZ '2026-07-31 08:15:00+00'
       AND (
           schedule_state <> 'READY'
           OR readiness_until IS NULL
           OR readiness_until <=
               TIMESTAMPTZ '2026-07-31 08:30:00+00'
       )
    THEN
        RAISE EXCEPTION 'XOM authenticated readiness is not fresh';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE profile.profile_key = 'earnings-xom-2026q2'
          AND profile.scope_id = 'earnings:XOM:2026Q2'
          AND profile.account_name = 'abccbaq'
          AND profile.condition_id =
              '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND profile.lifecycle_kind = 'reprice_on_tick_change'
          AND profile.old_tick = 0.01
          AND profile.new_tick = 0.001
          AND profile.max_reprices = 1
          AND profile.status = 'DISABLED'
          AND rule.rule_key = 'xom-2026q2-nongaap-eps-3pt66'
          AND rule.cik = '2115436'
          AND rule.metric_kind = 'non_gaap_eps'
          AND rule.comparison_op = '>'
          AND rule.strike = 3.66
          AND rule.status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'reviewed XOM disabled profile is invalid';
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

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'XOM market has an active order group';
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

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-xom-2026q2';

    IF reviewed_notional <> 99.9
       OR reviewed_notional > approved_per_order_notional_cap
       OR 100 > approved_order_quantity_cap
       OR reviewed_notional > approved_aggregate_notional_cap
    THEN
        RAISE EXCEPTION 'XOM reviewed notional is invalid';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        automation_mode = 'AUTO_LIVE',
        metadata = metadata || jsonb_build_object(
            'armed_for_live', true,
            'armed_by', '044_arm_xom_july_31_premarket',
            'max_order_quantity_cap', approved_order_quantity_cap,
            'per_order_notional_cap', approved_per_order_notional_cap,
            'aggregate_notional_cap', approved_aggregate_notional_cap
        ),
        updated_at = now()
    WHERE schedule_key = 'schedule:earnings-xom-2026q2';
END
$guard$;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key = 'schedule:earnings-xom-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.timing_contract_version = 1
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.metadata ->> 'max_order_quantity_cap' = '100'
          AND schedule.metadata ->> 'per_order_notional_cap' = '100'
          AND schedule.metadata ->> 'aggregate_notional_cap' = '1000'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM live arming verification failed';
    END IF;
END
$verify$;

COMMIT;
