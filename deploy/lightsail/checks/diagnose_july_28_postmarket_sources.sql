BEGIN TRANSACTION READ ONLY;

SELECT format(
    'source=%s:sec=%s:company_ir=%s:company_feed=%s:wire=%s:wire_feed=%s',
    ticker,
    source_policy ? 'sec',
    coalesce(source_policy #>> '{company_ir,provider}', 'none'),
    coalesce(source_policy #>> '{company_ir,feed_url}', 'none'),
    coalesce(source_policy #>> '{press_wire,provider}', 'none'),
    coalesce(source_policy #>> '{press_wire,feed_url}', 'none')
)
FROM earnings_market_rules
WHERE scope_id IN (
    'earnings:CSGP:2026Q2',
    'earnings:CZR:2026Q2',
    'earnings:F:2026Q2',
    'earnings:NXPI:2026Q2',
    'earnings:V:2026Q3'
)
ORDER BY ticker;

ROLLBACK;
