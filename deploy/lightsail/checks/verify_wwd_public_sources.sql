BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'wwd-2026q3-gaap-eps-2pt42'
          AND scope_id = 'earnings:WWD:2026Q3'
          AND source_policy #>> '{company_ir,provider}' =
              'company_ir'
          AND source_policy #>> '{company_ir,kind}' =
              'wordpress_rest'
          AND source_policy #>> '{press_wire,provider}' =
              'globenewswire'
          AND source_policy #>> '{press_wire,kind}' = 'rss'
    ) THEN
        RAISE EXCEPTION
            'WWD public source policy is missing or invalid';
    END IF;
END
$verify$;

ROLLBACK;
