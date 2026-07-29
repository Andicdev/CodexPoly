-- Finalize only the unresolved July 29 POST_MARKET journal rows. Source
-- facts, execution claims, tracked orders, and remote orders are untouched.

BEGIN;

DO $guard$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-hood-2026q2'
          AND schedule.state = 'COMPLETED'
          AND profile.status = 'DISABLED'
          AND schedule.metadata ->> 'investigation_required' = 'true'
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:HOOD:2026Q2'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) <> 0 THEN
        RAISE EXCEPTION 'HOOD journal finalization guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        WHERE schedule.profile_key = 'earnings-ea-2027q1'
          AND schedule.state = 'BLOCKED'
          AND schedule.last_error_code =
              'official_schedule_unconfirmed'
          AND profile.status = 'DISABLED'
    ) <> 1 OR EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:EA:2027Q1'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:EA:2027Q1'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) THEN
        RAISE EXCEPTION 'EA journal finalization guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key = 'earnings:WAY:2026Q2:2026-07-29'
          AND profile_key = 'earnings-way-2026q2'
          AND overall_result = 'SUCCESS'
          AND execution_status = 'FILLED'
          AND matched_quantity = quantity
    ) <> 1 THEN
        RAISE EXCEPTION 'WAY supervision audit guard failed';
    END IF;
END
$guard$;

UPDATE resolution_run_journal
SET
    direction_status = 'CORRECT',
    execution_status = 'NOT_ATTEMPTED',
    latency_status = 'UNKNOWN',
    overall_result = 'MISSED_EXECUTION',
    error_stage = 'readiness',
    error_code = 'authenticated_preflight_not_ready',
    errors = jsonb_build_array(
        jsonb_build_object(
            'stage', 'readiness',
            'code', 'authenticated_preflight_not_ready'
        )
    ),
    classification_reason =
        'manual_preflight_blocked_before_official_signal',
    details = details || jsonb_build_object(
        'validated_fact_present', true,
        'live_execution_claim_present', false,
        'order_group_present', false,
        'fresh_non_submitting_probe_ready', true,
        'reviewed_after_block', true
    ),
    finalized_at = now(),
    updated_at = now()
WHERE journal_key = 'earnings:HOOD:2026Q2:2026-07-29'
  AND profile_key = 'earnings-hood-2026q2'
  AND execution_status = 'NOT_ATTEMPTED'
  AND overall_result = 'PENDING';

INSERT INTO resolution_run_journal (
    journal_key,
    scope_id,
    profile_key,
    schedule_key,
    source_kind,
    live_block,
    block_id,
    direction_status,
    execution_status,
    latency_status,
    overall_result,
    quantity,
    market_url,
    error_stage,
    error_code,
    errors,
    classification_reason,
    details,
    finalized_at
)
SELECT
    'earnings:EA:2027Q1:2026-07-29',
    profile.scope_id,
    profile.profile_key,
    schedule.schedule_key,
    'earnings',
    schedule.metadata ->> 'live_block',
    schedule.metadata ->> 'block_id',
    'UNKNOWN',
    'NOT_ATTEMPTED',
    'UNKNOWN',
    'ERROR',
    profile.quantity,
    profile.source_reference,
    'schedule',
    'official_schedule_unconfirmed',
    jsonb_build_array(
        jsonb_build_object(
            'stage', 'schedule',
            'code', 'official_schedule_unconfirmed'
        )
    ),
    'manual_official_schedule_unconfirmed',
    jsonb_build_object(
        'validated_fact_present', false,
        'live_execution_claim_present', false,
        'order_group_present', false,
        'fail_closed', true,
        'reviewed_after_block', true
    ),
    now()
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
WHERE profile.profile_key = 'earnings-ea-2027q1'
ON CONFLICT (journal_key) DO UPDATE
SET
    direction_status = EXCLUDED.direction_status,
    execution_status = EXCLUDED.execution_status,
    latency_status = EXCLUDED.latency_status,
    overall_result = EXCLUDED.overall_result,
    quantity = EXCLUDED.quantity,
    market_url = EXCLUDED.market_url,
    error_stage = EXCLUDED.error_stage,
    error_code = EXCLUDED.error_code,
    errors = EXCLUDED.errors,
    classification_reason = EXCLUDED.classification_reason,
    details = EXCLUDED.details,
    finalized_at = EXCLUDED.finalized_at,
    updated_at = now();

