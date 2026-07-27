-- Arm the reviewed July 28 earnings batch for automatic live activation.
-- This changes schedule policy only. Execution profiles remain DISABLED until
-- the scheduler observes both authenticated readiness and a healthy live
-- resolution-runtime heartbeat.

DO $$
DECLARE
    changed_count integer;
    enabled_count integer;
    reviewed_notional numeric;
    oversized_count integer;
BEGIN
    UPDATE resolution_profile_schedules
    SET
        automation_mode = 'AUTO_LIVE',
        metadata = metadata || jsonb_build_object(
            'armed_by_seed', '010_arm_july_28_auto_live',
            'aggregate_notional_cap', 1000
        ),
        updated_at = now()
    WHERE profile_key IN (
        'earnings-pypl-2026q2',
        'earnings-ups-2026q2',
        'earnings-hlt-2026q2',
        'earnings-ivz-2026q2',
        'earnings-ko-2026q2',
        'earnings-rcl-2026q2',
        'earnings-ba-2026q2',
        'earnings-jblu-2026q2',
        'earnings-spgi-2026q2',
        'earnings-czr-2026q2',
        'earnings-csgp-2026q2',
        'earnings-v-2026q3',
        'earnings-f-2026q2',
        'earnings-nxpi-2026q2',
        'earnings-sbux-2026q3'
    )
      AND automation_mode = 'AUTO_PREFLIGHT'
      AND state = 'PENDING';

    GET DIAGNOSTICS changed_count = ROW_COUNT;
    IF changed_count <> 15 THEN
        RAISE EXCEPTION
            'expected 15 pending AUTO_PREFLIGHT schedules to arm';
    END IF;

    SELECT count(*)
    INTO enabled_count
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-pypl-2026q2',
        'earnings-ups-2026q2',
        'earnings-hlt-2026q2',
        'earnings-ivz-2026q2',
        'earnings-ko-2026q2',
        'earnings-rcl-2026q2',
        'earnings-ba-2026q2',
        'earnings-jblu-2026q2',
        'earnings-spgi-2026q2',
        'earnings-czr-2026q2',
        'earnings-csgp-2026q2',
        'earnings-v-2026q3',
        'earnings-f-2026q2',
        'earnings-nxpi-2026q2',
        'earnings-sbux-2026q3'
    )
      AND status <> 'DISABLED';

    IF enabled_count <> 0 THEN
        RAISE EXCEPTION
            'AUTO_LIVE arming must not enable execution profiles';
    END IF;

    SELECT
        COALESCE(
            SUM(
                quantity * GREATEST(
                    yes_desired_price,
                    no_desired_price
                )
            ),
            0
        ),
        count(*) FILTER (
            WHERE quantity > 50
               OR yes_desired_price > 0.999
               OR no_desired_price > 0.999
        )
    INTO reviewed_notional, oversized_count
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-pypl-2026q2',
        'earnings-ups-2026q2',
        'earnings-hlt-2026q2',
        'earnings-ivz-2026q2',
        'earnings-ko-2026q2',
        'earnings-rcl-2026q2',
        'earnings-ba-2026q2',
        'earnings-jblu-2026q2',
        'earnings-spgi-2026q2',
        'earnings-czr-2026q2',
        'earnings-csgp-2026q2',
        'earnings-v-2026q3',
        'earnings-f-2026q2',
        'earnings-nxpi-2026q2',
        'earnings-sbux-2026q3'
    );

    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'reviewed aggregate notional exceeds 1000';
    END IF;
    IF oversized_count <> 0 THEN
        RAISE EXCEPTION 'reviewed order template exceeds 50 at 0.999';
    END IF;
END
$$;
