BEGIN;

DO $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM earnings_source_events
        WHERE scope_id = 'earnings:SPGI:2026Q2'
          AND provider = 'sec'
          AND status = 'QUARANTINED'
          AND error = 'document_encoding_invalid'
    ) OR EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:SPGI:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:SPGI:2026Q2'
    ) THEN
        RAISE EXCEPTION 'SPGI journal parser-error guard failed';
    END IF;
END
$guard$;

WITH event AS (
    SELECT *
    FROM earnings_source_events
    WHERE scope_id = 'earnings:SPGI:2026Q2'
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
    'earnings:SPGI:2026Q2:2026-07-28',
    'earnings:SPGI:2026Q2',
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
        'ticker', 'SPGI',
        'recovery_pending', true
    )
FROM resolution_execution_profiles AS profile
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = profile.profile_key
CROSS JOIN event
WHERE profile.profile_key = 'earnings-spgi-2026q2'
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
    'PARSER_QUARANTINED',
    'parse',
    journal.overall_result,
    journal.source_latency_ms,
    journal.error_code,
    jsonb_build_object(
        'execution_status', journal.execution_status,
        'latency_status', journal.latency_status,
        'direction_status', journal.direction_status
    ),
    journal.source_detected_at
FROM resolution_run_journal AS journal
WHERE journal.journal_key =
    'earnings:SPGI:2026Q2:2026-07-28'
ON CONFLICT (event_key) DO NOTHING;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key =
            'earnings:SPGI:2026Q2:2026-07-28'
          AND overall_result = 'ERROR'
          AND execution_status = 'NOT_ATTEMPTED'
          AND direction_status = 'UNKNOWN'
          AND error_stage = 'parse'
          AND error_code = 'document_encoding_invalid'
          AND details ->> 'recovery_pending' = 'true'
    ) <> 1 THEN
        RAISE EXCEPTION 'SPGI journal verification failed';
    END IF;
END
$verify$;

COMMIT;
