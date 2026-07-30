-- Correct the already-authorized MA AUTO_LIVE schedule before the release.
-- The issuer confirmed the 13:00 UTC call but not the publication time.
-- Fail closed unless the original reviewed schedule is still clean.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 11:00:00+00' THEN
        RAISE EXCEPTION 'MA early-window correction deadline has passed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.schedule_key = 'schedule:earnings-ma-2026q2'
          AND schedule.profile_key = 'earnings-ma-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'PENDING'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-30 10:30:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-30 11:00:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-30 14:30:00+00'
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.last_error_code IS NULL
          AND profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.quantity = 100
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND rule.rule_key = 'ma-2026q2-nongaap-eps-4pt77'
          AND rule.status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'reviewed pending MA schedule is unavailable';
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
          AND last_seen_at >= now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'live resolution heartbeat is missing or stale';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        preflight_at = TIMESTAMPTZ '2026-07-30 10:15:00+00',
        activate_at = TIMESTAMPTZ '2026-07-30 10:20:00+00',
        metadata = metadata || jsonb_build_object(
            'earliest_signal_at', '2026-07-30T10:30:00Z',
            'activation_safety_lead_minutes', 10,
            'timing_basis', 'official_call_with_conservative_release_floor',
            'timing_corrected_by',
                '035_advance_ma_earliest_release_window'
        ),
        updated_at = now()
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
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-30 10:15:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-30 10:20:00+00'
          AND (
              schedule.metadata ->> 'earliest_signal_at'
          )::timestamptz =
              TIMESTAMPTZ '2026-07-30 10:30:00+00'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'MA early-window correction verification failed';
    END IF;
END
$verify$;

COMMIT;
