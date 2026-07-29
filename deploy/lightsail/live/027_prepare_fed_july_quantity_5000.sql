-- Raise only the five reviewed July FOMC profiles to 5,000 shares.
-- This resets readiness and leaves every profile disabled.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-29 17:55:00+00' THEN
        RAISE EXCEPTION 'FED quantity preparation deadline has passed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE profile.profile_key IN (
            'fed-jul29-no-change',
            'fed-jul29-increase-25',
            'fed-jul29-increase-50-plus',
            'fed-jul29-decrease-25',
            'fed-jul29-decrease-50-plus'
        )
          AND profile.source_name = 'fed_fomc'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 50
          AND profile.status = 'DISABLED'
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'READY'
          AND schedule.readiness_valid_until >
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
    ) <> 5 THEN
        RAISE EXCEPTION 'reviewed ready FED profile set is incomplete';
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

UPDATE resolution_execution_profiles
SET
    quantity = 5000,
    metadata = metadata || jsonb_build_object(
        'quantity_policy', '5000_shares',
        'aggregate_notional_cap', 26000
    ),
    updated_at = now()
WHERE profile_key IN (
    'fed-jul29-no-change',
    'fed-jul29-increase-25',
    'fed-jul29-increase-50-plus',
    'fed-jul29-decrease-25',
    'fed-jul29-decrease-50-plus'
)
  AND source_name = 'fed_fomc'
  AND status = 'DISABLED';

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
    metadata = metadata || jsonb_build_object(
        'quantity_policy', '5000_shares',
        'aggregate_notional_cap', 26000
    ),
    updated_at = now()
WHERE profile_key IN (
    'fed-jul29-no-change',
    'fed-jul29-increase-25',
    'fed-jul29-increase-50-plus',
    'fed-jul29-decrease-25',
    'fed-jul29-decrease-50-plus'
)
  AND automation_mode = 'AUTO_PREFLIGHT'
  AND state = 'READY';

DO $verify$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE profile.profile_key IN (
            'fed-jul29-no-change',
            'fed-jul29-increase-25',
            'fed-jul29-increase-50-plus',
            'fed-jul29-decrease-25',
            'fed-jul29-decrease-50-plus'
        )
          AND profile.quantity = 5000
          AND profile.status = 'DISABLED'
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'PENDING'
          AND schedule.readiness_checked_at IS NULL
          AND schedule.readiness_valid_until IS NULL
    ) <> 5 THEN
        RAISE EXCEPTION 'FED quantity update verification failed';
    END IF;

    SELECT sum(
        quantity * greatest(yes_desired_price, no_desired_price)
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'fed-jul29-no-change',
        'fed-jul29-increase-25',
        'fed-jul29-increase-50-plus',
        'fed-jul29-decrease-25',
        'fed-jul29-decrease-50-plus'
    );

    IF reviewed_notional <> 24975 OR reviewed_notional > 26000 THEN
        RAISE EXCEPTION 'FED reviewed aggregate notional is invalid';
    END IF;
END
$verify$;

COMMIT;
