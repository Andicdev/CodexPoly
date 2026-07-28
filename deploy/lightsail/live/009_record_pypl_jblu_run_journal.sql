BEGIN;

DO $guard$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:PYPL:2026Q2',
            'earnings:JBLU:2026Q2'
        )
          AND outcome = 'YES'
          AND status = 'EXECUTED'
          AND effective_price = 0.99
          AND result ->> 'accepted' = 'true'
    ) <> 2 OR (
        SELECT count(DISTINCT groups.template_id)
        FROM resolution_order_groups AS groups
        JOIN resolution_order_group_orders AS orders
          ON orders.order_group_id = groups.order_group_id
        WHERE groups.template_id IN (
            'numeric_threshold:earnings-pypl-2026q2:YES',
            'numeric_threshold:earnings-jblu-2026q2:YES'
        )
          AND groups.status IN ('ACTIVE', 'COMPLETED')
          AND orders.status = 'LIVE'
    ) <> 2 THEN
        RAISE EXCEPTION 'PYPL/JBLU journal execution guard failed';
    END IF;
END
$guard$;

WITH target (scope_id, profile_key) AS (
    VALUES
        ('earnings:PYPL:2026Q2', 'earnings-pypl-2026q2'),
        ('earnings:JBLU:2026Q2', 'earnings-jblu-2026q2')
),
fact AS (
    SELECT DISTINCT ON (candidate.scope_id)
        candidate.scope_id,
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
    JOIN target
      ON target.scope_id = candidate.scope_id
    WHERE candidate.status = 'VALIDATED'
    ORDER BY candidate.scope_id, candidate.detected_at, candidate.id
),
claim AS (
    SELECT
        claims.scope_id,
        claims.id,
        claims.outcome,
        claims.desired_price,
        claims.effective_price,
        claims.quantity,
        claims.created_at,
        claims.completed_at
    FROM resolution_execution_claims AS claims
    JOIN target
      ON target.scope_id = claims.scope_id
    WHERE claims.status = 'EXECUTED'
),
current_order AS (
    SELECT DISTINCT ON (profile.profile_key)
        profile.profile_key,
        groups.status AS group_status,
        groups.reprice_count,
        orders.effective_price,
        orders.quantity,
        orders.opened_at
    FROM target
    JOIN resolution_execution_profiles AS profile
      ON profile.profile_key = target.profile_key
    JOIN resolution_order_groups AS groups
      ON groups.template_id =
          'numeric_threshold:' || profile.profile_key || ':YES'
    JOIN resolution_order_group_orders AS orders
      ON orders.order_group_id = groups.order_group_id
    WHERE orders.status = 'LIVE'
    ORDER BY
        profile.profile_key,
        orders.generation DESC,
        orders.id DESC
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
    target.scope_id || ':2026-07-28',
    target.scope_id,
    target.profile_key,
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
    coalesce(current_order.effective_price, claim.effective_price),
    current_order.quantity,
    0,
    fact.published_at,
    fact.detected_at,
    claim.created_at,
    claim.completed_at,
    current_order.opened_at,
    current_order.opened_at,
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
    CASE
        WHEN coalesce(
            current_order.effective_price,
            claim.effective_price
        ) = 0.999
            THEN 'accepted_order_remained_open_at_0_999'
        ELSE 'accepted_order_remained_open_at_0_99'
    END,
    jsonb_build_object(
        'ticker', rule.ticker,
        'fact_value', fact.value,
        'initial_effective_price', claim.effective_price,
        'current_effective_price',
            coalesce(
                current_order.effective_price,
                claim.effective_price
            ),
        'reprice_count', current_order.reprice_count,
        'group_status', current_order.group_status,
        'accepted_order_left_unchanged', true
    )
FROM target
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = target.profile_key
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = target.profile_key
JOIN earnings_market_rules AS rule
  ON rule.scope_id = target.scope_id
JOIN fact
  ON fact.scope_id = target.scope_id
JOIN claim
  ON claim.scope_id = target.scope_id
JOIN current_order
  ON current_order.profile_key = target.profile_key
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
WHERE journal.journal_key IN (
    'earnings:PYPL:2026Q2:2026-07-28',
    'earnings:JBLU:2026Q2:2026-07-28'
)
ON CONFLICT (event_key) DO NOTHING;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key IN (
            'earnings:PYPL:2026Q2:2026-07-28',
            'earnings:JBLU:2026Q2:2026-07-28'
        )
          AND overall_result = 'LATENCY_MISS'
          AND execution_status = 'ACCEPTED_OPEN'
          AND latency_status = 'TOO_SLOW'
          AND direction_status = 'CORRECT'
          AND desired_price = 0.999
          AND effective_price IN (0.99, 0.999)
          AND matched_quantity = 0
    ) <> 2 THEN
        RAISE EXCEPTION 'PYPL/JBLU journal verification failed';
    END IF;
END
$verify$;

COMMIT;
