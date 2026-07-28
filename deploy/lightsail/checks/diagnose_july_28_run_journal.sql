BEGIN TRANSACTION READ ONLY;

SELECT format(
    'journal=%s:result=%s:execution=%s:latency=%s:direction=%s:price=%s/%s:quantity=%s:matched=%s:source_ms=%s:decision_ms=%s:exchange_ms=%s:error=%s',
    journal_key,
    overall_result,
    execution_status,
    latency_status,
    direction_status,
    coalesce(desired_price::text, 'none'),
    coalesce(effective_price::text, 'none'),
    coalesce(quantity::text, 'none'),
    coalesce(matched_quantity::text, 'none'),
    coalesce(source_latency_ms::text, 'none'),
    coalesce(decision_latency_ms::text, 'none'),
    coalesce(exchange_latency_ms::text, 'none'),
    coalesce(error_code, 'none')
)
FROM resolution_run_journal
WHERE journal_key IN (
    'earnings:UPS:2026Q2:2026-07-28',
    'earnings:HLT:2026Q2:2026-07-28',
    'earnings:RCL:2026Q2:2026-07-28',
    'earnings:KO:2026Q2:2026-07-28',
    'earnings:IVZ:2026Q2:2026-07-28'
)
ORDER BY journal_key;

SELECT format(
    'journal_events=%s',
    count(*)
)
FROM resolution_run_journal_events
WHERE event_key LIKE
    'run-journal:earnings:%:2026-07-28:initial-classification';

ROLLBACK;
