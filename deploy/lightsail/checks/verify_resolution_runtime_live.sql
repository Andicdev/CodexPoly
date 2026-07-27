-- Confirm the long-lived resolution process is currently eligible to guard
-- AUTO_LIVE activation. This returns no rows and exposes no secret values.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at > now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION
            'fresh fully-live hosted resolution heartbeat is missing';
    END IF;
END
$$;
