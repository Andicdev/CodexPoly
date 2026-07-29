-- Close the already-published HOOD event without inventing an execution,
-- and fail closed for the unconfirmed EA schedule. Facts and all historical
-- execution/order evidence remain untouched for the post-market audit.

BEGIN;

DO $guard$
DECLARE
    hood_profile constant text := 'earnings-hood-2026q2';
    hood_scope constant text := 'earnings:HOOD:2026Q2';
    ea_profile constant text := 'earnings-ea-2027q1';
    ea_scope constant text := 'earnings:EA:2027Q1';
BEGIN
    PERFORM schedule.id
    FROM resolution_profile_schedules AS schedule
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = schedule.profile_key
    WHERE schedule.profile_key IN (hood_profile, ea_profile)
    ORDER BY schedule.id
    FOR UPDATE OF schedule, profile;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = hood_profile
          AND profile.scope_id = hood_scope
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-hood-post-market'
          AND schedule.state <> 'EXPIRED'
          AND profile.status IN ('ENABLED', 'DISABLED')
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD lifecycle close guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_fact_candidates
        WHERE scope_id = hood_scope
          AND ticker = 'HOOD'
          AND metric_kind = 'gaap_eps'
          AND provider = 'sec'
          AND value = 0.62
          AND status IN ('VALIDATED', 'EMITTED')
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD validated fact guard failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = hood_scope
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) OR EXISTS (
        SELECT 1
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        WHERE profile.profile_key = hood_profile
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
    ) THEN
        RAISE EXCEPTION 'HOOD unexpected execution evidence exists';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = ea_profile
          AND profile.scope_id = ea_scope
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-ea-post-market'
          AND schedule.metadata ->> 'schedule_basis' =
              'market_active_no_official_call'
          AND schedule.state NOT IN ('COMPLETED', 'EXPIRED')
          AND profile.status IN ('ENABLED', 'DISABLED')
    ) <> 1 THEN
        RAISE EXCEPTION 'EA lifecycle block guard failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = ea_scope
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ea_scope
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) OR EXISTS (
        SELECT 1
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        WHERE profile.profile_key = ea_profile
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
    ) THEN
        RAISE EXCEPTION 'EA unexpected live evidence exists';
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
    'postmarket-close:earnings-hood-2026q2:2026-07-29',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'COMPLETED',
    'POST_EVENT_RECONCILIATION_COMPLETED',
    'official_result_observed_execution_missing',
    jsonb_build_object(
        'block_id', '2026-07-29-hood-post-market',
        'validated_fact_present', true,
        'live_execution_claim_present', false,
        'preflight_claims_left_unchanged', true,
        'order_group_present', false,
        'investigation_required', true,
        'existing_orders_left_unchanged', true
    )
FROM resolution_profile_schedules AS schedule
WHERE schedule.profile_key = 'earnings-hood-2026q2'
  AND schedule.state NOT IN ('COMPLETED', 'EXPIRED')
ON CONFLICT (event_key) DO NOTHING;

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
    'schedule-block:earnings-ea-2027q1:2026-07-29',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'BLOCKED',
    'OFFICIAL_SCHEDULE_BLOCKED',
    'official_schedule_unconfirmed',
    jsonb_build_object(
        'block_id', '2026-07-29-ea-post-market',
        'schedule_basis', 'market_active_no_official_call',
        'validated_fact_present', false,
        'live_execution_claim_present', false,
        'preflight_claims_left_unchanged', true,
        'order_group_present', false,
        'fail_closed', true
    )
FROM resolution_profile_schedules AS schedule
WHERE schedule.profile_key = 'earnings-ea-2027q1'
  AND schedule.state NOT IN ('COMPLETED', 'EXPIRED')
ON CONFLICT (event_key) DO NOTHING;

UPDATE resolution_execution_profiles
SET status = 'DISABLED', updated_at = now()
WHERE profile_key IN (
    'earnings-hood-2026q2',
    'earnings-ea-2027q1'
)
  AND status = 'ENABLED';

UPDATE resolution_profile_schedules
SET
    state = 'COMPLETED',
    last_error_code = NULL,
    metadata = metadata || jsonb_build_object(
        'completion_reason',
            'official_result_observed_execution_missing',
        'validated_fact_present', true,
        'live_execution_claim_present', false,
        'preflight_claims_left_unchanged', true,
        'order_group_present', false,
        'investigation_required', true
    ),
    updated_at = now()
WHERE profile_key = 'earnings-hood-2026q2'
  AND state NOT IN ('COMPLETED', 'EXPIRED');

UPDATE resolution_profile_schedules
SET
    state = 'BLOCKED',
    last_error_code = 'official_schedule_unconfirmed',
    metadata = metadata || jsonb_build_object(
        'block_reason', 'official_schedule_unconfirmed',
        'validated_fact_present', false,
        'live_execution_claim_present', false,
        'preflight_claims_left_unchanged', true,
        'order_group_present', false,
        'fail_closed', true
    ),
    updated_at = now()
WHERE profile_key = 'earnings-ea-2027q1'
  AND state NOT IN ('COMPLETED', 'EXPIRED');

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-hood-2026q2'
          AND schedule.state = 'COMPLETED'
          AND profile.status = 'DISABLED'
          AND schedule.last_error_code IS NULL
          AND schedule.metadata ->> 'investigation_required' =
              'true'
          AND schedule.metadata ->> 'live_execution_claim_present' =
              'false'
          AND schedule.metadata ->> 'order_group_present' =
              'false'
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key =
              'postmarket-close:earnings-hood-2026q2:2026-07-29'
          AND previous_state IN (
              'PENDING',
              'PREFLIGHTING',
              'READY',
              'ACTIVE',
              'BLOCKED'
          )
          AND next_state = 'COMPLETED'
          AND reason_code =
              'official_result_observed_execution_missing'
    ) <> 1 THEN
        RAISE EXCEPTION 'HOOD lifecycle close verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-ea-2027q1'
          AND schedule.state = 'BLOCKED'
          AND profile.status = 'DISABLED'
          AND schedule.last_error_code =
              'official_schedule_unconfirmed'
          AND schedule.metadata ->> 'fail_closed' = 'true'
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_profile_schedule_events
        WHERE event_key =
              'schedule-block:earnings-ea-2027q1:2026-07-29'
          AND previous_state IN (
              'PENDING',
              'PREFLIGHTING',
              'READY',
              'ACTIVE',
              'BLOCKED'
          )
          AND next_state = 'BLOCKED'
          AND reason_code = 'official_schedule_unconfirmed'
    ) <> 1 THEN
        RAISE EXCEPTION 'EA lifecycle block verification failed';
    END IF;
END
$verify$;

COMMIT;
