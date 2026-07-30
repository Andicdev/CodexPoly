-- Arm only YUM, ICE, and CI for the July 30 PRE_MARKET window.
-- Authenticated preflight and profile activation remain scheduler-owned.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    schedule_row record;
    selected_notional numeric;
    five_profile_notional numeric;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 10:00:00+00' THEN
        RAISE EXCEPTION 'YUM/ICE/CI live arming deadline has passed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-yum-2026q2',
            'schedule:earnings-ice-2026q2',
            'schedule:earnings-ci-2026q2'
        )
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state IN ('PENDING', 'READY')
          AND preflight_at =
              TIMESTAMPTZ '2026-07-30 09:45:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-30 10:00:00+00'
          AND metadata ->> 'block_id' =
              '2026-07-30-extra-pre-market'
          AND coalesce(
              (metadata ->> 'temporarily_paused')::boolean,
              false
          ) = false
          AND last_error_code IS NULL
    ) <> 3 THEN
        RAISE EXCEPTION 'reviewed YUM/ICE/CI schedules are missing';
    END IF;

    FOR schedule_row IN
        SELECT
            schedule_key,
            state,
            readiness_valid_until
        FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-yum-2026q2',
            'schedule:earnings-ice-2026q2',
            'schedule:earnings-ci-2026q2'
        )
        FOR UPDATE
    LOOP
        IF now() >= TIMESTAMPTZ '2026-07-30 09:45:00+00'
           AND (
               schedule_row.state <> 'READY'
               OR schedule_row.readiness_valid_until IS NULL
               OR schedule_row.readiness_valid_until <=
                   TIMESTAMPTZ '2026-07-30 10:00:00+00'
           )
        THEN
            RAISE EXCEPTION
                'YUM/ICE/CI authenticated readiness is not fresh';
        END IF;
    END LOOP;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE profile.profile_key IN (
            'earnings-yum-2026q2',
            'earnings-ice-2026q2',
            'earnings-ci-2026q2'
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
          AND rule.rule_key IN (
              'yum-2026q2-nongaap-eps-1pt56',
              'ice-2026q2-nongaap-eps-1pt84',
              'ci-2026q2-nongaap-eps-7pt60'
          )
          AND rule.status = 'SHADOW'
    ) <> 3 THEN
        RAISE EXCEPTION 'reviewed YUM/ICE/CI profiles are invalid';
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
        RAISE EXCEPTION 'YUM/ICE/CI scopes already contain facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id IN (
              '0xf12f1d26c9f7c02c36e0986be4e32f5adc2b30642f0f1f4dda2b5a51bf3e20dd',
              '0x52f96f0d385691c1534d86c7fbad89abd4358da382624b79882279a4ec3eaa20',
              '0xecdbab51723875aee7d00faa3b5a8adbbfe7054763dff375c92443a670bb6a61'
          )
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'YUM/ICE/CI active order group already exists';
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
    INTO selected_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-yum-2026q2',
        'earnings-ice-2026q2',
        'earnings-ci-2026q2'
    );

    IF selected_notional <> 299.7 OR selected_notional > 1000 THEN
        RAISE EXCEPTION 'YUM/ICE/CI reviewed notional is invalid';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-virt-2026q2',
            'schedule:earnings-ma-2026q2'
        )
          AND automation_mode = 'AUTO_LIVE'
          AND state IN ('PENDING', 'READY')
          AND metadata ->> 'armed_for_live' = 'true'
    ) <> 2 THEN
        RAISE EXCEPTION 'existing VIRT/MA live schedules are not armed';
    END IF;

    SELECT sum(
        profile.quantity * greatest(
            profile.yes_desired_price,
            profile.no_desired_price
        )
    )
    INTO five_profile_notional
    FROM resolution_execution_profiles AS profile
    WHERE profile.profile_key IN (
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

    UPDATE resolution_profile_schedules
    SET
        automation_mode = 'AUTO_LIVE',
        metadata = metadata || jsonb_build_object(
            'armed_for_live', true,
            'armed_by', '034_arm_yum_ice_ci_july_30_premarket',
            'aggregate_notional_cap', 1000
        ),
        updated_at = now()
    WHERE schedule_key IN (
        'schedule:earnings-yum-2026q2',
        'schedule:earnings-ice-2026q2',
        'schedule:earnings-ci-2026q2'
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
            'schedule:earnings-yum-2026q2',
            'schedule:earnings-ice-2026q2',
            'schedule:earnings-ci-2026q2'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 3 THEN
        RAISE EXCEPTION 'YUM/ICE/CI live arming verification failed';
    END IF;
END
$verify$;

COMMIT;
