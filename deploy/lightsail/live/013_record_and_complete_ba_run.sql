BEGIN;

DO $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:BA:2026Q2'
          AND outcome = 'NO'
          AND status = 'EXECUTED'
          AND effective_price = 0.99
          AND result ->> 'accepted' = 'true'
    ) OR NOT EXISTS (
        SELECT 1
        FROM resolution_order_groups AS groups
        JOIN resolution_order_group_orders AS orders
          ON orders.order_group_id = groups.order_group_id
        WHERE groups.template_id =
            'numeric_threshold:earnings-ba-2026q2:NO'
          AND groups.status = 'COMPLETED'
          AND groups.reprice_count = 1
          AND orders.status = 'LIVE'
          AND orders.effective_price = 0.999
          AND orders.quantity = 50
    ) OR NOT EXISTS (
        SELECT 1
        FROM resolution_order_observations AS observations
        JOIN resolution_order_groups AS groups
          ON groups.order_group_id = observations.order_group_id
        WHERE groups.template_id =
            'numeric_threshold:earnings-ba-2026q2:NO'
          AND observations.original_quantity = 50
          AND observations.matched_quantity = 0
          AND observations.remaining_quantity = 50
    ) THEN
        RAISE EXCEPTION 'BA journal execution guard failed';
    END IF;
END
$guard$;

WITH fact AS (
    SELECT
        candidate.id,
        candidate.source_event_id,
        candidate.provider,
        candidate.value,
        candidate.published_at,
        candidate.detected_at,
        event.source_url
    FROM earnings_fact_candidates AS candidate
    JOIN earnings_source_events AS event
      ON event.id = candidate.source_event_id
    WHERE candidate.scope_id = 'earnings:BA:2026Q2'
      AND candidate.status = 'VALIDATED'
    ORDER BY candidate.detected_at, candidate.id
    LIMIT 1
),
claim AS (
    SELECT *
    FROM resolution_execution_claims
    WHERE scope_id = 'earnings:BA:2026Q2'
      AND status = 'EXECUTED'
    ORDER BY id
    LIMIT 1
),
orders AS (
    SELECT
        min(order_rows.opened_at) AS first_opened_at,
        max(order_rows.opened_at) AS last_opened_at,
        max(order_rows.effective_price)
            FILTER (WHERE order_rows.status = 'LIVE')
            AS live_effective_price,
        max(order_rows.quantity)
            FILTER (WHERE order_rows.status = 'LIVE')
            AS live_quantity
    FROM resolution_order_groups AS groups
    JOIN resolution_order_group_orders AS order_rows
      ON order_rows.order_group_id = groups.order_group_id
    WHERE groups.template_id =
        'numeric_threshold:earnings-ba-2026q2:NO'
)
INSERT INTO resolution_run_journal (
    journal_key,
    scope_id,
    profile_key,
    schedule_key,
    source_kind,
    source_provider,
    source_event_ref,
    fact_ref,
    execution_claim_ref,
    live_block,
    block_id,
    selected_outcome,
    direction_status,
    execution_status,
    latency_status,
    overall_result,
    desired_price,
    effective_price,
    quantity,
    matched_quantity,
    source_published_at,
    source_detected_at,
    claim_created_at,
    exchange_completed_at,
    first_order_observed_at,
    last_order_observed_at,
    source_latency_ms,
    decision_latency_ms,
    exchange_latency_ms,
    source_url,
    market_url,
    errors,
    classification_reason,
    details
)
SELECT
    'earnings:BA:2026Q2:2026-07-28',
    'earnings:BA:2026Q2',
    profile.profile_key,
    schedule.schedule_key,
    'earnings',
    fact.provider,
    'earnings_source_events:' || fact.source_event_id,
    'earnings_fact_candidates:' || fact.id,
    'resolution_execution_claims:' || claim.id,
    schedule.metadata ->> 'live_block',
    schedule.metadata ->> 'block_id',
    claim.outcome,
    'CORRECT',
    'ACCEPTED_OPEN',
    'TOO_SLOW',
    'LATENCY_MISS',
    claim.desired_price,
    orders.live_effective_price,
    claim.quantity,
    0,
    fact.published_at,
    fact.detected_at,
    claim.created_at,
    claim.completed_at,
    orders.first_opened_at,
    orders.last_opened_at,
    round(
        extract(epoch FROM (
            fact.detected_at - fact.published_at
        )) * 1000
    )::bigint,
    round(
        extract(epoch FROM (
            claim.created_at - fact.detected_at
        )) * 1000
    )::bigint,
    round(
        extract(epoch FROM (
            claim.completed_at - claim.created_at
        )) * 1000
    )::bigint,
    fact.source_url,
    profile.source_reference,
    '[]'::jsonb,
    'correct_no_order_remained_open_at_0_999',
    jsonb_build_object(
        'ticker', 'BA',
        'fact_value', fact.value,
        'initial_effective_price', claim.effective_price,
        'current_effective_price', orders.live_effective_price,
        'reprice_count', 1,
        'accepted_order_left_unchanged', true
    )
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
CROSS JOIN fact
CROSS JOIN claim
CROSS JOIN orders
WHERE profile.profile_key = 'earnings-ba-2026q2'
ON CONFLICT (journal_key) DO UPDATE
SET
    direction_status = EXCLUDED.direction_status,
    execution_status = EXCLUDED.execution_status,
    latency_status = EXCLUDED.latency_status,
    overall_result = EXCLUDED.overall_result,
    effective_price = EXCLUDED.effective_price,
    quantity = EXCLUDED.quantity,
    matched_quantity = EXCLUDED.matched_quantity,
    first_order_observed_at = EXCLUDED.first_order_observed_at,
    last_order_observed_at = EXCLUDED.last_order_observed_at,
    classification_reason = EXCLUDED.classification_reason,
    details = EXCLUDED.details,
    updated_at = now();

