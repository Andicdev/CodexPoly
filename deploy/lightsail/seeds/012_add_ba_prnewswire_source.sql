-- Add a third, independently polled BA transport without changing profile,
-- schedule, claim, fact, or order state.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '15s';

DO $update$
DECLARE
    changed_rows integer;
BEGIN
    UPDATE earnings_market_rules AS rule
    SET
        source_policy = jsonb_set(
            rule.source_policy,
            '{press_wire}',
            '{
                "allowed_document_hosts": ["www.prnewswire.com"],
                "feed_url": "https://www.prnewswire.com/rss/news-releases-list.rss",
                "kind": "rss",
                "provider": "prnewswire",
                "title_all": ["Boeing", "Second Quarter", "Results"],
                "title_none": ["to release", "deliveries"]
            }'::jsonb,
            true
        ),
        updated_at = now()
    WHERE rule.rule_key = 'ba-2026q2-nongaap-eps-neg0pt32'
      AND rule.scope_id = 'earnings:BA:2026Q2'
      AND rule.ticker = 'BA'
      AND rule.cik = '12927'
      AND rule.metric_kind = 'non_gaap_eps'
      AND rule.primary_basis = 'diluted'
      AND rule.comparison_op = '>'
      AND rule.strike = -0.32
      AND rule.condition_id =
          '0x9073468de3e2675f39232dfa39ec131ccb5d181807ce1c56432ebb8c2843100f'
      AND rule.status = 'SHADOW'
      AND clock_timestamp() <
          TIMESTAMPTZ '2026-07-28 09:45:00+00'
      AND EXISTS (
          SELECT 1
          FROM resolution_execution_profiles AS profile
          WHERE profile.profile_key = 'earnings-ba-2026q2'
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
                    'schedule:earnings-ba-2026q2'
            AND schedule.profile_key = 'earnings-ba-2026q2'
            AND schedule.automation_mode = 'AUTO_LIVE'
            AND schedule.preflight_at =
                TIMESTAMPTZ '2026-07-28 09:45:00+00'
            AND schedule.activate_at =
                TIMESTAMPTZ '2026-07-28 10:00:00+00'
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
        RAISE EXCEPTION 'BA PR Newswire source guard rejected update';
    END IF;
END
$update$;

COMMIT;
