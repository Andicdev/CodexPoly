-- Arm the six additional July 31 PRE_MARKET profiles.
-- Authenticated preflight and activation remain scheduler-owned.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    batch_notional numeric;
    block_notional numeric;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-31 09:45:00+00' THEN
        RAISE EXCEPTION 'July 31 batch live arming deadline has passed';
    END IF;
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-ben-2026q3',
            'schedule:earnings-cboe-2026q2',
            'schedule:earnings-cvx-2026q2',
            'schedule:earnings-cl-2026q2',
            'schedule:earnings-mrna-2026q2',
            'schedule:earnings-ares-2026q2'
        )
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state IN ('PENDING', 'READY')
          AND preflight_at = TIMESTAMPTZ '2026-07-31 08:30:00+00'
          AND activate_at = TIMESTAMPTZ '2026-07-31 08:45:00+00'
          AND metadata ->> 'block_id' = '2026-07-31-pre-market'
          AND coalesce(
              (metadata ->> 'temporarily_paused')::boolean,
              false
          ) = false
          AND last_error_code IS NULL
    ) <> 6 THEN
        RAISE EXCEPTION 'reviewed July 31 batch schedules are missing';
    END IF;
    IF now() >= TIMESTAMPTZ '2026-07-31 08:30:00+00'
       AND (
           SELECT count(*)
           FROM resolution_profile_schedules
           WHERE schedule_key IN (
               'schedule:earnings-ben-2026q3',
               'schedule:earnings-cboe-2026q2',
               'schedule:earnings-cvx-2026q2',
               'schedule:earnings-cl-2026q2',
               'schedule:earnings-mrna-2026q2',
               'schedule:earnings-ares-2026q2'
           )
             AND state = 'READY'
             AND readiness_valid_until >
                 TIMESTAMPTZ '2026-07-31 08:45:00+00'
       ) <> 6
    THEN
        RAISE EXCEPTION 'July 31 batch authenticated readiness is not fresh';
    END IF;
    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE profile.profile_key IN (
            'earnings-ben-2026q3',
            'earnings-cboe-2026q2',
            'earnings-cvx-2026q2',
            'earnings-cl-2026q2',
            'earnings-mrna-2026q2',
            'earnings-ares-2026q2'
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
    ) <> 6 THEN
        RAISE EXCEPTION 'reviewed July 31 batch profiles are invalid';
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
    IF batch_notional <> 599.4 OR batch_notional > 1000 THEN
        RAISE EXCEPTION 'July 31 batch reviewed notional is invalid';
    END IF;

    SELECT sum(quantity * greatest(yes_desired_price, no_desired_price))
    INTO block_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-xom-2026q2',
        'earnings-ben-2026q3',
        'earnings-cboe-2026q2',
        'earnings-cvx-2026q2',
        'earnings-cl-2026q2',
        'earnings-mrna-2026q2',
        'earnings-ares-2026q2'
    );
    IF block_notional <> 699.3 OR block_notional > 1000 THEN
        RAISE EXCEPTION 'July 31 seven-profile block notional is invalid';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        automation_mode = 'AUTO_LIVE',
        metadata = metadata || jsonb_build_object(
            'armed_for_live', true,
            'armed_by', '045_arm_july_31_premarket_batch',
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
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 6 THEN
        RAISE EXCEPTION 'July 31 batch live arming verification failed';
    END IF;
END
$verify$;

COMMIT;
