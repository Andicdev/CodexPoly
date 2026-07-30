BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-30 19:20:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-30 20:00:00+00'
    THEN
        RAISE EXCEPTION 'RBLX active check is outside its valid interval';
    END IF;
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key =
              'schedule:earnings-rblx-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.metadata ->> 'reduced_lead_accepted' = 'true'
          AND profile.profile_key = 'earnings-rblx-2026q2'
          AND profile.status = 'ENABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'RBLX active state is invalid';
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
        WHERE scope_id = 'earnings:RBLX:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RBLX has an unexpected execution claim';
    END IF;
END
$verify$;

ROLLBACK;
