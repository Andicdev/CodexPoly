-- Arm only WAY for the July 29 POST_MARKET window. This migration never
-- enables the execution profile directly.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    schedule_state text;
    readiness_until timestamptz;
    reviewed_notional numeric;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-29 19:45:00+00' THEN
        RAISE EXCEPTION 'WAY live arming deadline has passed';
    END IF;

    SELECT state, readiness_valid_until
    INTO schedule_state, readiness_until
    FROM resolution_profile_schedules
    WHERE schedule_key = 'schedule:earnings-way-2026q2'
      AND profile_key = 'earnings-way-2026q2'
      AND automation_mode = 'AUTO_PREFLIGHT'
      AND state IN ('PENDING', 'READY')
      AND preflight_at = TIMESTAMPTZ '2026-07-29 19:20:00+00'
      AND activate_at = TIMESTAMPTZ '2026-07-29 19:45:00+00'
      AND deactivate_at = TIMESTAMPTZ '2026-07-30 02:00:00+00'
      AND metadata ->> 'block_id' =
          '2026-07-29-way-post-market';

    IF schedule_state IS NULL THEN
        RAISE EXCEPTION 'WAY reviewed schedule is missing';
    END IF;

    IF now() >= TIMESTAMPTZ '2026-07-29 19:20:00+00'
       AND (
           schedule_state <> 'READY'
           OR readiness_until IS NULL
           OR readiness_until <=
               TIMESTAMPTZ '2026-07-29 19:45:00+00'
       )
    THEN
        RAISE EXCEPTION 'WAY authenticated readiness is not fresh';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE profile.profile_key = 'earnings-way-2026q2'
          AND profile.scope_id = 'earnings:WAY:2026Q2'
          AND profile.account_name = 'abccbaq'
          AND profile.condition_id =
              '0xaf07f668593362c55d734ec94a80b415bc12015b92cb03c4b8c5e571e018da2e'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND profile.lifecycle_kind = 'reprice_on_tick_change'
          AND profile.old_tick = 0.01
          AND profile.new_tick = 0.001
          AND profile.max_reprices = 1
          AND profile.status = 'DISABLED'
          AND rule.rule_key =
              'way-2026q2-nongaap-eps-0pt40'
          AND rule.status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'WAY reviewed disabled profile is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:WAY:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:WAY:2026Q2'
    ) THEN
        RAISE EXCEPTION 'WAY scope already contains facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0xaf07f668593362c55d734ec94a80b415bc12015b92cb03c4b8c5e571e018da2e'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'WAY market has an active order group';
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
    WHERE profile_key = 'earnings-way-2026q2';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'WAY reviewed notional is invalid';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        automation_mode = 'AUTO_LIVE',
        metadata = metadata || jsonb_build_object(
            'armed_for_live', true,
            'armed_by', '030_arm_way_july_29_postmarket'
        ),
        updated_at = now()
    WHERE schedule_key = 'schedule:earnings-way-2026q2';
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
              'schedule:earnings-way-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'WAY live arming verification failed';
    END IF;
END
$verify$;

COMMIT;
