BEGIN;

DO $guard$
BEGIN
    IF to_regclass('resolution_run_journal') IS NULL
       OR to_regclass('resolution_run_journal_events') IS NULL THEN
        RAISE EXCEPTION 'resolution run journal schema is missing';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key IN (
            'earnings-ups-2026q2',
            'earnings-hlt-2026q2',
            'earnings-rcl-2026q2'
        )
          AND schedule.automation_mode = 'MANUAL'
          AND schedule.state = 'EXPIRED'
          AND profile.status = 'DISABLED'
          AND rule.status = 'DISABLED'
          AND schedule.metadata ->> 'live_block' = 'PRE_MARKET'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-28-pre-market'
    ) <> 3 THEN
        RAISE EXCEPTION 'July 28 journal profile guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:HLT:2026Q2',
            'earnings:RCL:2026Q2'
        )
          AND status = 'EXECUTED'
          AND result ->> 'attempted' = 'true'
          AND result ->> 'accepted' = 'true'
    ) <> 2 OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:UPS:2026Q2'
    ) THEN
        RAISE EXCEPTION 'July 28 journal claim guard failed';
    END IF;
END
$guard$;

WITH target (
    scope_id,
    profile_key,
    ticker,
    overall_result,
    execution_status,
    latency_status,
    direction_status,
    first_order_observed_at,
    classification_reason,
    error_stage,
    error_code,
    errors
) AS (
    VALUES
        (
            'earnings:UPS:2026Q2',
            'earnings-ups-2026q2',
            'UPS',
            'MISSED_EXECUTION',
            'NOT_ATTEMPTED',
            'UNKNOWN',
            'CORRECT',
            NULL::timestamptz,
            'validated_fact_without_execution_claim',
            'profile_activation',
            'live_profile_preparation_failed',
            jsonb_build_array(
                jsonb_build_object(
                    'stage', 'profile_activation',
                    'code', 'live_profile_preparation_failed'
                )
            )
        ),
        (
            'earnings:HLT:2026Q2',
            'earnings-hlt-2026q2',
            'HLT',
            'LATENCY_MISS',
            'ACCEPTED_OPEN',
            'TOO_SLOW',
            'CORRECT',
            TIMESTAMPTZ '2026-07-28 10:47:35.045574+00',
            'accepted_order_remained_open_at_0_999',
            'parse',
            'conflicting_hilton_adjusted_diluted_eps_values',
            jsonb_build_array(
                jsonb_build_object(
                    'stage', 'parse',
                    'provider', 'sec',
                    'code',
                    'conflicting_hilton_adjusted_diluted_eps_values'
                )
            )
        ),
        (
            'earnings:RCL:2026Q2',
            'earnings-rcl-2026q2',
            'RCL',
            'LATENCY_MISS',
            'ACCEPTED_OPEN',
            'TOO_SLOW',
            'CORRECT',
            TIMESTAMPTZ '2026-07-28 10:47:14.508970+00',
            'accepted_order_remained_open_at_0_999',
            NULL::text,
            NULL::text,
            '[]'::jsonb
        )
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
    WHERE candidate.scope_id IN (
        'earnings:UPS:2026Q2',
        'earnings:HLT:2026Q2',
        'earnings:RCL:2026Q2'
    )
      AND candidate.status = 'VALIDATED'
    ORDER BY candidate.scope_id, candidate.detected_at, candidate.id
),
claim AS (
    SELECT
        scope_id,
        id,
        outcome,
        desired_price,
        effective_price,
        quantity,
        created_at,
        completed_at
    FROM resolution_execution_claims
    WHERE scope_id IN (
        'earnings:HLT:2026Q2',
        'earnings:RCL:2026Q2'
    )
      AND status = 'EXECUTED'
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
    error_stage,
    error_code,
    errors,
    classification_reason,
    details,
    finalized_at
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
    CASE
        WHEN claim.id IS NULL THEN NULL
        ELSE 'resolution_execution_claims:' || claim.id
    END,
    schedule.metadata ->> 'live_block',
    schedule.metadata ->> 'block_id',
    coalesce(claim.outcome, 'YES'),
    target.direction_status,
    target.execution_status,
    target.latency_status,
    target.overall_result,
    coalesce(claim.desired_price, profile.yes_desired_price),
    claim.effective_price,
    coalesce(claim.quantity, profile.quantity),
    CASE WHEN claim.id IS NULL THEN NULL ELSE 0 END,
    fact.published_at,
    fact.detected_at,
    claim.created_at,
    claim.completed_at,
    target.first_order_observed_at,
    target.first_order_observed_at,
    round(
        extract(epoch FROM (
            fact.detected_at - fact.published_at
        )) * 1000
    )::bigint,
    CASE
        WHEN claim.id IS NULL THEN NULL
        ELSE round(
            extract(epoch FROM (
                claim.created_at - fact.detected_at
            )) * 1000
        )::bigint
    END,
    CASE
        WHEN claim.completed_at IS NULL THEN NULL
        ELSE round(
            extract(epoch FROM (
                claim.completed_at - claim.created_at
            )) * 1000
        )::bigint
    END,
    fact.source_url,
    profile.source_reference,
    target.error_stage,
    target.error_code,
    target.errors,
    target.classification_reason,
    jsonb_build_object(
        'ticker', target.ticker,
        'comparison_op', rule.comparison_op,
        'strike', rule.strike,
        'fact_value', fact.value,
        'accepted_order_left_unchanged', claim.id IS NOT NULL
    ),
    CASE
        WHEN target.overall_result = 'MISSED_EXECUTION'
            THEN now()
        ELSE NULL
    END
FROM target
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = target.profile_key
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = target.profile_key
JOIN earnings_market_rules AS rule
  ON rule.scope_id = target.scope_id
JOIN fact
  ON fact.scope_id = target.scope_id
LEFT JOIN claim
  ON claim.scope_id = target.scope_id
ON CONFLICT (journal_key) DO UPDATE
SET
    execution_status = EXCLUDED.execution_status,
    latency_status = EXCLUDED.latency_status,
    overall_result = EXCLUDED.overall_result,
    matched_quantity = EXCLUDED.matched_quantity,
    last_order_observed_at = EXCLUDED.last_order_observed_at,
    error_stage = EXCLUDED.error_stage,
    error_code = EXCLUDED.error_code,
    errors = EXCLUDED.errors,
    classification_reason = EXCLUDED.classification_reason,
    details = EXCLUDED.details,
    finalized_at = EXCLUDED.finalized_at,
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
    'INITIAL_CLASSIFICATION',
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
        journal.finalized_at,
        journal.updated_at
    )
