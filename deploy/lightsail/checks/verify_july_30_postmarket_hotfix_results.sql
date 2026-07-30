-- Fail-closed, read-only verification of the three recovered July 30
-- earnings executions. Sensitive account, asset, and order identifiers are
-- intentionally excluded from every predicate.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    expected record;
BEGIN
    FOR expected IN
        SELECT *
        FROM (
            VALUES
                (
                    'earnings:RIVN:2026Q2',
                    -0.9700000000::numeric,
                    'NO'
                ),
                (
                    'earnings:RDDT:2026Q2',
                    1.2500000000::numeric,
                    'YES'
                ),
                (
                    'earnings:RBLX:2026Q2',
                    -0.2600000000::numeric,
                    'YES'
                )
        ) AS rows(scope_id, fact_value, outcome)
    LOOP
        IF (
            SELECT count(*)
            FROM earnings_fact_candidates
            WHERE scope_id = expected.scope_id
              AND status IN ('VALIDATED', 'EMITTED')
              AND value = expected.fact_value
        ) <> 1 THEN
            RAISE EXCEPTION
                'validated fact verification failed for %',
                expected.scope_id;
        END IF;

        IF (
            SELECT count(*)
            FROM resolution_execution_claims
            WHERE scope_id = expected.scope_id
              AND outcome = expected.outcome
              AND side = 'BUY'
              AND desired_price = 0.999
              AND effective_price IN (0.99, 0.999)
              AND quantity = 100
              AND status = 'EXECUTED'
              AND error IS NULL
        ) <> 1 OR (
            SELECT count(*)
            FROM resolution_execution_claims
            WHERE scope_id = expected.scope_id
        ) <> 2 OR (
            SELECT count(*)
            FROM resolution_execution_claims
            WHERE scope_id = expected.scope_id
              AND outcome <> expected.outcome
              AND status = 'EXPIRED'
        ) <> 1 THEN
            RAISE EXCEPTION
                'execution claim verification failed for %',
                expected.scope_id;
        END IF;

        IF EXISTS (
            SELECT 1
            FROM resolution_order_groups AS order_group
            JOIN resolution_execution_profiles AS profile
              ON profile.condition_id = order_group.condition_id
            JOIN resolution_order_group_orders AS order_row
              ON order_row.order_group_id = order_group.order_group_id
            WHERE profile.scope_id = expected.scope_id
              AND order_group.created_at >=
                  TIMESTAMPTZ '2026-07-30 21:10:00+00'
              AND order_row.status IN ('REJECTED', 'UNKNOWN')
        ) THEN
            RAISE EXCEPTION
                'order lifecycle error detected for %',
                expected.scope_id;
        END IF;
    END LOOP;

    -- The accepted submit-first overlap risk materialized for RIVN: the
    -- initial 0.99 claim and the 0.999 replacement both filled. The original
    -- row has no persisted effective price, while its claim records 0.99.
    -- No live RIVN order remains.
    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RIVN:2026Q2'
          AND outcome = 'NO'
          AND status = 'EXECUTED'
          AND effective_price = 0.99
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        JOIN resolution_order_group_orders AS order_row
          ON order_row.order_group_id = order_group.order_group_id
        WHERE profile.scope_id = 'earnings:RIVN:2026Q2'
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-30 21:10:00+00'
          AND order_row.status = 'FILLED'
          AND order_row.quantity = 100
    ) <> 2 OR (
        SELECT count(*)
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        JOIN resolution_order_group_orders AS order_row
          ON order_row.order_group_id = order_group.order_group_id
        WHERE profile.scope_id = 'earnings:RIVN:2026Q2'
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-30 21:10:00+00'
          AND order_row.status = 'FILLED'
          AND order_row.effective_price = 0.999
          AND order_row.quantity = 100
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        JOIN resolution_order_group_orders AS order_row
          ON order_row.order_group_id = order_group.order_group_id
        WHERE profile.scope_id = 'earnings:RIVN:2026Q2'
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-30 21:10:00+00'
          AND order_row.status = 'FILLED'
          AND order_row.effective_price IS NULL
          AND order_row.quantity = 100
    ) <> 1 OR EXISTS (
        SELECT 1
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        JOIN resolution_order_group_orders AS order_row
          ON order_row.order_group_id = order_group.order_group_id
        WHERE profile.scope_id = 'earnings:RIVN:2026Q2'
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-30 21:10:00+00'
          AND order_row.status = 'LIVE'
    ) THEN
        RAISE EXCEPTION 'RIVN overlap fill verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        WHERE profile.scope_id = 'earnings:RIVN:2026Q2'
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-30 21:10:00+00'
          AND order_group.status = 'FAILED'
          AND order_group.last_error IS NOT NULL
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN reconciliation anomaly is missing';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        JOIN resolution_order_group_orders AS order_row
          ON order_row.order_group_id = order_group.order_group_id
        WHERE profile.scope_id IN (
            'earnings:RDDT:2026Q2',
            'earnings:RBLX:2026Q2'
        )
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-30 21:10:00+00'
          AND order_row.status = 'LIVE'
          AND order_row.effective_price = 0.999
          AND order_row.quantity = 100
    ) <> 2 OR EXISTS (
        SELECT 1
        FROM resolution_order_groups AS order_group
        JOIN resolution_execution_profiles AS profile
          ON profile.condition_id = order_group.condition_id
        WHERE profile.scope_id IN (
            'earnings:RDDT:2026Q2',
            'earnings:RBLX:2026Q2'
        )
          AND order_group.created_at >=
              TIMESTAMPTZ '2026-07-30 21:10:00+00'
          AND order_group.status = 'FAILED'
    ) THEN
        RAISE EXCEPTION 'RDDT/RBLX live order verification failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at >= now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'live resolution heartbeat is missing or stale';
    END IF;
END
$verify$;

ROLLBACK;
