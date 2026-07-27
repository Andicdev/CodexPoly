-- Add the reviewed RCL Q2 2026 rule and a deliberately disabled execution
-- profile. This seed cannot enable trading or create execution claims.

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
    'rcl-2026q2-nongaap-eps-3pt97',
    'earnings:RCL:2026Q2',
    'RCL',
    '884887',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-28 10:30:00+00',
    'non_gaap_eps',
    'diluted',
    'basic',
    '>',
    3.97,
    2,
    'USD',
    'rcl-quarterly-earnings-nongaap-eps-07-28-2026-3pt97',
    '0x8701e9a10812190db05c6f703b4dd3d8d978ac171874c78bb26b2f23d7a38976',
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
                "www.rclinvestor.com"
            ],
            "feed_url": "https://www.rclinvestor.com/press-releases/",
            "kind": "html_listing",
            "listing_utc_offset_minutes": -240,
            "provider": "company_ir",
            "title_all": [
                "Royal Caribbean Group",
                "Reports",
                "Second Quarter",
                "Results"
            ],
            "title_none": [
                "to hold",
                "conference call"
            ]
        },
        "press_wire": {
            "allowed_document_hosts": [
                "www.prnewswire.com"
            ],
            "feed_url": "https://www.prnewswire.com/rss/news-releases-list.rss",
            "kind": "rss",
            "provider": "prnewswire",
            "title_all": [
                "Royal Caribbean Group",
                "Reports",
                "Second Quarter",
                "Results"
            ],
            "title_none": [
                "to hold",
                "conference call"
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
    'earnings-rcl-2026q2',
    'earnings:RCL:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/rcl-quarterly-earnings-nongaap-eps-07-28-2026-3pt97',
    'abccbaq',
    '0x8701e9a10812190db05c6f703b4dd3d8d978ac171874c78bb26b2f23d7a38976',
    0.999,
    0.999,
    50,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-28 09:00:00+00',
    TIMESTAMPTZ '2026-07-28 17:00:00+00',
    '{
        "profile_template_key": "default",
        "rule_key": "rcl-2026q2-nongaap-eps-3pt97",
        "ticker": "RCL"
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
        "strike": "3.97"
    }'::jsonb,
    source_options = '[
        {
            "delivery": "websocket",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "html_listing",
            "listing_url": "https://www.rclinvestor.com/press-releases/",
            "provider": "company_ir",
            "status": "verified_full_html"
        },
        {
            "delivery": "rss",
            "listing_url": "https://www.prnewswire.com/rss/news-releases-list.rss",
            "provider": "prnewswire",
            "status": "verified_full_html"
        }
    ]'::jsonb,
    notes = (
        'Exact Polymarket basis verified: Royal Caribbean primary '
        'headline adjusted diluted EPS greater than 3.97 USD.'
    ),
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'RCL:2026-07-28';

COMMIT;
