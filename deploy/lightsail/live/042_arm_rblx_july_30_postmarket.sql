-- Arm only RBLX for its reviewed July 30 POST_MARKET window.
-- This very late activation requires explicit reduced-lead acceptance.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    schedule_state text;
    readiness_until timestamptz;
    reviewed_notional numeric;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 19:20:00+00' THEN
        RAISE EXCEPTION 'RBLX live arming deadline has passed';
    END IF;

    SELECT state, readiness_valid_until
    INTO schedule_state, readiness_until
    FROM resolution_profile_schedules
    WHERE schedule_key = 'schedule:earnings-rblx-2026q2'
      AND profile_key = 'earnings-rblx-2026q2'
      AND automation_mode = 'AUTO_PREFLIGHT'
      AND state IN ('PENDING', 'READY')
      AND preflight_at = TIMESTAMPTZ '2026-07-30 19:15:00+00'
      AND activate_at = TIMESTAMPTZ '2026-07-30 19:20:00+00'
      AND deactivate_at = TIMESTAMPTZ '2026-07-31 02:00:00+00'
      AND earliest_signal_at = TIMESTAMPTZ '2026-07-30 20:00:00+00'
      AND activation_safety_lead_seconds = 2400
      AND timing_basis = 'HISTORICAL_PATTERN'
      AND timing_contract_version = 1
      AND metadata ->> 'block_id' =
          '2026-07-30-rblx-post-market'
      AND metadata ->> 'late_preparation' = 'true'
      AND metadata ->> 'operator_acceptance_required' = 'true'
      AND coalesce(
          (metadata ->> 'temporarily_paused')::boolean,
          false
      ) = false
      AND last_error_code IS NULL
    FOR UPDATE;

    IF schedule_state IS NULL THEN
        RAISE EXCEPTION 'RBLX reviewed schedule is missing';
    END IF;
    IF now() >= TIMESTAMPTZ '2026-07-30 19:15:00+00'
       AND (
           schedule_state <> 'READY'
           OR readiness_until IS NULL
           OR readiness_until <= TIMESTAMPTZ '2026-07-30 19:20:00+00'
       )
    THEN
        RAISE EXCEPTION 'RBLX authenticated readiness is not fresh';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE profile.profile_key = 'earnings-rblx-2026q2'
          AND profile.scope_id = 'earnings:RBLX:2026Q2'
          AND profile.account_name = 'abccbaq'
          AND profile.condition_id =
              '0xa12716116eb129272d80f3b85a565f3ed7efe845bb29f46546187a90b986a7b9'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND profile.lifecycle_kind = 'reprice_on_tick_change'
          AND profile.old_tick = 0.01
          AND profile.new_tick = 0.001
          AND profile.max_reprices = 1
          AND profile.status = 'DISABLED'
          AND rule.rule_key = 'rblx-2026q2-gaap-eps-neg0pt33'
          AND rule.status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'reviewed RBLX disabled profile is invalid';
    END IF;

    IF EXISTS (
        SELECT 1 FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RBLX:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RBLX:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RBLX scope already contains facts or claims';
    END IF;
    IF EXISTS (
        SELECT 1 FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0xa12716116eb129272d80f3b85a565f3ed7efe845bb29f46546187a90b986a7b9'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'RBLX market has an active order group';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM resolution_runtime_heartbeats
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
    WHERE profile_key = 'earnings-rblx-2026q2';
    IF reviewed_notional <> 99.9
       OR reviewed_notional > 100
       OR reviewed_notional > 1000
    THEN
        RAISE EXCEPTION 'RBLX reviewed notional is invalid';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        automation_mode = 'AUTO_LIVE',
        metadata = metadata || jsonb_build_object(
            'armed_for_live', true,
            'operator_acceptance_required', false,
            'reduced_lead_accepted', true,
            'armed_by', '042_arm_rblx_july_30_postmarket',
            'max_order_quantity_cap', 100,
            'per_order_notional_cap', 100,
            'aggregate_notional_cap', 1000
        ),
        updated_at = now()
    WHERE schedule_key = 'schedule:earnings-rblx-2026q2';
END
$guard$;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key =
              'schedule:earnings-rblx-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.metadata ->> 'reduced_lead_accepted' = 'true'
          AND schedule.metadata ->> 'max_order_quantity_cap' = '100'
          AND schedule.metadata ->> 'per_order_notional_cap' = '100'
          AND schedule.metadata ->> 'aggregate_notional_cap' = '1000'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'RBLX live arming verification failed';
    END IF;
END
$verify$;

COMMIT;