INSERT INTO resolution_run_journal_events (
    event_key,
    journal_id,
    event_kind,
    stage,
    event_status,
    latency_ms,
    details,
    occurred_at
)
SELECT
    'run-journal:' || journal.journal_key
        || ':initial-classification',
    journal.id,
    'INITIAL_CLASSIFICATION',
    'execution',
    journal.overall_result,
    journal.source_latency_ms,
    jsonb_build_object(
        'execution_status', journal.execution_status,
        'latency_status', journal.latency_status,
        'direction_status', journal.direction_status
    ),
    journal.last_order_observed_at
FROM resolution_run_journal AS journal
WHERE journal.journal_key =
    'earnings:BA:2026Q2:2026-07-28'
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
    'manual-complete:earnings:ba:2026q2:2026-07-28',
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
WHERE schedule.profile_key = 'earnings-ba-2026q2'
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
WHERE profile_key = 'earnings-ba-2026q2';

UPDATE resolution_execution_profiles
SET status = 'DISABLED', updated_at = now()
WHERE profile_key = 'earnings-ba-2026q2';

UPDATE earnings_market_rules
SET status = 'DISABLED', updated_at = now()
WHERE scope_id = 'earnings:BA:2026Q2';

UPDATE earnings_release_catalog
SET schedule_status = 'REPORTED', updated_at = now()
WHERE event_key = 'BA:2026-07-28';

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key = 'earnings:BA:2026Q2:2026-07-28'
          AND overall_result = 'LATENCY_MISS'
          AND execution_status = 'ACCEPTED_OPEN'
          AND latency_status = 'TOO_SLOW'
          AND direction_status = 'CORRECT'
          AND selected_outcome = 'NO'
          AND desired_price = 0.999
          AND effective_price = 0.999
          AND quantity = 50
          AND matched_quantity = 0
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key = 'earnings-ba-2026q2'
          AND schedule.automation_mode = 'MANUAL'
          AND schedule.state = 'EXPIRED'
          AND profile.status = 'DISABLED'
          AND rule.status = 'DISABLED'
          AND schedule.metadata ->>
              'accepted_order_left_unchanged' = 'true'
    ) <> 1 THEN
        RAISE EXCEPTION 'BA run journal verification failed';
    END IF;
END
$verify$;

COMMIT;
