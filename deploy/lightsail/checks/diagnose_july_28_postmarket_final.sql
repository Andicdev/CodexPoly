BEGIN TRANSACTION READ ONLY;

WITH scopes(scope_id) AS (
    VALUES
        ('earnings:CSGP:2026Q2'),
        ('earnings:CZR:2026Q2'),
        ('earnings:F:2026Q2'),
        ('earnings:NXPI:2026Q2'),
        ('earnings:V:2026Q3')
)
SELECT format(
    'fact=%s:provider=%s:value=%s:published=%s:detected=%s',
    scope.scope_id,
    coalesce(fact.provider, 'none'),
    coalesce(fact.value::text, 'none'),
    coalesce(
        to_char(
            fact.published_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
        ),
        'none'
    ),
    coalesce(
        to_char(
            fact.detected_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
        ),
        'none'
    )
)
FROM scopes AS scope
LEFT JOIN LATERAL (
    SELECT
        provider,
        value,
        published_at,
        detected_at
    FROM earnings_fact_candidates
    WHERE scope_id = scope.scope_id
      AND status IN ('VALIDATED', 'EMITTED')
    ORDER BY detected_at, id
    LIMIT 1
) AS fact ON true
ORDER BY scope.scope_id;

SELECT format(
    'source=%s:provider=%s:status=%s:reason=%s',
    event.scope_id,
    event.provider,
    event.status,
    coalesce(event.error, 'none')
)
FROM earnings_source_events AS event
WHERE event.scope_id IN (
    'earnings:CSGP:2026Q2',
    'earnings:CZR:2026Q2',
    'earnings:F:2026Q2',
    'earnings:NXPI:2026Q2',
    'earnings:V:2026Q3'
)
ORDER BY event.received_at, event.id;

SELECT format(
    'claim=%s:template=%s:outcome=%s:status=%s:desired=%s:effective=%s:quantity=%s:created=%s',
    claim.scope_id,
    claim.template_id,
    claim.outcome,
    claim.status,
    claim.desired_price,
    claim.effective_price,
    coalesce(claim.quantity::text, 'none'),
    to_char(
        claim.created_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    )
)
FROM resolution_execution_claims AS claim
WHERE claim.scope_id IN (
    'earnings:CSGP:2026Q2',
    'earnings:CZR:2026Q2',
    'earnings:F:2026Q2',
    'earnings:NXPI:2026Q2',
    'earnings:V:2026Q3'
)
ORDER BY claim.scope_id, claim.created_at, claim.id;

SELECT format(
    'order=%s:outcome=%s:group=%s:generation=%s:status=%s:price=%s:quantity=%s',
    profile.scope_id,
    groups.outcome,
    groups.status,
    orders.generation,
    orders.status,
    coalesce(orders.effective_price::text, 'none'),
    coalesce(orders.quantity::text, 'none')
)
FROM resolution_order_groups AS groups
JOIN resolution_execution_profiles AS profile
  ON profile.condition_id = groups.condition_id
JOIN resolution_order_group_orders AS orders
  ON orders.order_group_id = groups.order_group_id
WHERE profile.scope_id IN (
    'earnings:CSGP:2026Q2',
    'earnings:CZR:2026Q2',
    'earnings:F:2026Q2',
    'earnings:NXPI:2026Q2',
    'earnings:V:2026Q3'
)
  AND groups.created_at >= TIMESTAMPTZ '2026-07-28 18:00:00+00'
ORDER BY profile.scope_id, orders.generation, orders.id;

ROLLBACK;
