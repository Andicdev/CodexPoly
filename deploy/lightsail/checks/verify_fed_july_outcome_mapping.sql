BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id = 'fed:fomc:2026-07-29:no_change'
          AND status = 'EXECUTED'
          AND outcome = 'YES'
    ) <> 1 OR (
        SELECT count(*)
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'fed:fomc:2026-07-29:increase_25',
            'fed:fomc:2026-07-29:increase_50_plus',
            'fed:fomc:2026-07-29:decrease_25',
            'fed:fomc:2026-07-29:decrease_50_plus'
        )
          AND status = 'EXECUTED'
          AND outcome = 'NO'
    ) <> 4 THEN
        RAISE EXCEPTION 'FED no-change outcome mapping is invalid';
    END IF;
END
$verification$;

ROLLBACK;
