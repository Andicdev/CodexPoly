-- Verify the BA source-only change without returning database contents.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-28 09:45:00+00' THEN
        RAISE EXCEPTION 'BA preflight has already started';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules AS rule
        JOIN resolution_execution_profiles AS profile
          ON profile.scope_id = rule.scope_id
        JOIN resolution_profile_schedules AS schedule
          ON schedule.profile_key = profile.profile_key
        WHERE rule.rule_key = 'ba-2026q2-nongaap-eps-neg0pt32'
          AND rule.scope_id = 'earnings:BA:2026Q2'
          AND rule.status = 'SHADOW'
          AND rule.source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND rule.source_policy -> 'press_wire' ->> 'provider' =
              'prnewswire'
          AND rule.source_policy -> 'press_wire' ->> 'kind' = 'rss'
          AND rule.source_policy -> 'press_wire' ->> 'feed_url' =
              'https://www.prnewswire.com/rss/news-releases-list.rss'
          AND rule.source_policy -> 'press_wire'
                  -> 'allowed_document_hosts' =
              '["www.prnewswire.com"]'::jsonb
          AND rule.source_policy -> 'press_wire' -> 'title_all' =
              '["Boeing", "Second Quarter", "Results"]'::jsonb
          AND rule.source_policy -> 'press_wire' -> 'title_none' =
              '["to release", "deliveries"]'::jsonb
          AND profile.profile_key = 'earnings-ba-2026q2'
          AND profile.status = 'DISABLED'
          AND schedule.schedule_key =
              'schedule:earnings-ba-2026q2'
          AND schedule.automation_mode = 'AUTO_LIVE'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-28 09:45:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-28 10:00:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-28 17:00:00+00'
          AND schedule.state = 'PENDING'
    ) THEN
        RAISE EXCEPTION 'BA PR Newswire source is not safely configured';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:BA:2026Q2'
          AND status = 'VALIDATED'
    ) THEN
        RAISE EXCEPTION 'a validated BA fact already exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:BA:2026Q2'
    ) THEN
        RAISE EXCEPTION 'a BA execution claim already exists';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x9073468de3e2675f39232dfa39ec131ccb5d181807ce1c56432ebb8c2843100f'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'an active BA order group already exists';
    END IF;
END
$verify$;

ROLLBACK;
