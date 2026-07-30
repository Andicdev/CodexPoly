-- Fail closed without returning account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules AS rule
        JOIN resolution_execution_profiles AS profile
          ON profile.scope_id = rule.scope_id
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE rule.ticker IN ('YUM', 'ICE', 'CI')
          AND rule.status = 'SHADOW'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'PENDING'
          AND schedule.metadata ->> 'armed_for_live' = 'false'
    ) <> 3 THEN
        RAISE EXCEPTION 'YUM/ICE/CI preparation mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id IN (
            'earnings:YUM:2026Q2',
            'earnings:ICE:2026Q2',
            'earnings:CI:2026Q2'
        )
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:YUM:2026Q2',
            'earnings:ICE:2026Q2',
            'earnings:CI:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'YUM/ICE/CI facts or claims already exist';
    END IF;
END
$verification$;

ROLLBACK;
