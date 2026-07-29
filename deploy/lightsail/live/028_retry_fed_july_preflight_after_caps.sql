-- Retry only the expected FED preflight failures produced while the old
-- 100-share runtime caps were still active. Profiles remain disabled.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-29 17:56:00+00' THEN
        RAISE EXCEPTION 'FED preflight retry deadline has passed';
    END IF;

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
          AND profile.quantity = 5000
          AND profile.status = 'DISABLED'
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'BLOCKED'
          AND schedule.last_error_code IN (
              'preflight_valueerror',
              'authenticated_preflight_not_ready'
          )
    ) <> 5 THEN
        RAISE EXCEPTION 'expected FED cap-related failures are incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'fed:fomc:2026-07-29:%'
    ) THEN
        RAISE EXCEPTION 'FED execution claim already exists';
    END IF;
END
$guard$;

UPDATE resolution_profile_schedules
SET
    state = 'PENDING',
    preflight_request_id = NULL,
    preflight_requested_at = NULL,
    preflight_lease_until = NULL,
    readiness_checked_at = NULL,
    readiness_valid_until = NULL,
    readiness_evidence = '{}'::jsonb,
    last_error_code = NULL,
    updated_at = now()
WHERE profile_key IN (
    'fed-jul29-no-change',
    'fed-jul29-increase-25',
    'fed-jul29-increase-50-plus',
    'fed-jul29-decrease-25',
    'fed-jul29-decrease-50-plus'
)
  AND automation_mode = 'AUTO_PREFLIGHT'
  AND state = 'BLOCKED'
  AND last_error_code IN (
      'preflight_valueerror',
      'authenticated_preflight_not_ready'
  );

COMMIT;
