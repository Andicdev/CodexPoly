BEGIN;

DO $guard$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key = 'earnings:JBLU:2026Q2:2026-07-28'
          AND direction_status = 'CORRECT'
          AND execution_status = 'ACCEPTED_OPEN'
          AND overall_result = 'LATENCY_MISS'
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_order_observations AS observations
        JOIN resolution_order_groups AS groups
          ON groups.order_group_id = observations.order_group_id
        WHERE groups.template_id =
            'numeric_threshold:earnings-jblu-2026q2:YES'
          AND observations.remote_state = 'OPEN'
          AND observations.original_quantity = 50
          AND observations.matched_quantity = 16
          AND observations.remaining_quantity = 34
    ) < 1 OR (
        SELECT count(*)
        FROM resolution_order_group_orders AS orders
        JOIN resolution_order_groups AS groups
          ON groups.order_group_id = orders.order_group_id
        WHERE groups.template_id =
            'numeric_threshold:earnings-jblu-2026q2:YES'
          AND orders.status = 'LIVE'
          AND orders.effective_price = 0.999
          AND orders.quantity = 34
    ) <> 1 THEN
        RAISE EXCEPTION 'JBLU partial-fill journal guard failed';
    END IF;
END
$guard$;

WITH observed AS (
    SELECT
        observations.matched_quantity,
        observations.remaining_quantity,
        observations.observed_at
    FROM resolution_order_observations AS observations
    JOIN resolution_order_groups AS groups
      ON groups.order_group_id = observations.order_group_id
    WHERE groups.template_id =
        'numeric_threshold:earnings-jblu-2026q2:YES'
      AND observations.matched_quantity > 0
    ORDER BY
        observations.observed_at DESC,
        observations.created_at DESC
    LIMIT 1
)
UPDATE resolution_run_journal AS journal
SET
    execution_status = 'PARTIALLY_FILLED',
    overall_result = 'SUCCESS',
    matched_quantity = observed.matched_quantity,
    last_order_observed_at = observed.observed_at,
    classification_reason =
        'correct_direction_partial_fill_with_slow_open_remainder',
    details = journal.details || jsonb_build_object(
        'matched_quantity', observed.matched_quantity,
        'remaining_quantity', observed.remaining_quantity,
        'fill_evidence', 'resolution_order_observations',
        'open_remainder_at_slow_price', true
    ),
    updated_at = now()
FROM observed
WHERE journal.journal_key =
    'earnings:JBLU:2026Q2:2026-07-28';

INSERT INTO resolution_run_journal_events (
    event_key,
    journal_id,
    event_kind,
    stage,
    event_status,
    details,
    occurred_at
)
SELECT
    'run-journal:earnings:JBLU:2026Q2:2026-07-28:partial-fill-16',
    journal.id,
    'PARTIAL_FILL_OBSERVED',
    'execution',
    'PARTIALLY_FILLED',
    jsonb_build_object(
        'matched_quantity', observations.matched_quantity,
        'remaining_quantity', observations.remaining_quantity,
        'remote_state', observations.remote_state,
        'remote_status', observations.remote_status,
        'open_remainder_at_slow_price', true
    ),
    observations.observed_at
FROM resolution_run_journal AS journal
JOIN resolution_order_groups AS groups
  ON groups.template_id =
      'numeric_threshold:earnings-jblu-2026q2:YES'
JOIN resolution_order_observations AS observations
  ON observations.order_group_id = groups.order_group_id
WHERE journal.journal_key =
    'earnings:JBLU:2026Q2:2026-07-28'
  AND observations.matched_quantity = 16
  AND observations.remaining_quantity = 34
ORDER BY observations.observed_at DESC
LIMIT 1
ON CONFLICT (event_key) DO NOTHING;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key = 'earnings:JBLU:2026Q2:2026-07-28'
          AND overall_result = 'SUCCESS'
          AND execution_status = 'PARTIALLY_FILLED'
          AND latency_status = 'TOO_SLOW'
          AND direction_status = 'CORRECT'
          AND quantity = 50
          AND matched_quantity = 16
          AND effective_price = 0.999
          AND finalized_at IS NULL
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_run_journal_events
        WHERE event_key =
            'run-journal:earnings:JBLU:2026Q2:2026-07-28:partial-fill-16'
          AND event_kind = 'PARTIAL_FILL_OBSERVED'
          AND event_status = 'PARTIALLY_FILLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'JBLU partial-fill journal verification failed';
    END IF;
END
$verify$;

COMMIT;
