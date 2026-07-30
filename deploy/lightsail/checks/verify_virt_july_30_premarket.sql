BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules AS rule
        JOIN resolution_execution_profiles AS profile
          ON profile.scope_id = rule.scope_id
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE rule.rule_key = 'virt-2026q2-nongaap-eps-1pt82'
          AND rule.scope_id = 'earnings:VIRT:2026Q2'
          AND rule.condition_id =
              '0xe51d31ccfbad36c133152ce07533e5baee5db4bf2b02f76df7192fce363ac770'
          AND rule.source_policy ->> 'reject_preliminary_results' =
              'true'
          AND profile.profile_key = 'earnings-virt-2026q2'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
          AND schedule.schedule_key =
              'schedule:earnings-virt-2026q2'
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'PENDING'
    ) <> 1 THEN
        RAISE EXCEPTION 'VIRT premarket configuration mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:VIRT:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:VIRT:2026Q2'
    ) THEN
        RAISE EXCEPTION 'VIRT scope is not clean';
    END IF;
END
$verify$;

ROLLBACK;
