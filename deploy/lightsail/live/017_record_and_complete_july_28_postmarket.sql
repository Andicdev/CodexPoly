BEGIN;

DO $guard$
DECLARE
    target_profiles CONSTANT text[] := ARRAY[
        'earnings-csgp-2026q2',
        'earnings-czr-2026q2',
        'earnings-f-2026q2',
        'earnings-nxpi-2026q2',
        'earnings-v-2026q3'
    ];
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key = ANY(target_profiles)
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state = 'ACTIVE'
          AND profile.status = 'ENABLED'
          AND rule.status = 'SHADOW'
          AND schedule.metadata ->> 'live_block' = 'POST_MARKET'
          AND schedule.metadata ->> 'block_id' =
              '2026-07-28-post-market'
    ) <> cardinality(target_profiles) THEN
        RAISE EXCEPTION 'post-market completion profile guard failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:CZR:2026Q2',
            'earnings:NXPI:2026Q2',
            'earnings:V:2026Q3'
        )
          AND status = 'EXECUTED'
          AND result ->> 'attempted' = 'true'
          AND result ->> 'accepted' = 'true'
    ) <> 3 OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:CSGP:2026Q2',
            'earnings:F:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'post-market completion claim guard failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_source_events
        WHERE scope_id = 'earnings:CSGP:2026Q2'
          AND status = 'QUARANTINED'
          AND error =
              'conflicting_costar_gaap_diluted_eps_values'
    ) OR EXISTS (
        SELECT 1
        FROM earnings_source_events
        WHERE scope_id = 'earnings:F:2026Q2'
    ) THEN
        RAISE EXCEPTION 'post-market source miss guard failed';
    END IF;
END
$guard$;

