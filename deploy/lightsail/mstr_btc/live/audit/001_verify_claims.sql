BEGIN TRANSACTION READ ONLY;

DO $verify$
DECLARE
    scopes CONSTANT text[] := ARRAY[
        'mstr-btc:2026-07-21:2026-07-27:purchase-any',
        'mstr-btc:2026-07-21:2026-07-27:purchase-over-1000',
        'mstr-btc:2026-07-21:2026-07-27:sale-any'
    ];
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(scopes)
    ) <> 6 OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = ANY(scopes)
          AND status = 'EXECUTED'
    ) <> 3 OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ANY(scopes)
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
        WHERE scope_id = ANY(scopes)
          AND status = 'EXPIRED'
    ) <> 3 OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ANY(scopes)
          AND status = 'EXPIRED'
          AND (
              outcome <> 'YES'
              OR side <> 'BUY'
              OR account_name <> 'abccbaq'
              OR quantity <> 50
              OR error IS NOT NULL
              OR completed_at IS NULL
              OR result ->> 'attempted' <> 'false'
              OR result ->> 'reason' <> 'template_not_selected'
          )
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = ANY(scopes)
          AND status NOT IN ('EXECUTED', 'EXPIRED')
    ) THEN
        RAISE EXCEPTION 'MSTR claim invariant failed';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = scopes[1]
          AND status = 'EXECUTED'
          AND outcome = 'NO'
          AND effective_price = 0.999
    ) OR NOT EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = scopes[2]
          AND status = 'EXECUTED'
          AND outcome = 'NO'
          AND effective_price = 0.999
    ) OR NOT EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = scopes[3]
          AND status = 'EXECUTED'
          AND outcome = 'NO'
          AND effective_price = 0.99
    ) THEN
        RAISE EXCEPTION 'MSTR claim price invariant failed';
    END IF;
END
$verify$;

ROLLBACK;
