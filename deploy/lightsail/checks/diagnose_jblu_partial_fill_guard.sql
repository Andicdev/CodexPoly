BEGIN TRANSACTION READ ONLY;

SELECT format(
    'jblu_partial_fill_guard:journal=%s:observation=%s:live_order=%s:event=%s',
    (
        SELECT count(*)
        FROM resolution_run_journal
        WHERE journal_key = 'earnings:JBLU:2026Q2:2026-07-28'
          AND direction_status = 'CORRECT'
          AND execution_status = 'ACCEPTED_OPEN'
          AND overall_result = 'LATENCY_MISS'
    ),
    (
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
    ),
    (
        SELECT count(*)
        FROM resolution_order_group_orders AS orders
        JOIN resolution_order_groups AS groups
          ON groups.order_group_id = orders.order_group_id
        WHERE groups.template_id =
            'numeric_threshold:earnings-jblu-2026q2:YES'
          AND orders.status = 'LIVE'
          AND orders.effective_price = 0.999
          AND orders.quantity = 34
    ),
    (
        SELECT count(*)
        FROM resolution_run_journal_events
        WHERE event_key =
            'run-journal:earnings:JBLU:2026Q2:2026-07-28:partial-fill-16'
    )
);

ROLLBACK;
