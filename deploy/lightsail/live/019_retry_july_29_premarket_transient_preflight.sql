-- Retry only the four July 29 PRE_MARKET profiles whose first authenticated
-- preflight returned the generic non-ready result. This resets them to the
-- normal scheduler path; it does not mark readiness or enable profiles.

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
BEGIN
    IF now() < TIMESTAMPTZ '2026-07-29 08:45:00+00'
       OR now() >= TIMESTAMPTZ '2026-07-29 10:00:00+00' THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET retry is outside its guarded window';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ANY(retry_profiles)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'BLOCKED'
          AND schedule.last_error_code =
              'authenticated_preflight_not_ready'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-pre-market'
          AND profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.quantity = 100
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
    ) <> 4 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET retry set does not match blocked profiles';
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
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('READY', 'ACTIVE')
          AND profile.status IN ('DISABLED', 'ENABLED')
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-pre-market'
    ) <> 5 THEN
        RAISE EXCEPTION
            'July 29 successful preflight subset is not intact';
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
        preflight_request_id = NULL,
        preflight_requested_at = NULL,
        preflight_lease_until = NULL,
        readiness_checked_at = NULL,
        readiness_valid_until = NULL,
        readiness_evidence = '{}'::jsonb,
        last_error_code = NULL,
        metadata = metadata || jsonb_build_object(
            'preflight_retry_count', 1,
            'preflight_retry_reason', 'transient_not_ready',
            'preflight_retry_guard',
            '019_retry_july_29_premarket_transient_preflight'
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
          AND schedule.preflight_request_id IS NULL
          AND schedule.readiness_valid_until IS NULL
          AND schedule.last_error_code IS NULL
          AND profile.status = 'DISABLED'
    ) <> 4 THEN
        RAISE EXCEPTION
            'July 29 PRE_MARKET retry reset verification failed';
    END IF;
END
$verify$;

COMMIT;
