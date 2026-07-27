-- Verify the HLT source-only change without returning database contents.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-28 08:45:00+00' THEN
        RAISE EXCEPTION 'HLT preflight has already started';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules AS rule
        JOIN resolution_execution_profiles AS profile
          ON profile.scope_id = rule.scope_id
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE rule.rule_key = 'hlt-2026q2-nongaap-eps-2pt25'
          AND rule.scope_id = 'earnings:HLT:2026Q2'
          AND rule.status = 'SHADOW'
          AND rule.source_policy -> 'sec' ->> 'required_item' =
              '2.02'
          AND rule.source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND rule.source_policy -> 'company_ir' ->> 'kind' = 'rss'
          AND rule.source_policy -> 'company_ir' ->> 'feed_url' =
              'https://stories.hilton.com/feed/'
          AND rule.source_policy -> 'company_ir'
                  -> 'allowed_document_hosts' =
              '["stories.hilton.com"]'::jsonb
          AND rule.source_policy -> 'company_ir' -> 'title_all' =
              '["Hilton", "Second Quarter", "Results"]'::jsonb
          AND rule.source_policy -> 'company_ir' -> 'title_none' =
              '["Announces", "Release Date"]'::jsonb
          AND profile.profile_key = 'earnings-hlt-2026q2'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 50
          AND profile.status = 'DISABLED'
          AND schedule.schedule_key =
              'schedule:earnings-hlt-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-28 08:45:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-28 09:00:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-28 17:00:00+00'
          AND schedule.state = 'PENDING'
    ) THEN
        RAISE EXCEPTION 'HLT company IR source is not safely configured';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:HLT:2026Q2'
          AND status = 'VALIDATED'
    ) THEN
        RAISE EXCEPTION 'a validated HLT fact already exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:HLT:2026Q2'
    ) THEN
        RAISE EXCEPTION 'an HLT execution claim already exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x619d7bfd2a712815069f0c8972149287a6f6fdfe21020d11e721ccd6bf4c3b4f'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'an active HLT order group already exists';
    END IF;
END
$verify$;

ROLLBACK;
