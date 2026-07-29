-- Arm the five reviewed July FOMC profiles after authenticated preflight.
-- Scheduler activation remains responsible for enabling the profiles.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-29 18:00:00+00' THEN
        RAISE EXCEPTION 'FED live arming deadline has passed';
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
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 5000
          AND profile.status = 'DISABLED'
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'READY'
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until >
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND schedule.last_error_code IS NULL
    ) <> 5 THEN
        RAISE EXCEPTION 'FED authenticated ready set is incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'fed:fomc:2026-07-29:%'
    ) THEN
        RAISE EXCEPTION 'FED execution claim already exists';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at > now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'fresh live resolution heartbeat is missing';
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
$guard$;

UPDATE resolution_profile_schedules
SET
    automation_mode = 'AUTO_LIVE',
    metadata = metadata || jsonb_build_object(
        'armed_for_live', true,
        'armed_by', '029_arm_fed_july_quantity_5000'
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
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE profile.source_name = 'fed_fomc'
          AND profile.quantity = 5000
          AND profile.status = 'DISABLED'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'READY'
          AND schedule.metadata ->> 'armed_for_live' = 'true'
    ) <> 5 THEN
        RAISE EXCEPTION 'FED live arming verification failed';
    END IF;
END
$verify$;

COMMIT;
