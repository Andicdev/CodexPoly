-- Schedule the checked-in July earnings profiles for authenticated preflight.
-- AUTO_PREFLIGHT never changes resolution_execution_profiles.status to ENABLED.

WITH scheduled_profile (profile_key) AS (
    VALUES
        ('earnings-pypl-2026q2'),
        ('earnings-ups-2026q2'),
        ('earnings-hlt-2026q2'),
        ('earnings-ivz-2026q2'),
        ('earnings-ko-2026q2'),
        ('earnings-rcl-2026q2'),
        ('earnings-ba-2026q2'),
        ('earnings-jblu-2026q2'),
        ('earnings-spgi-2026q2'),
        ('earnings-czr-2026q2'),
        ('earnings-csgp-2026q2'),
        ('earnings-v-2026q3'),
        ('earnings-f-2026q2'),
        ('earnings-nxpi-2026q2'),
        ('earnings-sbux-2026q3')
)
INSERT INTO resolution_profile_schedules (
    schedule_key,
    profile_key,
    automation_mode,
    preflight_at,
    activate_at,
    deactivate_at,
    metadata,
    state
)
SELECT
    'schedule:' || profile.profile_key,
    profile.profile_key,
    'AUTO_PREFLIGHT',
    profile.prepare_from - interval '15 minutes',
    profile.prepare_from,
    profile.expires_at,
    jsonb_build_object(
        'seed', '009_schedule_july_28_auto_preflight',
        'preflight_lead_minutes', 15
    ),
    'PENDING'
FROM scheduled_profile
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = scheduled_profile.profile_key
WHERE profile.status = 'DISABLED'
ON CONFLICT (schedule_key) DO UPDATE
SET
    automation_mode = EXCLUDED.automation_mode,
    preflight_at = EXCLUDED.preflight_at,
    activate_at = EXCLUDED.activate_at,
    deactivate_at = EXCLUDED.deactivate_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
WHERE resolution_profile_schedules.state = 'PENDING';

DO $$
DECLARE
    expected_count integer := 15;
    actual_count integer;
    enabled_count integer;
BEGIN
    SELECT count(*)
    INTO actual_count
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
      AND automation_mode = 'AUTO_PREFLIGHT';

    IF actual_count <> expected_count THEN
        RAISE EXCEPTION 'expected 15 AUTO_PREFLIGHT schedules';
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
        RAISE EXCEPTION 'schedule seed must not enable execution profiles';
    END IF;
END
$$;