UPDATE resolution_run_journal
SET
    error_stage = 'supervision',
    error_code = 'delayed_tick_replacement_after_source_fill',
    errors = errors || jsonb_build_array(
        jsonb_build_object(
            'stage', 'supervision',
            'code', 'delayed_tick_replacement_after_source_fill'
        )
    ),
    classification_reason =
        'automatic_fill_observed_with_supervision_incident',
    details = details || jsonb_build_object(
        'source_order_filled', true,
        'delayed_tick_observed', true,
        'replacement_remote_open_at_review', true,
        'replacement_order_left_unchanged', true,
        'operator_action_required', true
    ),
    updated_at = now()
WHERE journal_key = 'earnings:WAY:2026Q2:2026-07-29'
  AND profile_key = 'earnings-way-2026q2'
  AND overall_result = 'SUCCESS'
  AND execution_status = 'FILLED';

INSERT INTO resolution_run_journal_events (
    event_key,
    journal_id,
    event_kind,
    stage,
    event_status,
    error_code,
    details,
    occurred_at
)
SELECT
    'postmarket-review:hood:2026-07-29',
    id,
    'POSTMARKET_REVIEW',
    'readiness',
    'MISSED_EXECUTION',
    'authenticated_preflight_not_ready',
    jsonb_build_object(
        'validated_fact_present', true,
        'execution_attempted', false
    ),
    now()
FROM resolution_run_journal
WHERE journal_key = 'earnings:HOOD:2026Q2:2026-07-29'
ON CONFLICT (event_key) DO NOTHING;

INSERT INTO resolution_run_journal_events (
    event_key,
    journal_id,
    event_kind,
    stage,
    event_status,
    error_code,
    details,
    occurred_at
)
SELECT
    'postmarket-review:ea:2026-07-29',
    id,
    'POSTMARKET_REVIEW',
    'schedule',
    'BLOCKED',
    'official_schedule_unconfirmed',
    jsonb_build_object(
        'validated_fact_present', false,
        'execution_attempted', false
    ),
    now()
FROM resolution_run_journal
WHERE journal_key = 'earnings:EA:2027Q1:2026-07-29'
ON CONFLICT (event_key) DO NOTHING;

INSERT INTO resolution_run_journal_events (
    event_key,
    journal_id,
    event_kind,
    stage,
    event_status,
    error_code,
    details,
    occurred_at
)
SELECT
    'postmarket-review:way-supervision:2026-07-29',
    id,
    'POSTMARKET_REVIEW',
    'supervision',
    'FAILED',
    'delayed_tick_replacement_after_source_fill',
    jsonb_build_object(
        'initial_execution_success', true,
        'replacement_order_left_unchanged', true,
        'operator_action_required', true
    ),
    TIMESTAMPTZ '2026-07-29 20:10:26.671+00'
FROM resolution_run_journal
WHERE journal_key = 'earnings:WAY:2026Q2:2026-07-29'
ON CONFLICT (event_key) DO NOTHING;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key = 'earnings:HOOD:2026Q2:2026-07-29'
          AND overall_result = 'MISSED_EXECUTION'
          AND execution_status = 'NOT_ATTEMPTED'
          AND error_code = 'authenticated_preflight_not_ready'
          AND finalized_at IS NOT NULL
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key = 'earnings:EA:2027Q1:2026-07-29'
          AND overall_result = 'ERROR'
          AND execution_status = 'NOT_ATTEMPTED'
          AND error_code = 'official_schedule_unconfirmed'
          AND finalized_at IS NOT NULL
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key = 'earnings:WAY:2026Q2:2026-07-29'
          AND overall_result = 'SUCCESS'
          AND error_code =
              'delayed_tick_replacement_after_source_fill'
          AND details ->> 'operator_action_required' = 'true'
    ) <> 1 THEN
        RAISE EXCEPTION 'July 29 POST_MARKET journal verification failed';
    END IF;
END
$verify$;

COMMIT;
