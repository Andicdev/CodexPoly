-- Confirm fresh authenticated readiness for the five July FOMC profiles.
-- Profiles must remain disabled and no execution claim may exist.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE profile.profile_key IN (
            'fed-jul29-no-change',
            'fed-jul29-increase-25',
            'fed-jul29-increase-50-plus',
            'fed-jul29-decrease-25',
            'fed-jul29-decrease-50-plus'
        )
          AND profile.source_name = 'fed_fomc'
          AND profile.status = 'DISABLED'
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'READY'
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until >
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND schedule.last_error_code IS NULL
    ) <> 5 THEN
        RAISE EXCEPTION
            'FED July authenticated readiness set is incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'fed:fomc:2026-07-29:%'
    ) THEN
        RAISE EXCEPTION 'FED July execution claim already exists';
    END IF;
END
$verification$;

ROLLBACK;
