-- Read-only, non-secret diagnostic for the two residual July 29
-- POST_MARKET profiles. Account, condition, asset, order, and secret data
-- are intentionally excluded.

BEGIN TRANSACTION READ ONLY;

WITH target (ticker, scope_id, profile_key) AS (
    VALUES
        (
            'HOOD',
            'earnings:HOOD:2026Q2',
            'earnings-hood-2026q2'
        ),
        (
            'EA',
            'earnings:EA:2027Q1',
            'earnings-ea-2027q1'
        )
)
SELECT format(
    'ticker=%s,schedule=%s,profile=%s,rule=%s,'
    || 'facts=%s,validated=%s,claims=%s,executed=%s,'
    || 'order_groups=%s,orders=%s,journal=%s,last_error=%s',
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
        WHERE order_group.condition_id = profile.condition_id
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
    ),
    (
        SELECT count(*)
        FROM resolution_order_groups AS order_group
        JOIN resolution_order_group_orders AS order_row
          ON order_row.order_group_id = order_group.order_group_id
        WHERE order_group.condition_id = profile.condition_id
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
    ),
    (
        SELECT count(*)
        FROM resolution_run_journal AS journal
        WHERE journal.scope_id = target.scope_id
          AND journal.block_id IN (
              '2026-07-29-hood-post-market',
              '2026-07-29-ea-post-market'
          )
    ),
    coalesce(schedule.last_error_code, 'none')
)
FROM target
JOIN resolution_execution_profiles AS profile
  ON profile.profile_key = target.profile_key
 AND profile.scope_id = target.scope_id
JOIN resolution_profile_schedules AS schedule
  ON schedule.profile_key = target.profile_key
JOIN earnings_market_rules AS rule
  ON rule.scope_id = target.scope_id
ORDER BY target.ticker;

SELECT format(
    'ticker=%s,provider=%s,event_status=%s,filed=%s,received=%s,'
    || 'fact_status=%s,value=%s,detected=%s,error=%s',
    event.ticker,
    event.provider,
    event.status,
    event.filed_at,
    event.received_at,
    coalesce(fact.status, 'none'),
    fact.value,
    fact.detected_at,
    coalesce(event.error, 'none')
)
FROM earnings_source_events AS event
LEFT JOIN earnings_fact_candidates AS fact
  ON fact.source_event_id = event.id
WHERE event.scope_id IN (
    'earnings:HOOD:2026Q2',
    'earnings:EA:2027Q1'
)
ORDER BY event.ticker, event.received_at, event.id;

ROLLBACK;
