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
        WHERE (
            (
                schedule.schedule_key =
                    'schedule:earnings-virt-2026q2'
                AND schedule.profile_key = 'earnings-virt-2026q2'
                AND schedule.preflight_at =
                    TIMESTAMPTZ '2026-07-30 10:00:00+00'
                AND schedule.activate_at =
                    TIMESTAMPTZ '2026-07-30 10:30:00+00'
                AND schedule.deactivate_at =
                    TIMESTAMPTZ '2026-07-30 13:30:00+00'
                AND profile.scope_id = 'earnings:VIRT:2026Q2'
                AND rule.rule_key =
                    'virt-2026q2-nongaap-eps-1pt82'
            ) OR (
                schedule.schedule_key =
                    'schedule:earnings-ma-2026q2'
                AND schedule.profile_key = 'earnings-ma-2026q2'
                AND schedule.preflight_at =
                    TIMESTAMPTZ '2026-07-30 10:30:00+00'
                AND schedule.activate_at =
                    TIMESTAMPTZ '2026-07-30 11:00:00+00'
                AND schedule.deactivate_at =
                    TIMESTAMPTZ '2026-07-30 14:30:00+00'
                AND profile.scope_id = 'earnings:MA:2026Q2'
                AND rule.rule_key = 'ma-2026q2-nongaap-eps-4pt77'
            )
        )
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.state IN ('PENDING', 'READY')
          AND schedule.metadata ->> 'armed_for_live' = 'true'
          AND schedule.metadata ->> 'aggregate_notional_cap' = '1000'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND profile.status = 'DISABLED'
          AND rule.status = 'SHADOW'
    ) <> 2 THEN
        RAISE EXCEPTION 'VIRT/MA AUTO_LIVE arming mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id IN (
            'earnings:VIRT:2026Q2',
            'earnings:MA:2026Q2'
        )
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:VIRT:2026Q2',
            'earnings:MA:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'VIRT/MA facts or claims already exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id IN (
              '0xe51d31ccfbad36c133152ce07533e5baee5db4bf2b02f76df7192fce363ac770',
              '0x9aa5ff923c2669e27ce9be9631deb17719afd08d877237e9bf24d853b75893a1'
          )
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'VIRT/MA active order group already exists';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at >= now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION 'live resolution heartbeat is missing or stale';
    END IF;
END
$verification$;

ROLLBACK;
