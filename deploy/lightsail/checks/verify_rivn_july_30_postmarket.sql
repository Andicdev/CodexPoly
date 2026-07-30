BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '15s';

DO $verify$
BEGIN
    IF (
        SELECT count(*) FROM earnings_market_rules
        WHERE rule_key = 'rivn-2026q2-gaap-eps-neg0pt78'
          AND scope_id = 'earnings:RIVN:2026Q2'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN rule is not ready';
    END IF;
    IF (
        SELECT count(*) FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-rivn-2026q2'
          AND status = 'DISABLED'
          AND quantity = 100
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN profile is not safely disabled';
    END IF;
    IF (
        SELECT count(*) FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-rivn-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND metadata ->> 'armed_for_live' = 'false'
          AND metadata ->> 'operator_acceptance_required' = 'true'
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN schedule is not safely pending';
    END IF;
    IF EXISTS (
        SELECT 1 FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RIVN:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RIVN:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RIVN has unexpected facts or claims';
    END IF;
END
$verify$;

ROLLBACK;
