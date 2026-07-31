-- Advance the six-profile July 31 batch after explicit user authorization.
-- The scheduler remains the only component that enables execution profiles.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    batch_notional numeric;
    enabled_notional numeric;
    activation_time timestamptz := clock_timestamp();
BEGIN
    IF activation_time < TIMESTAMPTZ '2026-07-31 08:30:00+00'
       OR activation_time >= TIMESTAMPTZ '2026-07-31 08:45:00+00'
    THEN
        RAISE EXCEPTION 'outside the explicitly authorized early activation window';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.schedule_key IN (
            'schedule:earnings-ben-2026q3',
            'schedule:earnings-cboe-2026q2',
            'schedule:earnings-cvx-2026q2',
            'schedule:earnings-cl-2026q2',
            'schedule:earnings-mrna-2026q2',
            'schedule:earnings-ares-2026q2'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'READY'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-31 08:45:00+00'
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until >
              TIMESTAMPTZ '2026-07-31 08:45:00+00'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.quantity = 100
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND rule.status = 'SHADOW'
    ) <> 6 THEN
        RAISE EXCEPTION 'reviewed July 31 batch is not ready for early activation';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id IN (
            'earnings:BEN:2026Q3',
            'earnings:CBOE:2026Q2',
            'earnings:CVX:2026Q2',
            'earnings:CL:2026Q2',
            'earnings:MRNA:2026Q2',
            'earnings:ARES:2026Q2'
        )
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:BEN:2026Q3',
            'earnings:CBOE:2026Q2',
            'earnings:CVX:2026Q2',
            'earnings:CL:2026Q2',
            'earnings:MRNA:2026Q2',
            'earnings:ARES:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'July 31 batch scopes already contain facts or claims';
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

    SELECT sum(quantity * greatest(yes_desired_price, no_desired_price))
    INTO batch_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-ben-2026q3',
        'earnings-cboe-2026q2',
        'earnings-cvx-2026q2',
        'earnings-cl-2026q2',
        'earnings-mrna-2026q2',
        'earnings-ares-2026q2'
    );
    IF batch_notional <> 599.4 THEN
        RAISE EXCEPTION 'July 31 batch reviewed notional is invalid';
    END IF;

    SELECT coalesce(
        sum(quantity * greatest(yes_desired_price, no_desired_price)),
        0
    )
    INTO enabled_notional
    FROM resolution_execution_profiles
    WHERE status = 'ENABLED';
    IF enabled_notional + batch_notional <> 699.3
       OR enabled_notional + batch_notional > 1000
    THEN
        RAISE EXCEPTION 'July 31 aggregate live notional is invalid';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        activate_at = activation_time,
        metadata = metadata || jsonb_build_object(
            'original_activate_at', '2026-07-31T08:45:00Z',
            'activation_advanced_at', activation_time,
            'activation_advanced_by',
                '046_activate_july_31_premarket_batch_now',
            'explicit_early_activation_authorization', true,
            'max_order_quantity_cap', 100,
            'per_order_notional_cap', 100,
            'aggregate_notional_cap', 1000
        ),
        updated_at = now()
    WHERE schedule_key IN (
        'schedule:earnings-ben-2026q3',
        'schedule:earnings-cboe-2026q2',
        'schedule:earnings-cvx-2026q2',
        'schedule:earnings-cl-2026q2',
        'schedule:earnings-mrna-2026q2',
        'schedule:earnings-ares-2026q2'
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
            'schedule:earnings-ben-2026q3',
            'schedule:earnings-cboe-2026q2',
            'schedule:earnings-cvx-2026q2',
            'schedule:earnings-cl-2026q2',
            'schedule:earnings-mrna-2026q2',
            'schedule:earnings-ares-2026q2'
        )
          AND schedule.state = 'READY'
          AND schedule.activate_at <= clock_timestamp()
          AND schedule.metadata
              ->> 'explicit_early_activation_authorization' = 'true'
          AND profile.status = 'DISABLED'
    ) <> 6 THEN
        RAISE EXCEPTION 'July 31 early activation request verification failed';
    END IF;
END
$verify$;

COMMIT;
