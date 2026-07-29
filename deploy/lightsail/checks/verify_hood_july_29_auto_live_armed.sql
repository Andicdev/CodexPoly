-- Verify the armed HOOD schedule before activation without returning account,
-- market, order, or secret data.

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
        RAISE EXCEPTION 'HOOD armed check is only valid before activation';
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
    WHERE schedule.schedule_key = 'schedule:earnings-hood-2026q2'
      AND schedule.profile_key = 'earnings-hood-2026q2'
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
          '2026-07-29-hood-post-market'
      AND profile.account_name = 'abccbaq'
      AND profile.quantity = 100
      AND profile.yes_desired_price = 0.999
      AND profile.no_desired_price = 0.999;

    IF schedule_state IS NULL OR profile_state <> 'DISABLED' THEN
        RAISE EXCEPTION 'HOOD armed schedule or disabled profile is invalid';
    END IF;

    IF now() < TIMESTAMPTZ '2026-07-29 17:45:00+00' THEN
        IF schedule_state <> 'PENDING'
           OR readiness_checked IS NOT NULL
           OR readiness_until IS NOT NULL
        THEN
            RAISE EXCEPTION 'HOOD state is invalid before preflight';
        END IF;
    ELSE
        IF schedule_state <> 'READY'
           OR readiness_checked IS NULL
           OR readiness_until IS NULL
           OR readiness_until <=
               TIMESTAMPTZ '2026-07-29 18:00:00+00'
        THEN
            RAISE EXCEPTION 'HOOD authenticated readiness is not fresh';
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'hood-2026q2-gaap-eps-0pt43'
          AND scope_id = 'earnings:HOOD:2026Q2'
          AND status = 'SHADOW'
          AND source_policy ? 'sec'
          AND source_policy ? 'company_ir'
          AND source_policy ? 'press_wire'
    ) THEN
        RAISE EXCEPTION 'HOOD source rule is missing';
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
        WHERE scope_id = 'earnings:HOOD:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:HOOD:2026Q2'
    ) THEN
        RAISE EXCEPTION 'HOOD facts or claims already exist';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-hood-2026q2';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'HOOD armed notional is invalid';
    END IF;
END
$verification$;

ROLLBACK;
