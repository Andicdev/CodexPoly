-- Replace the unstable Navitas vanity RSS endpoint with the official GCS
-- endpoint. Existing facts, claims, profiles, schedules, and orders remain
-- unchanged.

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
            '{company_ir,feed_url}',
            to_jsonb(
                'https://navitassemi.gcs-web.com/rss/news-releases.xml'
                ::text
            ),
            false
        ),
        updated_at = now()
    WHERE rule.rule_key =
              'nvts-2026q2-nongaap-eps-neg0pt04'
      AND rule.scope_id = 'earnings:NVTS:2026Q2'
      AND rule.ticker = 'NVTS'
      AND rule.cik = '1821769'
      AND rule.metric_kind = 'non_gaap_eps'
      AND rule.primary_basis = 'diluted'
      AND rule.comparison_op = '>'
      AND rule.strike = -0.04
      AND rule.condition_id =
          '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
      AND rule.status = 'SHADOW'
      AND rule.source_policy -> 'company_ir' ->> 'provider' =
          'company_ir'
      AND rule.source_policy -> 'company_ir' ->> 'kind' = 'rss'
      AND rule.source_policy -> 'company_ir'
              -> 'allowed_document_hosts' ? 'navitassemi.gcs-web.com'
      AND rule.source_policy -> 'company_ir' ->> 'feed_url' IN (
          'https://ir.navitassemi.com/rss/news-releases.xml',
          'https://navitassemi.gcs-web.com/rss/news-releases.xml'
      )
      AND EXISTS (
          SELECT 1
          FROM resolution_execution_profiles AS profile
          WHERE profile.profile_key = 'earnings-nvts-2026q2'
            AND profile.scope_id = rule.scope_id
            AND profile.account_name = 'abccbaq'
            AND profile.condition_id = rule.condition_id
            AND profile.yes_desired_price = 0.999
            AND profile.no_desired_price = 0.999
            AND profile.quantity = 50
            AND profile.status = 'DISABLED'
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
        RAISE EXCEPTION 'NVTS GCS feed guard rejected change';
    END IF;
END
$change$;

COMMIT;
