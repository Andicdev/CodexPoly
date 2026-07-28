-- Fail closed without printing rules, profiles, catalog rows, or claims.

DO $verification$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key IN (
            'pypl-2026q2-nongaap-eps-1pt28',
            'ups-2026q2-nongaap-eps-1pt66',
            'hlt-2026q2-nongaap-eps-2pt25',
            'ivz-2026q2-nongaap-eps-0pt66',
            'ko-2026q2-nongaap-eps-0pt93',
            'jblu-2026q2-nongaap-eps-neg0pt68',
            'spgi-2026q2-nongaap-eps-4pt95',
            'sbux-2026q3-gaap-eps-0pt69',
            'v-2026q3-nongaap-eps-3pt22',
            'f-2026q2-nongaap-eps-0pt35'
        )
          AND status = 'SHADOW'
          AND comparison_op = '>'
          AND rounding_places = 2
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND source_policy -> 'sec' ->> 'form_type' = '8-K'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'sec' ->> 'document_type' = 'EX-99.1'
          AND (
              (
                  rule_key =
                      'hlt-2026q2-nongaap-eps-2pt25'
                  AND source_policy -> 'company_ir' ->> 'provider' =
                      'company_ir'
                  AND source_policy -> 'company_ir' ->> 'kind' =
                      'rss'
                  AND source_policy -> 'company_ir' ->> 'feed_url' =
                      'https://stories.hilton.com/feed/'
                  AND NOT source_policy ? 'press_wire'
              )
              OR (
                  rule_key <>
                      'hlt-2026q2-nongaap-eps-2pt25'
                  AND NOT source_policy ? 'company_ir'
                  AND NOT source_policy ? 'press_wire'
              )
          )
    ) <> 10 THEN
        RAISE EXCEPTION 'July earnings SEC rule set mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'hlt-2026q2-nongaap-eps-2pt25'
          AND scope_id = 'earnings:HLT:2026Q2'
          AND cik = '1585689'
          AND strike = 2.25
          AND condition_id = '0x619d7bfd2a712815069f0c8972149287a6f6fdfe21020d11e721ccd6bf4c3b4f'
    ) THEN
        RAISE EXCEPTION 'HLT earnings rule mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE rule_key = 'sbux-2026q3-gaap-eps-0pt69'
          AND scope_id = 'earnings:SBUX:2026Q3'
          AND metric_kind = 'gaap_eps'
          AND estimated_release_at = TIMESTAMPTZ '2026-07-29 20:05:00+00'
          AND market_slug = 'sbux-quarterly-earnings-gaap-eps-07-28-2026-0pt69'
    ) THEN
        RAISE EXCEPTION 'SBUX official release schedule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'earnings-pypl-2026q2',
            'earnings-ups-2026q2',
            'earnings-hlt-2026q2',
            'earnings-ivz-2026q2',
            'earnings-ko-2026q2',
            'earnings-jblu-2026q2',
            'earnings-spgi-2026q2',
            'earnings-sbux-2026q3',
            'earnings-v-2026q3',
            'earnings-f-2026q2'
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
    ) <> 10 THEN
        RAISE EXCEPTION 'July earnings SEC profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key IN (
            'PYPL:2026-07-28',
            'UPS:2026-07-28',
            'HLT:2026-07-28',
            'IVZ:2026-07-28',
            'KO:2026-07-28',
            'JBLU:2026-07-28',
            'SPGI:2026-07-28',
            'SBUX:2026-07-29',
            'V:2026-07-28',
            'F:2026-07-28'
        )
          AND metric_options ->> 'comparison_op' = '>'
          AND metric_options ->> 'primary_basis' = 'diluted'
          AND metric_options ->> 'market_basis' <> 'unverified'
    ) <> 10 THEN
        RAISE EXCEPTION 'July earnings SEC catalog set mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:PYPL:2026Q2',
            'earnings:UPS:2026Q2',
            'earnings:HLT:2026Q2',
            'earnings:IVZ:2026Q2',
            'earnings:KO:2026Q2',
            'earnings:JBLU:2026Q2',
            'earnings:SPGI:2026Q2',
            'earnings:SBUX:2026Q3',
            'earnings:V:2026Q3',
            'earnings:F:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'July earnings SEC execution claim must not exist';
    END IF;
END
$verification$;
