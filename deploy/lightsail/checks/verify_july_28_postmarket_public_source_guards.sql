BEGIN TRANSACTION READ ONLY;

DO $verification$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'csgp-2026q2-gaap-eps-0pt10'
          AND source_policy #> '{company_ir,title_all}'
              = '["CoStar Group", "Q2"]'::jsonb
    ) THEN
        RAISE EXCEPTION 'CSGP public-source guard mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'nxpi-2026q2-nongaap-eps-3pt53'
          AND source_policy #> '{company_ir,title_none}'
              = '["to report", "conference call"]'::jsonb
          AND source_policy #> '{press_wire,title_none}'
              = '["to report", "conference call"]'::jsonb
    ) THEN
        RAISE EXCEPTION 'NXPI public-source guard mismatch';
    END IF;
END
$verification$;

ROLLBACK;
