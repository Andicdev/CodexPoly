-- Recover MA after the first early-window correction crossed activate_at
-- before the scheduler could request authenticated preflight.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    correction_now timestamptz := now();
BEGIN
    IF correction_now >= TIMESTAMPTZ '2026-07-30 11:00:00+00' THEN
        RAISE EXCEPTION 'MA preflight recovery deadline has passed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key = 'schedule:earnings-ma-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'BLOCKED'
          AND schedule.last_error_code = 'preflight_not_requested'
          AND schedule.metadata ->> 'timing_corrected_by' =
              '035_advance_ma_earliest_release_window'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
    ) <> 1 THEN
        RAISE EXCEPTION 'recoverable MA schedule is unavailable';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:MA:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:MA:2026Q2'
    ) THEN
        RAISE EXCEPTION 'MA already contains a fact or execution claim';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at >= correction_now - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'live resolution heartbeat is missing or stale';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        preflight_at = correction_now,
        activate_at = correction_now + interval '3 minutes',
        preflight_request_id = NULL,
        preflight_requested_at = NULL,
        preflight_lease_until = NULL,
        readiness_checked_at = NULL,
        readiness_valid_until = NULL,
        readiness_evidence = '{}'::jsonb,
        last_error_code = NULL,
        metadata = metadata || jsonb_build_object(
            'earliest_signal_at',
                correction_now + interval '8 minutes',
            'activation_safety_lead_minutes', 5,
            'timing_recovered_by',
                '036_recover_ma_early_preflight'
        ),
        state = 'PENDING',
        updated_at = correction_now
    WHERE schedule_key = 'schedule:earnings-ma-2026q2';
END
$guard$;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.schedule_key = 'schedule:earnings-ma-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'PENDING'
          AND schedule.last_error_code IS NULL
          AND schedule.activate_at - schedule.preflight_at =
              interval '3 minutes'
          AND (
              schedule.metadata ->> 'earliest_signal_at'
          )::timestamptz - schedule.activate_at =
              interval '5 minutes'
          AND profile.status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'MA preflight recovery verification failed';
    END IF;
END
$verify$;

COMMIT;
