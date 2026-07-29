-- Verify the exact historical reconciliation without returning profile,
-- claim, order, source, market, account, event, or notification data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
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
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.metadata ->> 'block_id' = block_key
          AND schedule.profile_key = ANY(target_profiles)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'COMPLETED'
          AND profile.status = 'DISABLED'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->>
              'historical_reconciliation' = 'true'
          AND schedule.metadata ->>
              'existing_orders_left_unchanged' = 'true'
    ) <> cardinality(target_profiles) THEN
        RAISE EXCEPTION
            'July 29 reconciled profile state guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE profile_key = ANY(target_profiles)
          AND event_key LIKE
              'historical-complete:earnings-%:2026-07-29'
          AND previous_state IN ('ACTIVE', 'BLOCKED')
          AND next_state = 'COMPLETED'
          AND event_kind = 'RESOLUTION_EXECUTION_COMPLETED'
          AND reason_code =
              'historical_executed_claim_reconciled'
          AND metadata ->>
              'existing_orders_left_unchanged' = 'true'
    ) <> cardinality(target_profiles) THEN
        RAISE EXCEPTION
            'July 29 reconciliation audit event guard failed';
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
            'July 29 reconciled execution claim guard failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN resolution_execution_claims AS claim
          ON claim.scope_id = profile.scope_id
        WHERE schedule.metadata ->> 'block_id' = block_key
          AND schedule.state IN ('ACTIVE', 'BLOCKED')
          AND claim.status = 'EXECUTED'
    ) THEN
        RAISE EXCEPTION
            'July 29 historical completion gap remains';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE metadata ->> 'block_id' = block_key
          AND state = 'COMPLETED'
    ) <> cardinality(target_profiles) THEN
        RAISE EXCEPTION
            'Unexpected July 29 COMPLETED schedule set';
    END IF;
END
$verification$;

ROLLBACK;
