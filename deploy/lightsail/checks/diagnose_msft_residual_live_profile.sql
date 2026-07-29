BEGIN TRANSACTION READ ONLY;

DO $diagnostic$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-msft-2026q4'
          AND scope_id = 'earnings:MSFT:2026Q4'
          AND status = 'ENABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'MSFT is not the residual live profile';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:MSFT:2026Q4'
          AND (
              status <> 'EXPIRED'
              OR coalesce(result ->> 'attempted', 'false') <> 'false'
          )
    ) THEN
        RAISE EXCEPTION 'MSFT has unexpected live execution evidence';
    END IF;
END
$diagnostic$;

ROLLBACK;
