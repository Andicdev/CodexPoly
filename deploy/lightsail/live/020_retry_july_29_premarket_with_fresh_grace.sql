-- Give only the four transiently blocked July 29 PRE_MARKET profiles a fresh
-- two-minute activation grace window. The normal scheduler still requests
-- preflight, the readiness worker still authenticates and pre-signs, and
-- AUTO_LIVE still performs the guarded activation.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
DECLARE
    retry_profiles constant text[] := ARRAY[
        'earnings-iart-2026q2',
        'earnings-grmn-2026q2',
        'earnings-cbre-2026q2',
        'earnings-pag-2026q2'
    ];
    retry_scopes constant text[] := ARRAY[
        'earnings:IART:2026Q2',
        'earnings:GRMN:2026Q2',
        'earnings:CBRE:2026Q2',
        'earnings:PAG:2026Q2'
    ];
    retry_activate_at timestamptz := now() + interval '2 minutes';
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-29 09:30:00+00' THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET grace retry deadline has passed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ANY(retry_profiles)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'BLOCKED'
          AND schedule.last_error_code = 'preflight_not_requested'
          AND schedule.metadata ->> 'preflight_retry_count' = '1'
          AND profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.quantity = 100
    ) <> 4 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET grace retry set is not exact';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key IN (
            'earnings-sofi-2026q2',
            'earnings-pg-2026q4',
            'earnings-hum-2026q2',
            'earnings-wing-2026q2',
            'earnings-arcc-2026q2'
        )
          AND schedule.state = 'ACTIVE'
          AND profile.status = 'ENABLED'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-pre-market'
    ) <> 5 THEN
        RAISE EXCEPTION
            'July 29 active five-profile subset is not intact';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = ANY(retry_scopes)
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ANY(retry_scopes)
    ) THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET retry scopes contain facts or claims';
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
        RAISE EXCEPTION
            'live resolution heartbeat is missing or stale';
    END IF;

    UPDATE resolution_profile_schedules
    SET
        state = 'PENDING',
        activate_at = retry_activate_at,
        preflight_request_id = NULL,
        preflight_requested_at = NULL,
        preflight_lease_until = NULL,
        readiness_checked_at = NULL,
        readiness_valid_until = NULL,
        readiness_evidence = '{}'::jsonb,
        last_error_code = NULL,
        metadata = metadata || jsonb_build_object(
            'preflight_retry_count', 2,
            'preflight_retry_reason', 'fresh_activation_grace',
            'original_activate_at', '2026-07-29T09:00:00Z',
            'preflight_retry_guard',
            '020_retry_july_29_premarket_with_fresh_grace'
        ),
        updated_at = now()
    WHERE profile_key = ANY(retry_profiles);
END
$guard$;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key IN (
            'earnings-iart-2026q2',
            'earnings-grmn-2026q2',
            'earnings-cbre-2026q2',
            'earnings-pag-2026q2'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'PENDING'
          AND schedule.preflight_at <= now()
          AND schedule.activate_at > now()
          AND schedule.activate_at <= now() + interval '3 minutes'
          AND schedule.preflight_request_id IS NULL
          AND schedule.last_error_code IS NULL
          AND profile.status = 'DISABLED'
    ) <> 4 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET fresh grace verification failed';
    END IF;
END
$verify$;

COMMIT;
