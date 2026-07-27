-- Add Hilton Stories as an independently polled HLT transport without
-- changing profile, schedule, claim, fact, or order state.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

DO $change$
DECLARE
    changed_rows integer;
BEGIN
    UPDATE earnings_market_rules AS rule
    SET
        source_policy = jsonb_set(
            rule.source_policy,
            '{company_ir}',
            '{
                "allowed_document_hosts": ["stories.hilton.com"],
                "feed_url": "https://stories.hilton.com/feed/",
                "kind": "rss",
                "provider": "company_ir",
                "title_all": ["Hilton", "Second Quarter", "Results"],
                "title_none": ["Announces", "Release Date"]
            }'::jsonb,
            true
        ),
        updated_at = now()
    WHERE rule.rule_key = 'hlt-2026q2-nongaap-eps-2pt25'
      AND rule.scope_id = 'earnings:HLT:2026Q2'
      AND rule.ticker = 'HLT'
      AND rule.cik = '1585689'
      AND rule.metric_kind = 'non_gaap_eps'
      AND rule.primary_basis = 'diluted'
      AND rule.comparison_op = '>'
      AND rule.strike = 2.25
      AND rule.condition_id =
          '0x619d7bfd2a712815069f0c8972149287a6f6fdfe21020d11e721ccd6bf4c3b4f'
      AND rule.status = 'SHADOW'
      AND clock_timestamp() <
          TIMESTAMPTZ '2026-07-28 08:45:00+00'
      AND EXISTS (
          SELECT 1
          FROM resolution_execution_profiles AS profile
          WHERE profile.profile_key = 'earnings-hlt-2026q2'
            AND profile.scope_id = rule.scope_id
            AND profile.account_name = 'abccbaq'
            AND profile.condition_id = rule.condition_id
            AND profile.yes_desired_price = 0.999
            AND profile.no_desired_price = 0.999
            AND profile.quantity = 50
            AND profile.status = 'DISABLED'
      )
      AND EXISTS (
          SELECT 1
          FROM resolution_profile_schedules AS schedule
          WHERE schedule.schedule_key =
                    'schedule:earnings-hlt-2026q2'
            AND schedule.profile_key = 'earnings-hlt-2026q2'
            AND schedule.automation_mode = 'AUTO_LIVE'
            AND schedule.preflight_at =
                TIMESTAMPTZ '2026-07-28 08:45:00+00'
            AND schedule.activate_at =
                TIMESTAMPTZ '2026-07-28 09:00:00+00'
            AND schedule.deactivate_at =
                TIMESTAMPTZ '2026-07-28 17:00:00+00'
            AND schedule.state = 'PENDING'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM earnings_fact_candidates
          WHERE scope_id = rule.scope_id
            AND status = 'VALIDATED'
      )
      AND NOT EXISTS (
          SELECT 1
          FROM resolution_execution_claims
          WHERE scope_id = rule.scope_id
      )
      AND NOT EXISTS (
          SELECT 1
          FROM resolution_order_groups
          WHERE account_name = 'abccbaq'
            AND condition_id = rule.condition_id
            AND status IN ('ACTIVE', 'REPRICING')
      );

    GET DIAGNOSTICS changed_rows = ROW_COUNT;
    IF changed_rows <> 1 THEN
        RAISE EXCEPTION 'HLT company IR source guard rejected change';
    END IF;
END
$change$;

COMMIT;
