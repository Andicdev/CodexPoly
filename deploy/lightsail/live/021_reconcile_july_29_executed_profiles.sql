-- Reconcile only the five July 29 profiles already proven by accepted,
-- terminal EXECUTED claims. Existing orders, claims, source facts, earnings
-- rules, release catalog rows, and run journal rows are left unchanged.

BEGIN;

DO $guard$
DECLARE
    block_key constant text := '2026-07-29-pre-market';
    target_profiles constant text[] := ARRAY[
        'earnings-sofi-2026q2',
        'earnings-pg-2026q4',
        'earnings-hum-2026q2',
        'earnings-iart-2026q2',
        'earnings-grmn-2026q2'
    ];
    target_scopes constant text[] := ARRAY[
        'earnings:SOFI:2026Q2',
        'earnings:PG:2026Q4',
        'earnings:HUM:2026Q2',
        'earnings:IART:2026Q2',
        'earnings:GRMN:2026Q2'
    ];
BEGIN
    PERFORM schedule.id
    FROM resolution_profile_schedules AS schedule
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = schedule.profile_key
    WHERE schedule.profile_key = ANY(target_profiles)
    ORDER BY schedule.id
    FOR UPDATE OF schedule, profile;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.metadata ->> 'block_id' = block_key
          AND schedule.profile_key = ANY(target_profiles)
          AND profile.scope_id = ANY(target_scopes)
          AND profile.source_name = 'earnings_resolution'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN (
              'ACTIVE',
              'BLOCKED',
              'COMPLETED'
          )
          AND (
              (
                  schedule.state = 'ACTIVE'
                  AND profile.status = 'ENABLED'
              )
              OR (
                  schedule.state IN ('BLOCKED', 'COMPLETED')
                  AND profile.status = 'DISABLED'
              )
          )
    ) <> cardinality(target_profiles) THEN
        RAISE EXCEPTION
            'July 29 reconciliation target state guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(target_scopes)
          AND status = 'EXECUTED'
          AND result ->> 'attempted' = 'true'
          AND result ->> 'accepted' = 'true'
          AND jsonb_typeof(result -> 'order_ids') = 'array'
          AND jsonb_array_length(result -> 'order_ids') = 1
    ) <> cardinality(target_scopes) OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(target_scopes)
          AND status = 'EXPIRED'
          AND result ->> 'attempted' = 'false'
    ) <> cardinality(target_scopes) OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(target_scopes)
    ) <> cardinality(target_scopes) * 2 THEN
        RAISE EXCEPTION
            'July 29 reconciliation execution claim guard failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN resolution_execution_claims AS claim
          ON claim.scope_id = profile.scope_id
        WHERE schedule.metadata ->> 'block_id' = block_key
          AND claim.status = 'EXECUTED'
          AND schedule.profile_key <> ALL(target_profiles)
    ) THEN
        RAISE EXCEPTION
            'Unexpected July 29 executed profile exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        WHERE schedule.profile_key = ANY(target_profiles)
          AND schedule.state = 'COMPLETED'
          AND NOT EXISTS (
              SELECT 1
              FROM resolution_profile_schedule_events AS event
              WHERE event.schedule_id = schedule.id
                AND event.event_key =
                    'historical-complete:'
                    || lower(schedule.profile_key)
                    || ':2026-07-29'
                AND event.previous_state IN ('ACTIVE', 'BLOCKED')
                AND event.next_state = 'COMPLETED'
                AND event.event_kind =
                    'RESOLUTION_EXECUTION_COMPLETED'
                AND event.reason_code =
                    'historical_executed_claim_reconciled'
          )
    ) THEN
        RAISE EXCEPTION
            'Existing July 29 completion audit guard failed';
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
    'historical-complete:'
        || lower(schedule.profile_key)
        || ':2026-07-29',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'COMPLETED',
    'RESOLUTION_EXECUTION_COMPLETED',
    'historical_executed_claim_reconciled',
    jsonb_build_object(
        'block_id', '2026-07-29-pre-market',
        'historical_reconciliation', true,
        'evidence', 'terminal_execution_claim',
        'existing_orders_left_unchanged', true
    )
FROM resolution_profile_schedules AS schedule
WHERE schedule.profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2'
)
  AND schedule.state IN ('ACTIVE', 'BLOCKED')
ON CONFLICT (event_key) DO NOTHING;

UPDATE resolution_execution_profiles
SET status = 'DISABLED', updated_at = now()
WHERE profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2'
)
  AND status <> 'DISABLED';

UPDATE resolution_profile_schedules
SET
    state = 'COMPLETED',
    last_error_code = NULL,
    metadata = metadata || jsonb_build_object(
        'historical_reconciliation', true,
        'reconciliation_reason',
            'historical_executed_claim_reconciled',
        'existing_orders_left_unchanged', true
    ),
    updated_at = now()
WHERE profile_key IN (
    'earnings-sofi-2026q2',
    'earnings-pg-2026q4',
    'earnings-hum-2026q2',
    'earnings-iart-2026q2',
    'earnings-grmn-2026q2'
)
  AND state IN ('ACTIVE', 'BLOCKED');

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key IN (
            'earnings-sofi-2026q2',
            'earnings-pg-2026q4',
            'earnings-hum-2026q2',
            'earnings-iart-2026q2',
            'earnings-grmn-2026q2'
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'COMPLETED'
          AND profile.status = 'DISABLED'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->>
              'historical_reconciliation' = 'true'
          AND schedule.metadata ->>
              'existing_orders_left_unchanged' = 'true'
    ) <> 5 OR (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key LIKE
              'historical-complete:earnings-%:2026-07-29'
          AND profile_key IN (
              'earnings-sofi-2026q2',
              'earnings-pg-2026q4',
              'earnings-hum-2026q2',
              'earnings-iart-2026q2',
              'earnings-grmn-2026q2'
          )
          AND previous_state IN ('ACTIVE', 'BLOCKED')
          AND next_state = 'COMPLETED'
          AND event_kind = 'RESOLUTION_EXECUTION_COMPLETED'
          AND reason_code =
              'historical_executed_claim_reconciled'
          AND metadata ->>
              'existing_orders_left_unchanged' = 'true'
    ) <> 5 THEN
        RAISE EXCEPTION
            'July 29 reconciliation verification failed';
    END IF;
END
$verify$;

COMMIT;
