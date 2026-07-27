-- Verify only the post-event NVTS transport update.

BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules AS rule
        JOIN resolution_execution_profiles AS profile
          ON profile.scope_id = rule.scope_id
        WHERE rule.rule_key =
                  'nvts-2026q2-nongaap-eps-neg0pt04'
          AND rule.scope_id = 'earnings:NVTS:2026Q2'
          AND rule.status = 'SHADOW'
          AND rule.source_policy -> 'sec' ->> 'required_item' =
              '2.02'
          AND rule.source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND rule.source_policy -> 'company_ir' ->> 'kind' = 'rss'
          AND rule.source_policy -> 'company_ir' ->> 'feed_url' =
              'https://navitassemi.gcs-web.com/rss/news-releases.xml'
          AND rule.source_policy -> 'company_ir'
                  -> 'allowed_document_hosts' ?
              'navitassemi.gcs-web.com'
          AND rule.source_policy -> 'press_wire' ->> 'provider' =
              'globenewswire'
          AND profile.profile_key = 'earnings-nvts-2026q2'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 50
          AND profile.status = 'DISABLED'
    ) THEN
        RAISE EXCEPTION 'NVTS GCS feed is not safely configured';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'an active NVTS order group still exists';
    END IF;
END
$verify$;

ROLLBACK;
