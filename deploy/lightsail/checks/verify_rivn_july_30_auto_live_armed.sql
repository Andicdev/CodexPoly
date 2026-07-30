BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 18:45:00+00' THEN
        RAISE EXCEPTION 'RIVN armed check is only valid before activation';
    END IF;
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key =
              'schedule:earnings-rivn-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'READY'
          AND schedule.readiness_valid_until >
              TIMESTAMPTZ '2026-07-30 18:45:00+00'
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.metadata ->> 'reduced_lead_accepted' = 'true'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN armed state is invalid';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at >= now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'live resolution heartbeat is missing or stale';
    END IF;
    IF EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RIVN:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RIVN has an unexpected execution claim';
    END IF;
END
$verify$;

ROLLBACK;
