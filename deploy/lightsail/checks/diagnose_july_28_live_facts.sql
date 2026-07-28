BEGIN TRANSACTION READ ONLY;

SELECT format(
    'fact=%s:%s:%s',
    ticker,
    status,
    count(*)
)
FROM earnings_fact_candidates
WHERE scope_id IN (
    'earnings:HLT:2026Q2',
    'earnings:IVZ:2026Q2',
    'earnings:KO:2026Q2',
    'earnings:PYPL:2026Q2',
    'earnings:UPS:2026Q2',
    'earnings:RCL:2026Q2',
    'earnings:JBLU:2026Q2',
    'earnings:SPGI:2026Q2',
    'earnings:CSGP:2026Q2',
    'earnings:CZR:2026Q2',
    'earnings:F:2026Q2',
    'earnings:NXPI:2026Q2',
    'earnings:V:2026Q3'
)
GROUP BY ticker, status
ORDER BY ticker, status;

SELECT format(
    'event=%s:%s:%s:%s',
    ticker,
    provider,
    status,
    count(*)
)
FROM earnings_source_events
WHERE scope_id IN (
    'earnings:HLT:2026Q2',
    'earnings:IVZ:2026Q2',
    'earnings:KO:2026Q2',
    'earnings:PYPL:2026Q2',
    'earnings:UPS:2026Q2',
    'earnings:RCL:2026Q2',
    'earnings:JBLU:2026Q2',
    'earnings:SPGI:2026Q2',
    'earnings:CSGP:2026Q2',
    'earnings:CZR:2026Q2',
    'earnings:F:2026Q2',
    'earnings:NXPI:2026Q2',
    'earnings:V:2026Q3'
)
GROUP BY ticker, provider, status
ORDER BY ticker, provider, status;

SELECT format(
    'claim=%s:%s:%s',
    scope_id,
    status,
    count(*)
)
FROM resolution_execution_claims
WHERE scope_id IN (
    'earnings:HLT:2026Q2',
    'earnings:IVZ:2026Q2',
    'earnings:KO:2026Q2',
    'earnings:PYPL:2026Q2',
    'earnings:UPS:2026Q2',
    'earnings:RCL:2026Q2',
    'earnings:JBLU:2026Q2',
    'earnings:SPGI:2026Q2',
    'earnings:CSGP:2026Q2',
    'earnings:CZR:2026Q2',
    'earnings:F:2026Q2',
    'earnings:NXPI:2026Q2',
    'earnings:V:2026Q3'
)
GROUP BY scope_id, status
ORDER BY scope_id, status;

ROLLBACK;
