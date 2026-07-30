-- Fail closed without returning account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
DECLARE
    five_profile_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.schedule_key IN (
            'schedule:earnings-yum-2026q2',
            'schedule:earnings-ice-2026q2',
            'schedule:earnings-ci-2026q2'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-30 09:45:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-30 10:00:00+00'
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.metadata ->> 'aggregate_notional_cap' = '1000'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND profile.status = 'DISABLED'
          AND rule.status = 'SHADOW'
    ) <> 3 THEN
        RAISE EXCEPTION 'YUM/ICE/CI AUTO_LIVE arming mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id IN (
            'earnings:YUM:2026Q2',
            'earnings:ICE:2026Q2',
            'earnings:CI:2026Q2'
        )
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:YUM:2026Q2',
            'earnings:ICE:2026Q2',
            'earnings:CI:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'YUM/ICE/CI facts or claims already exist';
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
    INTO five_profile_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-virt-2026q2',
        'earnings-ma-2026q2',
        'earnings-yum-2026q2',
        'earnings-ice-2026q2',
        'earnings-ci-2026q2'
    );

    IF five_profile_notional <> 499.5
       OR five_profile_notional > 1000
    THEN
        RAISE EXCEPTION 'five-profile aggregate notional is invalid';
    END IF;
END
$verification$;

ROLLBACK;