WITH target (
    scope_id,
    profile_key,
    ticker,
    selected_outcome,
    execution_status,
    latency_status,
    overall_result,
    classification_reason,
    error_stage,
    error_code,
    reviewed_value,
    reviewed_source_url,
    reviewed_published_at
) AS (
    VALUES
        (
            'earnings:CSGP:2026Q2',
            'earnings-csgp-2026q2',
            'CSGP',
            'YES',
            'NOT_ATTEMPTED',
            'UNKNOWN',
            'MISSED_EXECUTION',
            'parser_quarantined_valid_official_result',
            'parse',
            'conflicting_costar_gaap_diluted_eps_values',
            0.14::numeric,
            NULL::text,
            NULL::timestamptz
        ),
        (
            'earnings:CZR:2026Q2',
            'earnings-czr-2026q2',
            'CZR',
            'NO',
            'ACCEPTED_OPEN',
            'TOO_SLOW',
            'LATENCY_MISS',
            'correct_no_order_remained_open_at_0_999',
            NULL::text,
            NULL::text,
            NULL::numeric,
            NULL::text,
            NULL::timestamptz
        ),
        (
            'earnings:F:2026Q2',
            'earnings-f-2026q2',
            'F',
            'YES',
            'NOT_ATTEMPTED',
            'UNKNOWN',
            'MISSED_EXECUTION',
            'official_ir_pdf_source_was_not_configured',
            'source',
            'official_ir_source_missing',
            0.42::numeric,
            'https://s205.q4cdn.com/882619693/files/'
                'doc_financials/2026/q2/'
                'Ford-Motor-Company-Q2-2026-Press-Release.pdf',
            TIMESTAMPTZ '2026-07-28 20:06:18+00'
        ),
        (
            'earnings:NXPI:2026Q2',
            'earnings-nxpi-2026q2',
            'NXPI',
            'YES',
            'ACCEPTED_OPEN',
            'TOO_SLOW',
            'LATENCY_MISS',
            'correct_yes_order_remained_open_at_0_999',
            NULL::text,
            NULL::text,
            NULL::numeric,
            NULL::text,
            NULL::timestamptz
        ),
        (
            'earnings:V:2026Q3',
            'earnings-v-2026q3',
            'V',
            'YES',
            'ACCEPTED_OPEN',
            'TOO_SLOW',
            'LATENCY_MISS',
            'correct_yes_order_remained_open_at_0_999',
            NULL::text,
            NULL::text,
            NULL::numeric,
            NULL::text,
            NULL::timestamptz
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
        candidate.detected_at
    FROM earnings_fact_candidates AS candidate
    WHERE candidate.scope_id IN (
        'earnings:CZR:2026Q2',
        'earnings:NXPI:2026Q2',
        'earnings:V:2026Q3'
    )
      AND candidate.status IN ('VALIDATED', 'EMITTED')
    ORDER BY candidate.scope_id, candidate.detected_at, candidate.id
),
source_event AS (
    SELECT DISTINCT ON (event.scope_id)
        event.scope_id,
        event.id,
        event.provider,
        event.source_url,
        event.filed_at,
        event.received_at
    FROM earnings_source_events AS event
    WHERE event.scope_id IN (
        'earnings:CSGP:2026Q2',
        'earnings:CZR:2026Q2',
        'earnings:NXPI:2026Q2',
        'earnings:V:2026Q3'
    )
    ORDER BY event.scope_id, event.received_at, event.id
),
claim AS (
    SELECT DISTINCT ON (execution.scope_id)
        execution.scope_id,
        execution.id,
        execution.outcome,
        execution.desired_price,
        execution.effective_price,
        execution.quantity,
        execution.created_at,
        execution.completed_at
    FROM resolution_execution_claims AS execution
    WHERE execution.scope_id IN (
        'earnings:CZR:2026Q2',
        'earnings:NXPI:2026Q2',
        'earnings:V:2026Q3'
    )
      AND execution.status = 'EXECUTED'
    ORDER BY execution.scope_id, execution.created_at, execution.id
),
orders AS (
    SELECT
        profile.scope_id,
        min(order_row.opened_at) AS first_opened_at,
        max(order_row.opened_at) AS last_opened_at,
        max(order_row.effective_price)
            FILTER (WHERE order_row.status = 'LIVE')
            AS live_effective_price,
        max(order_row.quantity)
            FILTER (WHERE order_row.status = 'LIVE')
            AS live_quantity,
        coalesce(max(observation.matched_quantity), 0)
            AS matched_quantity
    FROM resolution_execution_profiles AS profile
    JOIN resolution_order_groups AS groups
      ON groups.condition_id = profile.condition_id
    JOIN resolution_order_group_orders AS order_row
      ON order_row.order_group_id = groups.order_group_id
    LEFT JOIN resolution_order_observations AS observation
      ON observation.order_group_id = groups.order_group_id
    WHERE profile.scope_id IN (
        'earnings:CZR:2026Q2',
        'earnings:NXPI:2026Q2',
        'earnings:V:2026Q3'
    )
      AND groups.created_at >=
          TIMESTAMPTZ '2026-07-28 18:00:00+00'
    GROUP BY profile.scope_id
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
    coalesce(fact.provider, source_event.provider, 'company_ir'),
    CASE
        WHEN coalesce(fact.source_event_id, source_event.id) IS NULL
            THEN NULL
        ELSE 'earnings_source_events:'
            || coalesce(fact.source_event_id, source_event.id)
    END,
    CASE
        WHEN fact.id IS NULL THEN NULL
        ELSE 'earnings_fact_candidates:' || fact.id
    END,
    CASE
        WHEN claim.id IS NULL THEN NULL
        ELSE 'resolution_execution_claims:' || claim.id
    END,
    schedule.metadata ->> 'live_block',
    schedule.metadata ->> 'block_id',
    target.selected_outcome,
    'CORRECT',
    target.execution_status,
    target.latency_status,
    target.overall_result,
    coalesce(
        claim.desired_price,
        CASE target.selected_outcome
            WHEN 'YES' THEN profile.yes_desired_price
            ELSE profile.no_desired_price
        END
    ),
    orders.live_effective_price,
    coalesce(claim.quantity, profile.quantity),
    CASE
        WHEN claim.id IS NULL THEN NULL
        ELSE orders.matched_quantity
    END,
    coalesce(
        fact.published_at,
        source_event.filed_at,
        target.reviewed_published_at
    ),
    coalesce(fact.detected_at, source_event.received_at),
    claim.created_at,
    claim.completed_at,
    orders.first_opened_at,
    orders.last_opened_at,
    CASE
        WHEN coalesce(fact.detected_at, source_event.received_at) IS NULL
          OR coalesce(
                fact.published_at,
                source_event.filed_at,
                target.reviewed_published_at
            ) IS NULL
            THEN NULL
        ELSE round(
            extract(epoch FROM (
                coalesce(fact.detected_at, source_event.received_at)
                - coalesce(
                    fact.published_at,
                    source_event.filed_at,
                    target.reviewed_published_at
                )
            )) * 1000
        )::bigint
    END,
    CASE
        WHEN claim.created_at IS NULL OR fact.detected_at IS NULL
            THEN NULL
        ELSE round(
            extract(epoch FROM (
                claim.created_at - fact.detected_at
            )) * 1000
        )::bigint
    END,
    CASE
        WHEN claim.completed_at IS NULL OR claim.created_at IS NULL
            THEN NULL
        ELSE round(
            extract(epoch FROM (
                claim.completed_at - claim.created_at
            )) * 1000
        )::bigint
    END,
    coalesce(target.reviewed_source_url, source_event.source_url),
    profile.source_reference,
    target.error_stage,
    target.error_code,
    CASE
        WHEN target.error_code IS NULL THEN '[]'::jsonb
        ELSE jsonb_build_array(
            jsonb_build_object(
                'stage', target.error_stage,
                'code', target.error_code
            )
        )
    END,
    target.classification_reason,
    jsonb_build_object(
        'ticker', target.ticker,
        'comparison_op', rule.comparison_op,
        'strike', rule.strike,
        'fact_value', coalesce(fact.value, target.reviewed_value),
        'initial_effective_price', claim.effective_price,
        'current_effective_price', orders.live_effective_price,
        'accepted_order_left_unchanged', claim.id IS NOT NULL,
        'reviewed_after_block', true
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
LEFT JOIN fact
  ON fact.scope_id = target.scope_id
LEFT JOIN source_event
  ON source_event.scope_id = target.scope_id
LEFT JOIN claim
  ON claim.scope_id = target.scope_id
LEFT JOIN orders
  ON orders.scope_id = target.scope_id
ON CONFLICT (journal_key) DO UPDATE
SET
    source_provider = EXCLUDED.source_provider,
    source_event_ref = EXCLUDED.source_event_ref,
    fact_ref = EXCLUDED.fact_ref,
    execution_claim_ref = EXCLUDED.execution_claim_ref,
    selected_outcome = EXCLUDED.selected_outcome,
    direction_status = EXCLUDED.direction_status,
    execution_status = EXCLUDED.execution_status,
    latency_status = EXCLUDED.latency_status,
    overall_result = EXCLUDED.overall_result,
    desired_price = EXCLUDED.desired_price,
    effective_price = EXCLUDED.effective_price,
    quantity = EXCLUDED.quantity,
    matched_quantity = EXCLUDED.matched_quantity,
    source_published_at = EXCLUDED.source_published_at,
    source_detected_at = EXCLUDED.source_detected_at,
    claim_created_at = EXCLUDED.claim_created_at,
    exchange_completed_at = EXCLUDED.exchange_completed_at,
    first_order_observed_at = EXCLUDED.first_order_observed_at,
    last_order_observed_at = EXCLUDED.last_order_observed_at,
    source_latency_ms = EXCLUDED.source_latency_ms,
    decision_latency_ms = EXCLUDED.decision_latency_ms,
    exchange_latency_ms = EXCLUDED.exchange_latency_ms,
    source_url = EXCLUDED.source_url,
    market_url = EXCLUDED.market_url,
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
        journal.source_detected_at,
        journal.finalized_at,
        now()
    )
FROM resolution_run_journal AS journal
WHERE journal.journal_key IN (
    'earnings:CSGP:2026Q2:2026-07-28',
    'earnings:CZR:2026Q2:2026-07-28',
    'earnings:F:2026Q2:2026-07-28',
    'earnings:NXPI:2026Q2:2026-07-28',
    'earnings:V:2026Q3:2026-07-28'
)
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
    'manual-complete:' || lower(profile.scope_id)
        || ':2026-07-28',
    schedule.id,
    schedule.schedule_key,
    schedule.profile_key,
    schedule.state,
    'EXPIRED',
    'POSTMARKET_BLOCK_REVIEWED',
    CASE
        WHEN profile.scope_id IN (
            'earnings:CSGP:2026Q2',
            'earnings:F:2026Q2'
        ) THEN 'missed_execution_reviewed'
        ELSE 'accepted_order_left_unchanged'
    END,
    jsonb_build_object(
        'live_block', 'POST_MARKET',
        'block_id', '2026-07-28-post-market',
        'accepted_order_left_unchanged',
            profile.scope_id NOT IN (
                'earnings:CSGP:2026Q2',
                'earnings:F:2026Q2'
            )
    )
FROM resolution_profile_schedules AS schedule
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = schedule.profile_key
WHERE schedule.profile_key IN (
    'earnings-csgp-2026q2',
    'earnings-czr-2026q2',
    'earnings-f-2026q2',
    'earnings-nxpi-2026q2',
    'earnings-v-2026q3'
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
        'completed_after_review', true,
        'accepted_order_left_unchanged',
            profile_key IN (
                'earnings-czr-2026q2',
                'earnings-nxpi-2026q2',
                'earnings-v-2026q3'
            )
    ),
    updated_at = now()
WHERE profile_key IN (
    'earnings-csgp-2026q2',
    'earnings-czr-2026q2',
    'earnings-f-2026q2',
    'earnings-nxpi-2026q2',
    'earnings-v-2026q3'
);

UPDATE resolution_execution_profiles
SET status = 'DISABLED', updated_at = now()
WHERE profile_key IN (
    'earnings-csgp-2026q2',
    'earnings-czr-2026q2',
    'earnings-f-2026q2',
    'earnings-nxpi-2026q2',
    'earnings-v-2026q3'
);

UPDATE earnings_market_rules
SET
    source_policy = CASE
        WHEN scope_id = 'earnings:F:2026Q2' THEN
            source_policy || jsonb_build_object(
                'company_ir', jsonb_build_object(
                    'kind', 'direct_document',
                    'provider', 'company_ir',
                    'feed_url',
                        'https://s205.q4cdn.com/882619693/files/'
                        'doc_financials/2026/q2/'
                        'Ford-Motor-Company-Q2-2026-Press-Release.pdf',
                    'allowed_document_hosts',
                        jsonb_build_array('s205.q4cdn.com'),
                    'title_all',
                        jsonb_build_array(
                            'Ford',
                            'Second Quarter',
                            '2026',
                            'Press Release'
                        ),
                    'title_none', '[]'::jsonb
                )
            )
        ELSE source_policy
    END,
    status = 'DISABLED',
    updated_at = now()
WHERE scope_id IN (
    'earnings:CSGP:2026Q2',
    'earnings:CZR:2026Q2',
    'earnings:F:2026Q2',
    'earnings:NXPI:2026Q2',
    'earnings:V:2026Q3'
);

UPDATE earnings_release_catalog
SET schedule_status = 'REPORTED', updated_at = now()
WHERE event_key IN (
    'CSGP:2026-07-28',
    'CZR:2026-07-28',
    'F:2026-07-28',
    'NXPI:2026-07-28',
    'V:2026-07-28'
);

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key IN (
            'earnings:CSGP:2026Q2:2026-07-28',
            'earnings:CZR:2026Q2:2026-07-28',
            'earnings:F:2026Q2:2026-07-28',
            'earnings:NXPI:2026Q2:2026-07-28',
            'earnings:V:2026Q3:2026-07-28'
        )
          AND direction_status = 'CORRECT'
          AND live_block = 'POST_MARKET'
          AND block_id = '2026-07-28-post-market'
    ) <> 5 OR (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key IN (
            'earnings:CZR:2026Q2:2026-07-28',
            'earnings:NXPI:2026Q2:2026-07-28',
            'earnings:V:2026Q3:2026-07-28'
        )
          AND overall_result = 'LATENCY_MISS'
          AND execution_status = 'ACCEPTED_OPEN'
          AND latency_status = 'TOO_SLOW'
          AND effective_price = 0.999
          AND quantity = 100
          AND matched_quantity = 0
    ) <> 3 OR (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key IN (
            'earnings:CSGP:2026Q2:2026-07-28',
            'earnings:F:2026Q2:2026-07-28'
        )
          AND overall_result = 'MISSED_EXECUTION'
          AND execution_status = 'NOT_ATTEMPTED'
          AND error_code IS NOT NULL
    ) <> 2 OR (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.profile_key IN (
            'earnings-csgp-2026q2',
            'earnings-czr-2026q2',
            'earnings-f-2026q2',
            'earnings-nxpi-2026q2',
            'earnings-v-2026q3'
        )
          AND schedule.automation_mode = 'MANUAL'
          AND schedule.state = 'EXPIRED'
          AND profile.status = 'DISABLED'
          AND rule.status = 'DISABLED'
    ) <> 5 OR NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE scope_id = 'earnings:F:2026Q2'
          AND source_policy #>> '{company_ir,kind}' =
              'direct_document'
          AND source_policy #>> '{company_ir,feed_url}' =
              'https://s205.q4cdn.com/882619693/files/'
              'doc_financials/2026/q2/'
              'Ford-Motor-Company-Q2-2026-Press-Release.pdf'
    ) THEN
        RAISE EXCEPTION 'post-market completion verification failed';
    END IF;
END
$verify$;

COMMIT;
