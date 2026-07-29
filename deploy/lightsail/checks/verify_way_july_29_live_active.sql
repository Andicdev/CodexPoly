-- Confirm the exact WAY profile after scheduler activation, without returning
-- account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key = 'schedule:earnings-way-2026q2'
          AND profile.profile_key = 'earnings-way-2026q2'
          AND profile.scope_id = 'earnings:WAY:2026Q2'
          AND profile.quantity = 100
          AND profile.status = 'ENABLED'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND schedule.readiness_valid_until > now()
          AND schedule.last_error_code IS NULL
    ) <> 1 THEN
        RAISE EXCEPTION 'WAY live active profile is incomplete';
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

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:WAY:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:WAY:2026Q2'
    ) THEN
        RAISE EXCEPTION 'WAY facts or claims exist before final prestart check';
    END IF;
END
$verification$;

ROLLBACK;
