-- Read-only source inventory for July 29 IR parser replay.

BEGIN TRANSACTION READ ONLY;

SELECT format(
    'ticker=%s,provider=%s,event_id=%s,status=%s,source_url=%s,filing_url=%s,filed_at=%s,received_at=%s',
    event.ticker,
    event.provider,
    event.id,
    event.status,
    event.source_url,
    event.filing_url,
    event.filed_at,
    event.received_at
)
FROM earnings_source_events AS event
WHERE event.scope_id IN (
    'earnings:CBRE:2026Q2',
    'earnings:WING:2026Q2',
    'earnings:IART:2026Q2'
)
ORDER BY event.ticker, event.received_at, event.id;

ROLLBACK;
