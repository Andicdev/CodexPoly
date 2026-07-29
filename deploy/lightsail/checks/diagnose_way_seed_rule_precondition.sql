-- Read-only production diagnostic for conflicting WAY rule identities.
BEGIN;

SET TRANSACTION READ ONLY;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $diagnostic$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE (
            scope_id = 'earnings:WAY:2026Q2'
            OR condition_id =
                '0xaf07f668593362c55d734ec94a80b415bc12015b92cb03c4b8c5e571e018da2e'
        )
          AND rule_key <> 'way-2026q2-nongaap-eps-0pt40'
    ) THEN
        RAISE EXCEPTION 'WAY rule identity conflicts with an existing row';
    END IF;
END
$diagnostic$;

ROLLBACK;
