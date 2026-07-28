BEGIN;

DO $guard$
DECLARE
    premarket_rearm CONSTANT text[] := ARRAY[
        'earnings-rcl-2026q2',
        'earnings-ba-2026q2',
        'earnings-jblu-2026q2',
        'earnings-spgi-2026q2'
    ];
    premarket_existing CONSTANT text[] := ARRAY[
        'earnings-hlt-2026q2',
        'earnings-ivz-2026q2',
        'earnings-ko-2026q2',
        'earnings-pypl-2026q2'
    ];
    postmarket CONSTANT text[] := ARRAY[
        'earnings-csgp-2026q2',
        'earnings-czr-2026q2',
        'earnings-f-2026q2',
        'earnings-nxpi-2026q2',
        'earnings-v-2026q3'
    ];
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
        RAISE EXCEPTION 'fresh fully-live resolution heartbeat is missing';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ANY(premarket_rearm)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'BLOCKED'
          AND profile.status = 'DISABLED'
          AND schedule.deactivate_at > now()
    ) <> cardinality(premarket_rearm) THEN
        RAISE EXCEPTION 'pre-market recovery profile guard failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = ANY(ARRAY[
            'earnings:RCL:2026Q2',
            'earnings:BA:2026Q2',
            'earnings:JBLU:2026Q2',
            'earnings:SPGI:2026Q2'
        ])
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ANY(ARRAY[
            'earnings:RCL:2026Q2',
            'earnings:BA:2026Q2',
            'earnings:JBLU:2026Q2',
            'earnings:SPGI:2026Q2'
        ])
    ) THEN
        RAISE EXCEPTION 'pre-market recovery has a fact or execution claim';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ANY(premarket_existing)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND profile.status = 'ENABLED'
          AND schedule.deactivate_at > now()
    ) <> cardinality(premarket_existing) THEN
        RAISE EXCEPTION 'existing pre-market live block guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ANY(postmarket)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'PENDING'
          AND profile.status = 'DISABLED'
    ) <> cardinality(postmarket) THEN
        RAISE EXCEPTION 'post-market pause guard failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ANY(ARRAY[
            'earnings:CSGP:2026Q2',
            'earnings:CZR:2026Q2',
            'earnings:F:2026Q2',
            'earnings:NXPI:2026Q2',
            'earnings:V:2026Q3'
        ])
    ) THEN
        RAISE EXCEPTION 'post-market block already has execution claims';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key = 'earnings-ups-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'BLOCKED'
          AND profile.status = 'DISABLED'
          AND rule.status = 'WATCHING'
    ) OR (
        SELECT count(*)
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:UPS:2026Q2'
          AND status = 'VALIDATED'
    ) <> 1 OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:UPS:2026Q2'
    ) THEN
        RAISE EXCEPTION 'UPS manual completion guard failed';
    END IF;
END
$guard$;

INSERT INTO resolution_profile_schedule_events (
    event_key,
    schedule_id,
    schedule_key,
    profile_key,
    previous_state,
    next_state,
    event_kind,
    reason_code,
    metadata
)
SELECT
    'manual-complete:ups:2026-07-28',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'EXPIRED',
    'MANUAL_COMPLETED',
    'source_fact_without_live_execution',
    jsonb_build_object(
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-28-pre-market'
    )
FROM resolution_profile_schedules AS schedule
WHERE schedule.profile_key = 'earnings-ups-2026q2'
ON CONFLICT (event_key) DO NOTHING;

UPDATE resolution_profile_schedules
SET
    automation_mode = 'MANUAL',
    state = 'EXPIRED',
    preflight_request_id = NULL,
    preflight_requested_at = NULL,
    preflight_lease_until = NULL,
    readiness_checked_at = NULL,
    readiness_valid_until = NULL,
    readiness_evidence = '{}'::jsonb,
    last_error_code = NULL,
    metadata = metadata || jsonb_build_object(
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-28-pre-market',
        'manual_completed', true,
        'manual_completed_reason',
        'source_fact_without_live_execution'
    ),
    updated_at = now()
WHERE profile_key = 'earnings-ups-2026q2';

UPDATE resolution_execution_profiles
SET status = 'DISABLED', updated_at = now()
WHERE profile_key = 'earnings-ups-2026q2';

