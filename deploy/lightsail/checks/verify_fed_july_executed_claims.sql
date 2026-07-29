-- Confirm only the five successful selected-outcome claims.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'fed:fomc:2026-07-29:%'
          AND status = 'EXECUTED'
          AND side = 'BUY'
          AND quantity = 5000
          AND error IS NULL
          AND completed_at IS NOT NULL
          AND result ->> 'attempted' = 'true'
          AND result ->> 'accepted' = 'true'
          AND result ->> 'status' = 'SUBMITTED'
          AND jsonb_typeof(result -> 'order_ids') = 'array'
          AND jsonb_array_length(result -> 'order_ids') = 1
    ) <> 5 THEN
        RAISE EXCEPTION 'five FED claims were not successfully executed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id LIKE 'fed:fomc:2026-07-29:%'
          AND status IN ('PENDING', 'FAILED')
    ) THEN
        RAISE EXCEPTION 'a FED execution claim remains non-terminal';
    END IF;
END
$verification$;

ROLLBACK;
