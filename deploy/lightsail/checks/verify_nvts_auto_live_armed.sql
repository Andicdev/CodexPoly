-- Verify NVTS is safely scheduled but still disabled before preflight.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-27 18:45:00+00' THEN
        RAISE EXCEPTION 'NVTS preflight has already started';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key =
                  'schedule:earnings-nvts-2026q2'
          AND schedule.profile_key = 'earnings-nvts-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-27 18:45:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-27 19:00:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-28 03:00:00+00'
          AND schedule.state = 'PENDING'
          AND profile.status = 'DISABLED'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 50
    ) THEN
        RAISE EXCEPTION 'NVTS AUTO_LIVE schedule is not safely armed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:NVTS:2026Q2'
          AND status = 'VALIDATED'
    ) THEN
        RAISE EXCEPTION 'a validated NVTS fact already exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:NVTS:2026Q2'
    ) THEN
        RAISE EXCEPTION 'an NVTS execution claim already exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'an active NVTS order group already exists';
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

    SELECT
        COALESCE(
            SUM(
                profile.quantity * GREATEST(
                    profile.yes_desired_price,
                    profile.no_desired_price
                )
            ),
            0
        )
    INTO reviewed_notional
    FROM resolution_profile_schedules AS schedule
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = schedule.profile_key
    WHERE schedule.automation_mode = 'AUTO_LIVE'
      AND schedule.state NOT IN ('BLOCKED', 'EXPIRED');

    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'reviewed aggregate notional exceeds 1000';
    END IF;
END
$verify$;

ROLLBACK;
