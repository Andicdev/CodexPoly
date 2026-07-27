-- Fail closed without printing rule, profile, catalog, or claim contents.

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key IN (
            'ba-2026q2-nongaap-eps-neg0pt32',
            'czr-2026q2-gaap-eps-0pt05',
            'csgp-2026q2-gaap-eps-0pt10'
        )
          AND status = 'SHADOW'
          AND comparison_op = '>'
          AND rounding_places = 2
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'company_ir' ->> 'kind' = 'rss'
    ) <> 3 THEN
        RAISE EXCEPTION 'next earnings rule set mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'ba-2026q2-nongaap-eps-neg0pt32'
          AND scope_id = 'earnings:BA:2026Q2'
          AND ticker = 'BA'
          AND cik = '12927'
          AND metric_kind = 'non_gaap_eps'
          AND strike = -0.32
          AND condition_id = '0x9073468de3e2675f39232dfa39ec131ccb5d181807ce1c56432ebb8c2843100f'
    ) THEN
        RAISE EXCEPTION 'BA earnings rule mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'czr-2026q2-gaap-eps-0pt05'
          AND scope_id = 'earnings:CZR:2026Q2'
          AND ticker = 'CZR'
          AND cik = '1590895'
          AND metric_kind = 'gaap_eps'
          AND strike = 0.05
          AND condition_id = '0x13805b2ba317a2c26ff596bb59534c23c4808fd26eac9be6f847977b92fd6bf3'
    ) THEN
        RAISE EXCEPTION 'CZR earnings rule mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'csgp-2026q2-gaap-eps-0pt10'
          AND scope_id = 'earnings:CSGP:2026Q2'
          AND ticker = 'CSGP'
          AND cik = '1057352'
          AND metric_kind = 'gaap_eps'
          AND strike = 0.10
          AND condition_id = '0xb71e441b6853dc1c3e1480b6d772b63cd8a907e706c1b1a4862c3ffa794ac418'
    ) THEN
        RAISE EXCEPTION 'CSGP earnings rule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'earnings-ba-2026q2',
            'earnings-czr-2026q2',
            'earnings-csgp-2026q2'
        )
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 50
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND status = 'DISABLED'
    ) <> 3 THEN
        RAISE EXCEPTION 'next earnings profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key IN (
            'BA:2026-07-28',
            'CZR:2026-07-28',
            'CSGP:2026-07-28'
        )
          AND metric_options ->> 'comparison_op' = '>'
          AND metric_options ->> 'primary_basis' = 'diluted'
    ) <> 3 THEN
        RAISE EXCEPTION 'next earnings catalog set mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:BA:2026Q2',
            'earnings:CZR:2026Q2',
            'earnings:CSGP:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'next earnings execution claim must not exist';
    END IF;
END
$verification$;
