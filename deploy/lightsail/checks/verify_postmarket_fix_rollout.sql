-- Fail-closed production verification after the July 28 post-market fixes.
-- This check returns no rows and exposes no source documents or secrets.

DO $$
DECLARE
    reviewed_count integer;
    automatic_count integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM resolution_runtime_heartbeats
        WHERE runtime_key = 'hosted-resolution'
          AND mode = 'live'
          AND supervision_enabled
          AND trading_enabled
          AND last_seen_at > now() - interval '15 seconds'
    ) THEN
        RAISE EXCEPTION
            'fresh fully-live hosted resolution heartbeat is missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles AS profile
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE profile.source_name = 'earnings_resolution'
          AND profile.status = 'ENABLED'
          AND schedule.activate_at <= now()
          AND schedule.deactivate_at > now()
    ) THEN
        RAISE EXCEPTION
            'an in-window earnings profile is unexpectedly enabled';
    END IF;

    SELECT count(*)
    INTO reviewed_count
    FROM resolution_run_journal
    WHERE journal_key IN (
        'earnings:CSGP:2026Q2:2026-07-28',
        'earnings:CZR:2026Q2:2026-07-28',
        'earnings:F:2026Q2:2026-07-28',
        'earnings:NXPI:2026Q2:2026-07-28',
        'earnings:V:2026Q3:2026-07-28'
    )
      AND details ->> 'reviewed_after_block' = 'true';
    IF reviewed_count <> 5 THEN
        RAISE EXCEPTION
            'reviewed post-market journal rows were changed';
    END IF;

    SELECT count(*)
    INTO automatic_count
    FROM resolution_run_journal
    WHERE details ->> 'auto_reconciled' = 'true'
      AND updated_at > now() - interval '10 minutes';
    IF automatic_count < 1 THEN
        RAISE EXCEPTION
            'automatic run-journal reconciliation did not persist';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE scope_id = 'earnings:F:2026Q2'
          AND status = 'DISABLED'
          AND source_policy #>> '{company_ir,kind}' =
              'direct_document'
          AND source_policy #>> '{company_ir,provider}' =
              'company_ir'
    ) THEN
        RAISE EXCEPTION
            'disabled Ford direct-document policy is missing';
    END IF;
END
$$;
