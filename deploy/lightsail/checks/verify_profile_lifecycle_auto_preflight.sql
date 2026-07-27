-- Fail-closed verification for the first scheduled AUTO_PREFLIGHT rollout.
-- The production runner suppresses query results; success is exit status only.

DO $$
DECLARE
    scheduled_count integer;
    enabled_count integer;
    unsafe_schedule_count integer;
BEGIN
    IF to_regclass('resolution_profile_schedules') IS NULL
       OR to_regclass('resolution_profile_schedule_events') IS NULL THEN
        RAISE EXCEPTION 'profile lifecycle schema is missing';
    END IF;

    SELECT count(*)
    INTO scheduled_count
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
      AND automation_mode = 'AUTO_PREFLIGHT'
      AND state = 'PENDING';

    IF scheduled_count <> 15 THEN
        RAISE EXCEPTION 'expected 15 pending AUTO_PREFLIGHT schedules';
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
        RAISE EXCEPTION 'scheduled execution profile is enabled';
    END IF;

    SELECT count(*)
    INTO unsafe_schedule_count
    FROM resolution_profile_schedules
    WHERE automation_mode = 'AUTO_LIVE'
       OR state = 'ACTIVE';

    IF unsafe_schedule_count <> 0 THEN
        RAISE EXCEPTION 'automatic live profile schedule is armed';
    END IF;
END
$$;
