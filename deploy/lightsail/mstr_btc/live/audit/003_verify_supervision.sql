BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    conditions CONSTANT text[] := ARRAY[
        '0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c794fc3a4d1f18051a',
        '0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1',
        '0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b'
    ];
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id = ANY(conditions)
    ) <> 1 OR EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id = ANY(conditions)
          AND (
              status <> 'COMPLETED'
              OR outcome <> 'NO'
              OR desired_price <> 0.999
              OR quantity <> 50
              OR policy_kind <> 'reprice_on_tick_change'
              OR trigger_old_tick <> 0.01
              OR trigger_new_tick <> 0.001
              OR reprice_count <> 0
              OR max_reprices <> 1
              OR last_error IS NOT NULL
          )
    ) OR (
        SELECT count(*)
        FROM resolution_order_group_orders AS tracked
        JOIN resolution_order_groups AS groups
          ON groups.order_group_id = tracked.order_group_id
        WHERE groups.account_name = 'abccbaq'
          AND groups.condition_id = ANY(conditions)
          AND tracked.status = 'FILLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'MSTR supervision invariant failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_group_orders AS tracked
        JOIN resolution_order_groups AS groups
          ON groups.order_group_id = tracked.order_group_id
        WHERE groups.account_name = 'abccbaq'
          AND groups.condition_id = ANY(conditions)
          AND tracked.status = 'LIVE'
    ) THEN
        RAISE EXCEPTION 'a supervised MSTR order remains live';
    END IF;
END
$verify$;

ROLLBACK;
