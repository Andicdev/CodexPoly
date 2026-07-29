-- Confirm the exact FED July live set after scheduler activation.

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
          AND profile.quantity = 5000
          AND profile.status = 'ENABLED'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND schedule.readiness_valid_until > now()
          AND schedule.last_error_code IS NULL
    ) <> 5 THEN
        RAISE EXCEPTION 'FED July live active set is incomplete';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE source_name = 'fed_fomc'
          AND status = 'ENABLED'
    ) <> 5 THEN
        RAISE EXCEPTION 'unexpected enabled FED profile exists';
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
END
$verification$;

ROLLBACK;
