-- Read-only production diagnostic for claims, facts, orders, and lifecycle rows.
BEGIN;

SET TRANSACTION READ ONLY;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $diagnostic$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:WAY:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:WAY:2026Q2'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0xaf07f668593362c55d734ec94a80b415bc12015b92cb03c4b8c5e571e018da2e'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'WAY lifecycle already contains guarded activity';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-way-2026q2'
          AND status <> 'DISABLED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-way-2026q2'
          AND state <> 'PENDING'
    ) THEN
        RAISE EXCEPTION 'WAY lifecycle row is not safely mutable';
    END IF;
END
$diagnostic$;

ROLLBACK;
