BEGIN TRANSACTION READ ONLY;

SELECT format(
    'event=%s:%s:%s:filed=%s:received=%s:created=%s:error=%s:source=%s',
    ticker,
    provider,
    status,
    filed_at,
    received_at,
    created_at,
    CASE
        WHEN error IS NULL THEN 'none'
        WHEN error ~ '^[a-z0-9_]+$' THEN error
        ELSE 'redacted'
    END,
    source_url
)
FROM earnings_source_events
WHERE scope_id IN (
    'earnings:PYPL:2026Q2',
    'earnings:UPS:2026Q2',
    'earnings:HLT:2026Q2',
    'earnings:IVZ:2026Q2',
    'earnings:KO:2026Q2',
    'earnings:RCL:2026Q2',
    'earnings:BA:2026Q2',
    'earnings:JBLU:2026Q2',
    'earnings:SPGI:2026Q2'
)
ORDER BY created_at, ticker;

SELECT format(
    'fact=%s:%s:%s:value=%s:published=%s:detected=%s:created=%s',
    ticker,
    provider,
    status,
    value,
    published_at,
    detected_at,
    created_at
)
FROM earnings_fact_candidates
WHERE scope_id IN (
    'earnings:PYPL:2026Q2',
    'earnings:UPS:2026Q2',
    'earnings:HLT:2026Q2',
    'earnings:IVZ:2026Q2',
    'earnings:KO:2026Q2',
    'earnings:RCL:2026Q2',
    'earnings:BA:2026Q2',
    'earnings:JBLU:2026Q2',
    'earnings:SPGI:2026Q2'
)
ORDER BY created_at, ticker;

SELECT format(
    'claim=%s:%s:%s:price=%s:qty=%s:attempted=%s:accepted=%s:created=%s:completed=%s',
    scope_id,
    outcome,
    status,
    effective_price,
    quantity,
    coalesce(result ->> 'attempted', 'none'),
    coalesce(result ->> 'accepted', 'none'),
    created_at,
    coalesce(completed_at::text, 'none')
)
FROM resolution_execution_claims
WHERE scope_id IN (
    'earnings:PYPL:2026Q2',
    'earnings:UPS:2026Q2',
    'earnings:HLT:2026Q2',
    'earnings:IVZ:2026Q2',
    'earnings:KO:2026Q2',
    'earnings:RCL:2026Q2',
    'earnings:BA:2026Q2',
    'earnings:JBLU:2026Q2',
    'earnings:SPGI:2026Q2'
)
ORDER BY created_at, scope_id, outcome;

SELECT format(
    'group=%s:%s:%s:price=%s:qty=%s:reprices=%s:created=%s:updated=%s',
    coalesce(template_id, 'none'),
    outcome,
    status,
    desired_price,
    quantity,
    reprice_count,
    created_at,
    updated_at
)
FROM resolution_order_groups
WHERE template_id LIKE 'numeric_threshold:earnings-%-2026q2:%'
ORDER BY created_at, template_id;

SELECT format(
    'order=%s:%s:price=%s:qty=%s:opened=%s:closed=%s',
    groups.template_id,
    orders.status,
    orders.effective_price,
    orders.quantity,
    orders.opened_at,
    coalesce(orders.closed_at::text, 'none')
)
FROM resolution_order_group_orders AS orders
JOIN resolution_order_groups AS groups
  ON groups.order_group_id = orders.order_group_id
WHERE groups.template_id LIKE 'numeric_threshold:earnings-%-2026q2:%'
ORDER BY orders.opened_at, groups.template_id;

ROLLBACK;
