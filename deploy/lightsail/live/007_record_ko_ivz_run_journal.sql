BEGIN;

DO $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:KO:2026Q2'
          AND outcome = 'YES'
          AND status = 'EXECUTED'
          AND effective_price = 0.99
          AND result ->> 'accepted' = 'true'
    ) OR NOT EXISTS (
        SELECT 1
        FROM resolution_order_groups AS groups
        JOIN resolution_order_group_orders AS orders
          ON orders.order_group_id = groups.order_group_id
        WHERE groups.template_id =
            'numeric_threshold:earnings-ko-2026q2:YES'
          AND groups.status = 'COMPLETED'
          AND groups.reprice_count = 1
          AND orders.status = 'LIVE'
          AND orders.effective_price = 0.999
    ) THEN
        RAISE EXCEPTION 'KO journal execution guard failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_source_events
        WHERE scope_id = 'earnings:IVZ:2026Q2'
          AND provider = 'sec'
          AND status = 'QUARANTINED'
          AND error = 'document_encoding_invalid'
    ) OR EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:IVZ:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:IVZ:2026Q2'
    ) THEN
        RAISE EXCEPTION 'IVZ journal parser-error guard failed';
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
    WHERE candidate.scope_id = 'earnings:KO:2026Q2'
      AND candidate.status = 'VALIDATED'
    ORDER BY candidate.detected_at, candidate.id
    LIMIT 1
),
claim AS (
    SELECT *
    FROM resolution_execution_claims
    WHERE scope_id = 'earnings:KO:2026Q2'
      AND status = 'EXECUTED'
    ORDER BY id
    LIMIT 1
),
live_order AS (
    SELECT
        orders.effective_price,
        orders.quantity,
        orders.opened_at,
        groups.reprice_count
    FROM resolution_order_groups AS groups
    JOIN resolution_order_group_orders AS orders
      ON orders.order_group_id = groups.order_group_id
    WHERE groups.template_id =
        'numeric_threshold:earnings-ko-2026q2:YES'
      AND orders.status = 'LIVE'
    ORDER BY orders.generation DESC, orders.id DESC
    LIMIT 1
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
    'earnings:KO:2026Q2:2026-07-28',
    'earnings:KO:2026Q2',
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
    live_order.effective_price,
    live_order.quantity,
    0,
    fact.published_at,
    fact.detected_at,
    claim.created_at,
    claim.completed_at,
    live_order.opened_at,
    live_order.opened_at,
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
    'repriced_order_remained_open_at_0_999',
    jsonb_build_object(
        'ticker', 'KO',
        'fact_value', fact.value,
        'initial_effective_price', claim.effective_price,
        'current_effective_price', live_order.effective_price,
        'reprice_count', live_order.reprice_count,
        'accepted_order_left_unchanged', true
    )
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
CROSS JOIN fact
CROSS JOIN claim
CROSS JOIN live_order
WHERE profile.profile_key = 'earnings-ko-2026q2'
ON CONFLICT (journal_key) DO UPDATE
SET
    execution_status = EXCLUDED.execution_status,
    latency_status = EXCLUDED.latency_status,
    overall_result = EXCLUDED.overall_result,
    effective_price = EXCLUDED.effective_price,
    matched_quantity = EXCLUDED.matched_quantity,
    last_order_observed_at = EXCLUDED.last_order_observed_at,
    classification_reason = EXCLUDED.classification_reason,
    details = EXCLUDED.details,
    updated_at = now();

WITH event AS (
    SELECT *
    FROM earnings_source_events
    WHERE scope_id = 'earnings:IVZ:2026Q2'
      AND provider = 'sec'
      AND status = 'QUARANTINED'
      AND error = 'document_encoding_invalid'
    ORDER BY received_at, id
    LIMIT 1
)
INSERT INTO resolution_run_journal (
    journal_key,
    scope_id,
    profile_key,
    schedule_key,
    source_kind,
    source_provider,
    source_event_ref,
    live_block,
    block_id,
    direction_status,
    execution_status,
    latency_status,
    overall_result,
    source_published_at,
    source_detected_at,
    source_latency_ms,
    source_url,
    market_url,
    error_stage,
    error_code,
    errors,
    classification_reason,
    details
)
SELECT
    'earnings:IVZ:2026Q2:2026-07-28',
    'earnings:IVZ:2026Q2',
    profile.profile_key,
    schedule.schedule_key,
    'earnings',
    event.provider,
    'earnings_source_events:' || event.id,
    schedule.metadata ->> 'live_block',
    schedule.metadata ->> 'block_id',
    'UNKNOWN',
    'NOT_ATTEMPTED',
    'UNKNOWN',
    'ERROR',
    event.filed_at,
    event.received_at,
    round(
        extract(epoch FROM (
            event.received_at - event.filed_at
        )) * 1000
    )::bigint,
    event.source_url,
    profile.source_reference,
    'parse',
    event.error,
    jsonb_build_array(
        jsonb_build_object(
            'stage', 'parse',
            'provider', event.provider,
            'code', event.error
        )
    ),
    'sec_document_quarantined_before_fact',
    jsonb_build_object(
        'ticker', 'IVZ',
        'recovery_pending', true
    )
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
CROSS JOIN event
WHERE profile.profile_key = 'earnings-ivz-2026q2'
ON CONFLICT (journal_key) DO UPDATE
SET
    execution_status = EXCLUDED.execution_status,
    overall_result = EXCLUDED.overall_result,
    source_detected_at = EXCLUDED.source_detected_at,
    source_latency_ms = EXCLUDED.source_latency_ms,
    error_stage = EXCLUDED.error_stage,
    error_code = EXCLUDED.error_code,
    errors = EXCLUDED.errors,
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
    error_code,
    details,
    occurred_at
)
SELECT
    'run-journal:' || journal.journal_key
        || ':initial-classification',
    journal.id,
    CASE
        WHEN journal.scope_id = 'earnings:IVZ:2026Q2'
            THEN 'PARSER_QUARANTINED'
        ELSE 'INITIAL_CLASSIFICATION'
    END,
    coalesce(journal.error_stage, 'execution'),
    journal.overall_result,
    journal.source_latency_ms,
    journal.error_code,
    jsonb_build_object(
        'execution_status', journal.execution_status,
        'latency_status', journal.latency_status,
        'direction_status', journal.direction_status
    ),
    coalesce(
        journal.last_order_observed_at,
        journal.source_detected_at,
        journal.updated_at
    )
