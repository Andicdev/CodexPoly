BEGIN TRANSACTION READ ONLY;

DO $verify$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'nvts-2026q2-nongaap-eps-neg0pt04'
          AND scope_id = 'earnings:NVTS:2026Q2'
          AND source_policy #>> '{company_ir,provider}' =
              'company_ir'
          AND source_policy #>> '{company_ir,kind}' = 'rss'
          AND source_policy #>> '{press_wire,provider}' =
              'globenewswire'
          AND source_policy #>> '{press_wire,kind}' = 'rss'
    ) THEN
        RAISE EXCEPTION
            'NVTS public source policy is missing or invalid';
    END IF;
END
$verify$;

ROLLBACK;
