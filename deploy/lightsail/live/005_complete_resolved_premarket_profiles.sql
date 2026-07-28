BEGIN;

DO $guard$
DECLARE
    resolved_profiles CONSTANT text[] := ARRAY[
        'earnings-hlt-2026q2',
        'earnings-rcl-2026q2'
    ];
    resolved_scopes CONSTANT text[] := ARRAY[
        'earnings:HLT:2026Q2',
        'earnings:RCL:2026Q2'
    ];
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key = ANY(resolved_profiles)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND profile.status = 'ENABLED'
          AND rule.status = 'SHADOW'
          AND schedule.metadata ->> 'live_block' = 'PRE_MARKET'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-28-pre-market'
    ) <> cardinality(resolved_profiles) THEN
        RAISE EXCEPTION 'resolved pre-market profile guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(resolved_scopes)
          AND status = 'EXECUTED'
          AND result ->> 'attempted' = 'true'
          AND result ->> 'accepted' = 'true'
          AND jsonb_typeof(result -> 'order_ids') = 'array'
          AND jsonb_array_length(result -> 'order_ids') = 1
    ) <> cardinality(resolved_scopes) OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(resolved_scopes)
          AND status = 'EXPIRED'
          AND result ->> 'attempted' = 'false'
    ) <> cardinality(resolved_scopes) OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(resolved_scopes)
    ) <> cardinality(resolved_scopes) * 2 THEN
        RAISE EXCEPTION 'resolved pre-market execution claim guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key IN (
            'HLT:2026-07-28',
            'RCL:2026-07-28'
        )
    ) <> cardinality(resolved_profiles) THEN
        RAISE EXCEPTION 'resolved pre-market catalog guard failed';
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
    'manual-complete:' || lower(profile.scope_id)
        || ':2026-07-28',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'EXPIRED',
    'RESOLUTION_EXECUTION_COMPLETED',
    'accepted_order_left_unchanged',
    jsonb_build_object(
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-28-pre-market',
        'accepted_order_left_unchanged', true
    )
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.profile_key IN (
    'earnings-hlt-2026q2',
    'earnings-rcl-2026q2'
)
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
        'completed_after_execution', true,
        'accepted_order_left_unchanged', true
    ),
    updated_at = now()
WHERE profile_key IN (
    'earnings-hlt-2026q2',
    'earnings-rcl-2026q2'
);

UPDATE resolution_execution_profiles
SET status = 'DISABLED', updated_at = now()
WHERE profile_key IN (
    'earnings-hlt-2026q2',
    'earnings-rcl-2026q2'
);

UPDATE earnings_market_rules
SET status = 'DISABLED', updated_at = now()
WHERE scope_id IN (
    'earnings:HLT:2026Q2',
    'earnings:RCL:2026Q2'
);

UPDATE earnings_release_catalog
SET schedule_status = 'REPORTED', updated_at = now()
WHERE event_key IN (
    'HLT:2026-07-28',
    'RCL:2026-07-28'
);

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key IN (
            'earnings-hlt-2026q2',
            'earnings-rcl-2026q2'
        )
          AND schedule.automation_mode = 'MANUAL'
          AND schedule.state = 'EXPIRED'
          AND profile.status = 'DISABLED'
          AND rule.status = 'DISABLED'
          AND schedule.metadata ->>
              'accepted_order_left_unchanged' = 'true'
    ) <> 2 OR (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key IN (
            'HLT:2026-07-28',
            'RCL:2026-07-28'
        )
          AND schedule_status = 'REPORTED'
    ) <> 2 THEN
        RAISE EXCEPTION 'resolved pre-market completion verification failed';
    END IF;
END
$verify$;

COMMIT;
