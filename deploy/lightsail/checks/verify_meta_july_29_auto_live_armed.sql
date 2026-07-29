-- Verify the armed META schedule before its activation boundary without
-- returning account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    schedule_state text;
    profile_state text;
    readiness_checked timestamptz;
    readiness_until timestamptz;
    reviewed_notional numeric;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-29 18:00:00+00' THEN
        RAISE EXCEPTION 'META armed check is only valid before activation';
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
    WHERE schedule.schedule_key = 'schedule:earnings-meta-2026q2'
      AND schedule.profile_key = 'earnings-meta-2026q2'
      AND schedule.automation_mode = 'AUTO_LIVE'
      AND schedule.preflight_at =
          TIMESTAMPTZ '2026-07-29 17:45:00+00'
      AND schedule.activate_at =
          TIMESTAMPTZ '2026-07-29 18:00:00+00'
      AND schedule.deactivate_at =
          TIMESTAMPTZ '2026-07-30 02:00:00+00'
      AND schedule.last_error_code IS NULL
      AND schedule.metadata ->> 'armed_for_live' = 'true'
      AND schedule.metadata ->> 'block_id' =
          '2026-07-29-meta-post-market'
      AND profile.account_name = 'abccbaq'
      AND profile.quantity = 100
      AND profile.yes_desired_price = 0.999
      AND profile.no_desired_price = 0.999;

    IF schedule_state IS NULL OR profile_state <> 'DISABLED' THEN
        RAISE EXCEPTION 'META armed schedule or disabled profile is invalid';
    END IF;

    IF now() < TIMESTAMPTZ '2026-07-29 17:45:00+00' THEN
        IF schedule_state <> 'PENDING'
           OR readiness_checked IS NOT NULL
           OR readiness_until IS NOT NULL
        THEN
            RAISE EXCEPTION 'META state is invalid before preflight';
        END IF;
    ELSE
        IF schedule_state <> 'READY'
           OR readiness_checked IS NULL
           OR readiness_until IS NULL
           OR readiness_until <=
               TIMESTAMPTZ '2026-07-29 18:00:00+00'
        THEN
            RAISE EXCEPTION 'META authenticated readiness is not fresh';
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'meta-2026q2-gaap-eps-7pt20'
          AND scope_id = 'earnings:META:2026Q2'
          AND status = 'SHADOW'
          AND source_policy ? 'sec'
          AND source_policy ? 'company_ir'
          AND source_policy ? 'press_wire'
    ) THEN
        RAISE EXCEPTION 'META source rule is missing';
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
        WHERE scope_id = 'earnings:META:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:META:2026Q2'
    ) THEN
        RAISE EXCEPTION 'META facts or claims already exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x5b725d76638a67ec53ced1221dd6140ff0b419edb72a1653ba4aa82551601704'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'META active order group already exists';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-meta-2026q2';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'META armed notional is invalid';
    END IF;
END
$verification$;

ROLLBACK;
