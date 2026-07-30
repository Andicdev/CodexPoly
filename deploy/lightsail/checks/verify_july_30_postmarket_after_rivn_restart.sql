BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE (schedule.schedule_key, schedule.state, profile.status) IN (
            (
                'schedule:earnings-amzn-2026q2',
                'ACTIVE',
                'ENABLED'
            ),
            (
                'schedule:earnings-aapl-2026q3',
                'ACTIVE',
                'ENABLED'
            ),
            (
                'schedule:earnings-dlb-2026q3',
                'ACTIVE',
                'ENABLED'
            ),
            (
                'schedule:earnings-rddt-2026q2',
                'ACTIVE',
                'ENABLED'
            ),
            (
                'schedule:earnings-rivn-2026q2',
                'READY',
                'DISABLED'
            )
        )
    ) <> 5 THEN
        RAISE EXCEPTION 'July 30 post-market state preservation failed';
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
        SELECT 1 FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-amzn-2026q2',
            'schedule:earnings-aapl-2026q3',
            'schedule:earnings-dlb-2026q3',
            'schedule:earnings-rddt-2026q2',
            'schedule:earnings-rivn-2026q2'
        )
          AND last_error_code IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'July 30 post-market schedule error detected';
    END IF;
END
$verify$;

ROLLBACK;
