-- Fail-closed verification before enabling the production scheduler switch.
-- The production runner suppresses query results; success is exit status only.

DO $$
DECLARE
    armed_count integer;
    enabled_count integer;
    reviewed_notional numeric;
BEGIN
    IF to_regclass('resolution_profile_schedules') IS NULL
       OR to_regclass('resolution_profile_schedule_events') IS NULL
       OR to_regclass('resolution_runtime_heartbeats') IS NULL THEN
        RAISE EXCEPTION 'AUTO_LIVE lifecycle schema is missing';
    END IF;

    SELECT count(*)
    INTO armed_count
    FROM resolution_profile_schedules
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
      AND automation_mode = 'AUTO_LIVE'
      AND state = 'PENDING';

    IF armed_count <> 15 THEN
        RAISE EXCEPTION 'expected 15 pending AUTO_LIVE schedules';
    END IF;

    SELECT
        count(*) FILTER (WHERE status <> 'DISABLED'),
        COALESCE(
            SUM(
                quantity * GREATEST(
                    yes_desired_price,
                    no_desired_price
                )
            ),
            0
        )
    INTO enabled_count, reviewed_notional
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

    IF enabled_count <> 0 THEN
        RAISE EXCEPTION 'AUTO_LIVE arming enabled an execution profile';
    END IF;
    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'reviewed aggregate notional exceeds 1000';
    END IF;
END
$$;
