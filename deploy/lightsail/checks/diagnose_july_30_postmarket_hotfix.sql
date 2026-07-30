-- Read-only, non-secret production diagnostic for the July 30 earnings
-- hotfix. Account, condition, asset, order-id, and secret data are excluded.

BEGIN TRANSACTION READ ONLY;

WITH targets(ticker, scope_id, profile_key) AS (
    VALUES
        ('RIVN', 'earnings:RIVN:2026Q2', 'earnings-rivn-2026q2'),
        ('RDDT', 'earnings:RDDT:2026Q2', 'earnings-rddt-2026q2'),
        ('RBLX', 'earnings:RBLX:2026Q2', 'earnings-rblx-2026q2'),
        ('DLB', 'earnings:DLB:2026Q3', 'earnings-dlb-2026q3')
)
SELECT format(
    'ticker=%s,schedule=%s,profile=%s,rule=%s,facts=%s,validated=%s,claims=%s,executed=%s,orders=%s,last_error=%s',
    target.ticker,
    schedule.state,
    profile.status,
    rule.status,
    (
        SELECT count(*)
        FROM earnings_fact_candidates AS fact
        WHERE fact.scope_id = target.scope_id
    ),
    (
        SELECT count(*)
        FROM earnings_fact_candidates AS fact
        WHERE fact.scope_id = target.scope_id
          AND fact.status IN ('VALIDATED', 'EMITTED')
    ),
    (
        SELECT count(*)
        FROM resolution_execution_claims AS claim
        WHERE claim.scope_id = target.scope_id
    ),
    (
        SELECT count(*)
        FROM resolution_execution_claims AS claim
        WHERE claim.scope_id = target.scope_id
          AND claim.status = 'EXECUTED'
    ),
    (
        SELECT count(*)
        FROM resolution_order_groups AS order_group
        JOIN resolution_order_group_orders AS order_row
          ON order_row.order_group_id = order_group.order_group_id
        WHERE order_group.condition_id = profile.condition_id
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-30 18:00:00+00'
    ),
    coalesce(schedule.last_error_code, 'none')
)
FROM targets AS target
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = target.profile_key
 AND profile.scope_id = target.scope_id
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = target.profile_key
JOIN earnings_market_rules AS rule
  ON rule.scope_id = target.scope_id
ORDER BY target.ticker;

SELECT format(
    'ticker=%s,provider=%s,status=%s,fact_status=%s,value=%s,received=%s,error=%s',
    event.ticker,
    event.provider,
    event.status,
    coalesce(fact.status, 'none'),
    coalesce(fact.value::text, 'none'),
    to_char(
        event.received_at AT TIME ZONE 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'
    ),
    coalesce(event.error, 'none')
)
FROM earnings_source_events AS event
LEFT JOIN earnings_fact_candidates AS fact
  ON fact.source_event_id = event.id
WHERE event.scope_id IN (
    'earnings:RIVN:2026Q2',
    'earnings:RDDT:2026Q2',
    'earnings:RBLX:2026Q2',
    'earnings:DLB:2026Q3'
)
ORDER BY event.ticker, event.received_at, event.id;

SELECT format(
    'claim=%s,outcome=%s,status=%s,desired=%s,effective=%s,quantity=%s,created=%s',
    claim.scope_id,
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
    'earnings:RIVN:2026Q2',
    'earnings:RDDT:2026Q2',
    'earnings:RBLX:2026Q2',
    'earnings:DLB:2026Q3'
)
ORDER BY claim.scope_id, claim.created_at, claim.id;

SELECT format(
    'order=%s,outcome=%s,group=%s,generation=%s,status=%s,price=%s,quantity=%s',
    profile.scope_id,
    order_group.outcome,
    order_group.status,
    order_row.generation,
    order_row.status,
    coalesce(order_row.effective_price::text, 'none'),
    coalesce(order_row.quantity::text, 'none')
)
FROM resolution_order_groups AS order_group
JOIN resolution_execution_profiles AS profile
  ON profile.condition_id = order_group.condition_id
JOIN resolution_order_group_orders AS order_row
  ON order_row.order_group_id = order_group.order_group_id
WHERE profile.scope_id IN (
    'earnings:RIVN:2026Q2',
    'earnings:RDDT:2026Q2',
    'earnings:RBLX:2026Q2',
    'earnings:DLB:2026Q3'
)
  AND order_group.created_at >= TIMESTAMPTZ '2026-07-30 18:00:00+00'
ORDER BY profile.scope_id, order_row.generation, order_row.id;

ROLLBACK;
