-- Read-only post-09:45 UTC authenticated preflight checkpoint.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-30 09:45:00+00' THEN
        RAISE EXCEPTION 'YUM/ICE/CI preflight checkpoint is premature';
    END IF;

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
          AND schedule.state = 'READY'
          AND schedule.preflight_request_id IS NOT NULL
          AND schedule.preflight_requested_at IS NOT NULL
          AND schedule.preflight_lease_until IS NULL
          AND schedule.readiness_checked_at IS NOT NULL
          AND schedule.readiness_valid_until >
              now()
          AND schedule.readiness_valid_until <= schedule.deactivate_at
          AND jsonb_typeof(schedule.readiness_evidence) = 'object'
          AND schedule.readiness_evidence <> '{}'::jsonb
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.status = 'DISABLED'
    ) <> 3 THEN
        RAISE EXCEPTION 'YUM/ICE/CI authenticated preflight is not ready';
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
END
$verification$;

ROLLBACK;
