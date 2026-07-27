-- Add the reviewed NXPI Q2 2026 rule and a deliberately disabled execution
-- profile. This seed does not enable trading or create source events.

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
VALUES (
    'nxpi-2026q2-nongaap-eps-3pt53',
    'earnings:NXPI:2026Q2',
    'NXPI',
    '1413447',
    2026,
    2,
    DATE '2026-06-28',
    TIMESTAMPTZ '2026-07-28 20:10:00+00',
    'non_gaap_eps',
    'diluted',
    'basic',
    '>',
    3.53,
    2,
    'USD',
    'nxpi-quarterly-earnings-nongaap-eps-07-28-2026-3pt53',
    '0x70676300a6fffc684d86850f30c8c34a64557f86c1f3fb377568bacb73585ff4',
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
            "allowed_document_hosts": [
                "investors.nxp.com"
            ],
            "feed_url": "https://investors.nxp.com/rss/news-releases.xml",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "NXP Semiconductors",
                "Second Quarter 2026",
                "Results"
            ],
            "title_none": [
                "to report"
            ]
        },
        "press_wire": {
            "allowed_document_hosts": [
                "www.globenewswire.com"
            ],
            "feed_url": "https://www.globenewswire.com/RssFeed/subjectcode/13-Earnings%20Releases%20And%20Operating%20Results/feedTitle/GlobeNewswire%20-%20Earnings%20Releases%20And%20Operating%20Results",
            "kind": "rss",
            "provider": "globenewswire",
            "title_all": [
                "NXP Semiconductors",
                "Second Quarter 2026",
                "Results"
            ],
            "title_none": [
                "to report"
            ]
        }
    }'::jsonb,
    '{
        "gaap_after_hours": 96,
        "gaap_fallback_basis": "basic",
        "gaap_primary_basis": "diluted",
        "no_release_after_days": 45,
        "non_gaap_secondary": "seeking_alpha"
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
VALUES (
    'earnings-nxpi-2026q2',
    'earnings:NXPI:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/nxpi-quarterly-earnings-nongaap-eps-07-28-2026-3pt53',
    'abccbaq',
    '0x70676300a6fffc684d86850f30c8c34a64557f86c1f3fb377568bacb73585ff4',
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
        "rule_key": "nxpi-2026q2-nongaap-eps-3pt53",
        "ticker": "NXPI"
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
        "strike": "3.53"
    }'::jsonb,
    notes = (
        'Exact Polymarket basis verified: primary headline non-GAAP '
        'diluted EPS greater than 3.53 USD.'
    ),
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'NXPI:2026-07-28';

COMMIT;
