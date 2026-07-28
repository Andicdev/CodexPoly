-- Add three reviewed July 28 earnings rules and deliberately disabled
-- execution profiles. This seed cannot enable trading or create claims.

BEGIN;

INSERT INTO earnings_market_rules (
    rule_key,
    scope_id,
    ticker,
    cik,
    fiscal_year,
    fiscal_quarter,
    period_end,
    estimated_release_at,
    metric_kind,
    primary_basis,
    fallback_basis,
    comparison_op,
    strike,
    rounding_places,
    currency,
    market_slug,
    condition_id,
    source_policy,
    fallback_policy,
    status
)
VALUES
(
    'ba-2026q2-nongaap-eps-neg0pt32',
    'earnings:BA:2026Q2',
    'BA',
    '12927',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-28 11:30:00+00',
    'non_gaap_eps',
    'diluted',
    'basic',
    '>',
    -0.32,
    2,
    'USD',
    'ba-quarterly-earnings-nongaap-eps-07-28-2026-neg0pt32',
    '0x9073468de3e2675f39232dfa39ec131ccb5d181807ce1c56432ebb8c2843100f',
    '{
        "initial_release_only": true,
        "metric_selection": "primary_headline_non_gaap_diluted_eps",
        "primary_authority": "official_company",
        "sec": {
            "document_type": "EX-99.1",
            "form_type": "8-K",
            "required_item": "2.02"
        },
        "company_ir": {
            "allowed_document_hosts": ["investors.boeing.com"],
            "feed_url": "https://investors.boeing.com/rss/pressrelease.aspx",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": ["Boeing", "Second Quarter", "Results"],
            "title_none": ["to release"]
        }
    }'::jsonb,
    '{
        "non_gaap_secondary": "seeking_alpha",
        "gaap_after_hours": 96,
        "gaap_fallback_basis": "basic",
        "gaap_primary_basis": "diluted",
        "no_release_after_days": 45
    }'::jsonb,
    'SHADOW'
),
(
    'czr-2026q2-gaap-eps-0pt05',
    'earnings:CZR:2026Q2',
    'CZR',
    '1590895',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-28 20:05:00+00',
    'gaap_eps',
    'diluted',
    'basic',
    '>',
    0.05,
    2,
    'USD',
    'czr-quarterly-earnings-gaap-eps-07-28-2026-0pt05',
    '0x13805b2ba317a2c26ff596bb59534c23c4808fd26eac9be6f847977b92fd6bf3',
    '{
        "initial_release_only": true,
        "metric_selection": "official_gaap_diluted_eps",
        "primary_authority": "official_company",
        "sec": {
            "document_type": "EX-99.1",
            "form_type": "8-K",
            "required_item": "2.02"
        },
        "company_ir": {
            "allowed_document_hosts": ["investor.caesars.com"],
            "feed_url": "https://investor.caesars.com/rss/news-releases.xml",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "Caesars Entertainment",
                "Second Quarter",
                "Results"
            ],
            "title_none": ["to report"]
        }
    }'::jsonb,
    '{
        "gaap_secondary": "seeking_alpha",
        "gaap_fallback_basis": "basic",
        "gaap_primary_basis": "diluted",
        "no_release_after_days": 45
    }'::jsonb,
    'SHADOW'
),
(
    'csgp-2026q2-gaap-eps-0pt10',
    'earnings:CSGP:2026Q2',
    'CSGP',
    '1057352',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-28 20:05:00+00',
    'gaap_eps',
    'diluted',
    'basic',
    '>',
    0.10,
    2,
    'USD',
    'csgp-quarterly-earnings-gaap-eps-07-28-2026-0pt1',
    '0xb71e441b6853dc1c3e1480b6d772b63cd8a907e706c1b1a4862c3ffa794ac418',
    '{
        "initial_release_only": true,
        "metric_selection": "official_gaap_diluted_eps",
        "primary_authority": "official_company",
        "sec": {
            "document_type": "EX-99.1",
            "form_type": "8-K",
            "required_item": "2.02"
        },
        "company_ir": {
            "allowed_document_hosts": ["investors.costargroup.com"],
            "feed_url": "https://investors.costargroup.com/rss/news-releases.xml",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": ["CoStar Group", "Q2"],
            "title_none": [
                "to report",
                "will report",
                "conference call"
            ]
        }
    }'::jsonb,
    '{
        "gaap_secondary": "seeking_alpha",
        "gaap_fallback_basis": "basic",
        "gaap_primary_basis": "diluted",
        "no_release_after_days": 45
    }'::jsonb,
    'SHADOW'
)
ON CONFLICT (rule_key) DO UPDATE
SET
    scope_id = EXCLUDED.scope_id,
    ticker = EXCLUDED.ticker,
    cik = EXCLUDED.cik,
    fiscal_year = EXCLUDED.fiscal_year,
    fiscal_quarter = EXCLUDED.fiscal_quarter,
    period_end = EXCLUDED.period_end,
    estimated_release_at = EXCLUDED.estimated_release_at,
    metric_kind = EXCLUDED.metric_kind,
    primary_basis = EXCLUDED.primary_basis,
    fallback_basis = EXCLUDED.fallback_basis,
    comparison_op = EXCLUDED.comparison_op,
    strike = EXCLUDED.strike,
    rounding_places = EXCLUDED.rounding_places,
    currency = EXCLUDED.currency,
    market_slug = EXCLUDED.market_slug,
    condition_id = EXCLUDED.condition_id,
    source_policy = EXCLUDED.source_policy,
    fallback_policy = EXCLUDED.fallback_policy,
    updated_at = now();