UPDATE earnings_market_rules
SET status = 'DISABLED', updated_at = now()
WHERE scope_id = 'earnings:UPS:2026Q2';

UPDATE earnings_release_catalog
SET schedule_status = 'REPORTED', updated_at = now()
WHERE event_key = 'UPS:2026-07-28';

INSERT INTO resolution_profile_schedule_events (
    event_key,
    schedule_id,
    schedule_key,
    profile_key,
    previous_state,
    next_state,
    event_kind,
    reason_code,
    metadata
)
SELECT
    'manual-rearm:' || schedule.profile_key
        || ':2026-07-28-pre-market-r1',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'PENDING',
    'PROFILE_REARMED',
    'transient_preparation_capacity_recovered',
    jsonb_build_object(
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-28-pre-market'
    )
FROM resolution_profile_schedules AS schedule
WHERE schedule.profile_key = ANY(ARRAY[
    'earnings-rcl-2026q2',
    'earnings-ba-2026q2',
    'earnings-jblu-2026q2',
    'earnings-spgi-2026q2'
])
ON CONFLICT (event_key) DO NOTHING;

UPDATE resolution_profile_schedules
SET
    automation_mode = 'AUTO_LIVE',
    preflight_at = now(),
    activate_at = now(),
    state = 'PENDING',
    preflight_request_id = NULL,
    preflight_requested_at = NULL,
    preflight_lease_until = NULL,
    readiness_checked_at = NULL,
    readiness_valid_until = NULL,
    readiness_evidence = '{}'::jsonb,
    last_error_code = NULL,
    metadata = metadata || jsonb_build_object(
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-28-pre-market',
        'rearmed_after_transient_failure', true
    ),
    updated_at = now()
WHERE profile_key = ANY(ARRAY[
    'earnings-rcl-2026q2',
    'earnings-ba-2026q2',
    'earnings-jblu-2026q2',
    'earnings-spgi-2026q2'
]);

UPDATE resolution_profile_schedules
SET
    metadata = metadata || jsonb_build_object(
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-28-pre-market'
    ),
    updated_at = now()
WHERE profile_key = ANY(ARRAY[
    'earnings-hlt-2026q2',
    'earnings-ivz-2026q2',
    'earnings-ko-2026q2',
    'earnings-pypl-2026q2'
]);

UPDATE resolution_profile_schedules
SET
    automation_mode = 'MANUAL',
    metadata = metadata || jsonb_build_object(
        'live_block', 'POST_MARKET',
        'block_id', '2026-07-28-post-market',
        'temporarily_paused', true
    ),
    updated_at = now()
WHERE profile_key = ANY(ARRAY[
    'earnings-csgp-2026q2',
    'earnings-czr-2026q2',
    'earnings-f-2026q2',
    'earnings-nxpi-2026q2',
    'earnings-v-2026q3'
]);

DO $verify$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key = 'earnings-ups-2026q2'
          AND schedule.automation_mode = 'MANUAL'
          AND schedule.state = 'EXPIRED'
          AND profile.status = 'DISABLED'
          AND rule.status = 'DISABLED'
    ) OR NOT EXISTS (
        SELECT 1
        FROM earnings_release_catalog
        WHERE event_key = 'UPS:2026-07-28'
          AND schedule_status = 'REPORTED'
    ) THEN
        RAISE EXCEPTION 'UPS manual completion verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ANY(ARRAY[
            'earnings-rcl-2026q2',
            'earnings-ba-2026q2',
            'earnings-jblu-2026q2',
            'earnings-spgi-2026q2'
        ])
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'PENDING'
          AND profile.status = 'DISABLED'
          AND schedule.preflight_at = schedule.activate_at
    ) <> 4 THEN
        RAISE EXCEPTION 'pre-market recovery verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ANY(ARRAY[
            'earnings-csgp-2026q2',
            'earnings-czr-2026q2',
            'earnings-f-2026q2',
            'earnings-nxpi-2026q2',
            'earnings-v-2026q3'
        ])
          AND schedule.automation_mode = 'MANUAL'
          AND schedule.state = 'PENDING'
          AND profile.status = 'DISABLED'
    ) <> 5 THEN
        RAISE EXCEPTION 'post-market pause verification failed';
    END IF;
END
$verify$;

COMMIT;
