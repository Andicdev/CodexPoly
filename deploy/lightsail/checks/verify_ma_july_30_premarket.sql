-- Read-only fail-closed verification for the prepared MA profile.

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
        WHERE rule.rule_key = 'ma-2026q2-nongaap-eps-4pt77'
          AND rule.scope_id = 'earnings:MA:2026Q2'
          AND rule.cik = '1141391'
          AND rule.comparison_op = '>'
          AND rule.strike = 4.77
          AND rule.source_policy -> 'press_wire' ->> 'provider' =
              'businesswire'
          AND rule.status = 'SHADOW'
          AND profile.profile_key = 'earnings-ma-2026q2'
          AND profile.status = 'DISABLED'
          AND profile.quantity = 100
          AND schedule.schedule_key =
              'schedule:earnings-ma-2026q2'
          AND schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'PENDING'
          AND schedule.metadata ->> 'armed_for_live' = 'false'
    ) <> 1 THEN
        RAISE EXCEPTION 'MA premarket configuration mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:MA:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:MA:2026Q2'
    ) THEN
        RAISE EXCEPTION 'MA scope is not clean';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x9aa5ff923c2669e27ce9be9631deb17719afd08d877237e9bf24d853b75893a1'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'MA market has active order supervision';
    END IF;
END
$verification$;

ROLLBACK;