FROM resolution_run_journal AS journal
WHERE journal.journal_key IN (
    'earnings:KO:2026Q2:2026-07-28',
    'earnings:IVZ:2026Q2:2026-07-28'
)
ON CONFLICT (event_key) DO NOTHING;

DO $verify$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_run_journal
        WHERE journal_key =
            'earnings:KO:2026Q2:2026-07-28'
          AND overall_result = 'LATENCY_MISS'
          AND execution_status = 'ACCEPTED_OPEN'
          AND latency_status = 'TOO_SLOW'
          AND direction_status = 'CORRECT'
          AND desired_price = 0.999
          AND effective_price = 0.999
          AND matched_quantity = 0
    ) OR NOT EXISTS (
        SELECT 1
        FROM resolution_run_journal
        WHERE journal_key =
            'earnings:IVZ:2026Q2:2026-07-28'
          AND overall_result = 'ERROR'
          AND execution_status = 'NOT_ATTEMPTED'
          AND direction_status = 'UNKNOWN'
          AND error_stage = 'parse'
          AND error_code = 'document_encoding_invalid'
          AND details ->> 'recovery_pending' = 'true'
    ) THEN
        RAISE EXCEPTION 'KO/IVZ journal verification failed';
    END IF;
END
$verify$;

COMMIT;