INSERT INTO resolution_execution_profiles (
    profile_key,
    scope_id,
    source_name,
    source_reference,
    account_name,
    condition_id,
    yes_desired_price,
    no_desired_price,
    quantity,
    lifecycle_kind,
    old_tick,
    new_tick,
    max_reprices,
    prepare_from,
    expires_at,
    metadata,
    status
)
VALUES
(
    'earnings-ba-2026q2',
    'earnings:BA:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/ba-quarterly-earnings-nongaap-eps-07-28-2026-neg0pt32',
    'abccbaq',
    '0x9073468de3e2675f39232dfa39ec131ccb5d181807ce1c56432ebb8c2843100f',
    0.999,
    0.999,
    50,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-28 10:00:00+00',
    TIMESTAMPTZ '2026-07-28 17:00:00+00',
    '{
        "profile_template_key": "default",
        "rule_key": "ba-2026q2-nongaap-eps-neg0pt32",
        "ticker": "BA"
    }'::jsonb,
    'DISABLED'
),
(
    'earnings-czr-2026q2',
    'earnings:CZR:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/czr-quarterly-earnings-gaap-eps-07-28-2026-0pt05',
    'abccbaq',
    '0x13805b2ba317a2c26ff596bb59534c23c4808fd26eac9be6f847977b92fd6bf3',
    0.999,
    0.999,
    50,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-28 18:00:00+00',
    TIMESTAMPTZ '2026-07-29 02:00:00+00',
    '{
        "profile_template_key": "default",
        "rule_key": "czr-2026q2-gaap-eps-0pt05",
        "ticker": "CZR"
    }'::jsonb,
    'DISABLED'
),
(
    'earnings-csgp-2026q2',
    'earnings:CSGP:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/csgp-quarterly-earnings-gaap-eps-07-28-2026-0pt1',
    'abccbaq',
    '0xb71e441b6853dc1c3e1480b6d772b63cd8a907e706c1b1a4862c3ffa794ac418',
    0.999,
    0.999,
    50,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-28 18:00:00+00',
    TIMESTAMPTZ '2026-07-29 02:00:00+00',
    '{
        "profile_template_key": "default",
        "rule_key": "csgp-2026q2-gaap-eps-0pt10",
        "ticker": "CSGP"
    }'::jsonb,
    'DISABLED'
)
ON CONFLICT (profile_key) DO UPDATE
SET
    scope_id = EXCLUDED.scope_id,
    source_name = EXCLUDED.source_name,
    source_reference = EXCLUDED.source_reference,
    account_name = EXCLUDED.account_name,
    condition_id = EXCLUDED.condition_id,
    yes_desired_price = EXCLUDED.yes_desired_price,
    no_desired_price = EXCLUDED.no_desired_price,
    quantity = EXCLUDED.quantity,
    lifecycle_kind = EXCLUDED.lifecycle_kind,
    old_tick = EXCLUDED.old_tick,
    new_tick = EXCLUDED.new_tick,
    max_reprices = EXCLUDED.max_reprices,
    prepare_from = EXCLUDED.prepare_from,
    expires_at = EXCLUDED.expires_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
WHERE resolution_execution_profiles.status = 'DISABLED';

UPDATE earnings_release_catalog
SET
    metric_options = '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "non_gaap_eps",
        "primary_basis": "diluted",
        "reported": ["gaap_eps", "non_gaap_eps"],
        "strike": "-0.32"
    }'::jsonb,
    notes = (
        'Exact Polymarket basis verified: Boeing primary headline core '
        'non-GAAP EPS greater than -0.32 USD.'
    ),
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'BA:2026-07-28';

UPDATE earnings_release_catalog
SET
    metric_options = '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "gaap_eps",
        "primary_basis": "diluted",
        "reported": ["gaap_eps"],
        "strike": "0.05"
    }'::jsonb,
    notes = (
        'Exact Polymarket basis verified: official GAAP diluted EPS '
        'greater than 0.05 USD.'
    ),
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'CZR:2026-07-28';

UPDATE earnings_release_catalog
SET
    metric_options = '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "gaap_eps",
        "primary_basis": "diluted",
        "reported": ["gaap_eps", "adjusted_eps"],
        "strike": "0.10"
    }'::jsonb,
    notes = (
        'Exact Polymarket basis verified: official GAAP diluted EPS '
        'greater than 0.10 USD; adjusted EPS is excluded.'
    ),
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'CSGP:2026-07-28';

COMMIT;