FROM resolution_run_journal AS journal
WHERE journal.journal_key IN (
    'earnings:UPS:2026Q2:2026-07-28',
    'earnings:HLT:2026Q2:2026-07-28',
    'earnings:RCL:2026Q2:2026-07-28'
)
ON CONFLICT (event_key) DO NOTHING;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key IN (
            'earnings:UPS:2026Q2:2026-07-28',
            'earnings:HLT:2026Q2:2026-07-28',
            'earnings:RCL:2026Q2:2026-07-28'
        )
          AND direction_status = 'CORRECT'
          AND live_block = 'PRE_MARKET'
          AND block_id = '2026-07-28-pre-market'
    ) <> 3 OR (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key IN (
            'earnings:HLT:2026Q2:2026-07-28',
            'earnings:RCL:2026Q2:2026-07-28'
        )
          AND overall_result = 'LATENCY_MISS'
          AND execution_status = 'ACCEPTED_OPEN'
          AND latency_status = 'TOO_SLOW'
          AND desired_price = 0.999
          AND effective_price = 0.999
          AND matched_quantity = 0
    ) <> 2 OR NOT EXISTS (
        SELECT 1
        FROM resolution_run_journal
        WHERE journal_key =
            'earnings:UPS:2026Q2:2026-07-28'
          AND overall_result = 'MISSED_EXECUTION'
          AND execution_status = 'NOT_ATTEMPTED'
          AND error_code = 'live_profile_preparation_failed'
    ) OR (
        SELECT count(*)
        FROM resolution_run_journal_events
        WHERE event_key LIKE
            'run-journal:earnings:%:2026-07-28:initial-classification'
    ) <> 3 THEN
        RAISE EXCEPTION 'July 28 run journal verification failed';
    END IF;
END
$verify$;

COMMIT;
