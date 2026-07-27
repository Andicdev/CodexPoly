-- Read-only post-execution invariant for the MSTR July 21-27 live window.
-- The production migration runner intentionally exposes only pass/fail.

BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    mstr_scopes CONSTANT text[] := ARRAY[
        'mstr-btc:2026-07-21:2026-07-27:purchase-any',
        'mstr-btc:2026-07-21:2026-07-27:purchase-over-1000',
        'mstr-btc:2026-07-21:2026-07-27:sale-any'
    ];
    mstr_conditions CONSTANT text[] := ARRAY[
        '0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c794fc3a4d1f18051a',
        '0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d74a831b0465501ec1',
        '0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee56d36a5b0359500b'
    ];
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(mstr_scopes)
    ) <> 6 THEN
        RAISE EXCEPTION 'expected exactly six MSTR execution claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ANY(mstr_scopes)
          AND status = 'EXECUTED'
          AND (
              outcome <> 'NO'
              OR side <> 'BUY'
              OR account_name <> 'abccbaq'
              OR quantity <> 50
              OR error IS NOT NULL
              OR completed_at IS NULL
              OR result ->> 'attempted' <> 'true'
              OR result ->> 'accepted' <> 'true'
              OR result ->> 'status' <> 'SUBMITTED'
              OR jsonb_typeof(result -> 'order_ids') <> 'array'
              OR jsonb_array_length(result -> 'order_ids') <> 1
          )
    ) OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(mstr_scopes)
          AND status = 'EXECUTED'
    ) <> 3 OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(mstr_scopes)
          AND status = 'EXPIRED'
          AND outcome = 'YES'
          AND result ->> 'attempted' = 'false'
          AND result ->> 'reason' = 'template_not_selected'
          AND error IS NULL
    ) <> 3 THEN
        RAISE EXCEPTION 'an MSTR execution claim is not successfully submitted';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = mstr_scopes[1]
          AND effective_price = 0.999
    ) OR NOT EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = mstr_scopes[2]
          AND effective_price = 0.999
    ) OR NOT EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = mstr_scopes[3]
          AND effective_price = 0.99
    ) THEN
        RAISE EXCEPTION 'MSTR submitted prices do not match live tick sizes';
    END IF;

    IF (
        SELECT count(*)
        FROM mstr_btc_source_events
        WHERE scope_id = 'mstr-btc:2026-07-21:2026-07-27'
          AND provider = 'sec'
          AND ticker = 'MSTR'
          AND form_type = '8-K'
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one accepted SEC source event';
    END IF;

    IF (
        SELECT count(*)
        FROM mstr_btc_fact_candidates
        WHERE scope_id = 'mstr-btc:2026-07-21:2026-07-27'
          AND provider = 'sec'
          AND holdings_before_btc = 843775
          AND holdings_after_btc = 843775
          AND net_change_btc = 0
          AND acquired_btc = 0
          AND sold_btc IS NULL
          AND validation_status = 'VALIDATED'
    ) <> 1 THEN
        RAISE EXCEPTION 'validated MSTR holdings fact does not match';
    END IF;

    IF (
        SELECT count(*)
        FROM mstr_btc_processing_results AS result
        JOIN mstr_btc_source_events AS event
          ON event.id = result.source_event_id
        WHERE event.scope_id = 'mstr-btc:2026-07-21:2026-07-27'
          AND result.status = 'ACCEPTED'
          AND result.fact_candidate_id IS NOT NULL
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one accepted MSTR processing result';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id = ANY(mstr_conditions)
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one tick-supervised MSTR order group';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id = ANY(mstr_conditions)
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
    ) THEN
        RAISE EXCEPTION 'MSTR supervision group is not in the expected state';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_order_group_orders AS tracked
        JOIN resolution_order_groups AS groups
          ON groups.order_group_id = tracked.order_group_id
        WHERE groups.account_name = 'abccbaq'
          AND groups.condition_id = ANY(mstr_conditions)
          AND tracked.status = 'FILLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'expected exactly one filled supervised MSTR order';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_group_orders AS tracked
        JOIN resolution_order_groups AS groups
          ON groups.order_group_id = tracked.order_group_id
        WHERE groups.account_name = 'abccbaq'
          AND groups.condition_id = ANY(mstr_conditions)
          AND tracked.status = 'LIVE'
    ) THEN
        RAISE EXCEPTION 'a supervised MSTR order remains live';
    END IF;
END
$verify$;

ROLLBACK;
