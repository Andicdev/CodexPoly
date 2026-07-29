-- Fail closed without returning account, market, order, or secret data.

BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN resolution_execution_profiles AS profile
          ON profile.profile_key = schedule.profile_key
        JOIN earnings_market_rules AS rule
          ON rule.scope_id = profile.scope_id
        WHERE schedule.schedule_key =
              'schedule:earnings-way-2026q2'
          AND schedule.profile_key = 'earnings-way-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-29 19:45:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-30 02:00:00+00'
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND profile.scope_id = 'earnings:WAY:2026Q2'
          AND profile.account_name = 'abccbaq'
          AND profile.quantity = 100
          AND profile.status = 'DISABLED'
          AND rule.rule_key =
              'way-2026q2-nongaap-eps-0pt40'
          AND rule.status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'WAY AUTO_LIVE arming mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:WAY:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:WAY:2026Q2'
    ) THEN
        RAISE EXCEPTION 'WAY facts or claims already exist';
    END IF;
END
$verification$;

ROLLBACK;
