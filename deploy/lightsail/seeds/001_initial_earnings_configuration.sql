-- Initial non-secret earnings configuration for the isolated Lightsail DB.
-- Runtime events, execution claims, orders, and trading account rows are not
-- copied. Execution profiles are deliberately kept DISABLED.

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
        'nvts-2026q2-nongaap-eps-neg0pt04',
        'earnings:NVTS:2026Q2',
        'NVTS',
        '1821769',
        2026,
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-27 21:00:00+00',
        'non_gaap_eps',
        'diluted',
        'basic',
        '>',
        -0.04,
        2,
        'USD',
        'nvts-quarterly-earnings-nongaap-eps-07-27-2026-neg0pt04',
        '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d',
        '{
            "initial_release_only": true,
            "primary_authority": "official_company",
            "sec": {
                "document_type": "EX-99.1",
                "form_type": "8-K",
                "required_item": "2.02"
            }
        }'::jsonb,
        '{
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
            "non_gaap_secondary": "seeking_alpha"
        }'::jsonb,
        'SHADOW'
    ),
    (
        'wwd-2026q3-gaap-eps-2pt42',
        'earnings:WWD:2026Q3',
        'WWD',
        '108312',
        2026,
        3,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-29 20:00:00+00',
        'gaap_eps',
        'diluted',
        'basic',
        '>',
        2.42,
        2,
        'USD',
        'wwd-quarterly-earnings-gaap-eps-07-27-2026-2pt42',
        '0x4e84af80ebdd0c2e658c9b29f7a847289c758117d9d47382f3bfc5fb0df157ff',
        '{
            "initial_release_only": true,
            "primary_authority": "official_company",
            "sec": {
                "document_type": "EX-99.1",
                "form_type": "8-K",
                "required_item": "2.02"
            }
        }'::jsonb,
        '{
            "gaap_secondary": "seeking_alpha",
            "no_release_after_days": 45,
            "secondary_after_hours": 96
        }'::jsonb,
        'SHADOW'
    ),
    (
        'bbby-2026q2-nongaap-eps-neg0pt26',
        'earnings:BBBY:2026Q2',
        'BBBY',
        '1130713',
        2026,
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-08-04 20:00:00+00',
        'non_gaap_eps',
        'diluted',
        'basic',
        '>',
        -0.26,
        2,
        'USD',
        'bbby-quarterly-earnings-nongaap-eps-07-27-2026-neg0pt26',
        '0x2a6affd160ac8d394da6a12d8ff1479e20e1f6efa22e46001d82ea99665f1045',
        '{
            "initial_release_only": true,
            "primary_authority": "official_company",
            "sec": {
                "document_type": "EX-99.1",
                "form_type": "8-K",
                "required_item": "2.02"
            }
        }'::jsonb,
        '{
            "gaap_after_hours": 96,
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
VALUES
    (
        'earnings-nvts-2026q2',
        'earnings:NVTS:2026Q2',
        'earnings_resolution',
        'https://polymarket.com/event/nvts-quarterly-earnings-nongaap-eps-07-27-2026-neg0pt04',
        'abccbaq',
        '0xa9397ae270be6e9dec1cdd1d89b3e122b2a60647271261cda138bced069f7d9d',
        0.999,
        0.999,
        50,
        'reprice_on_tick_change',
        0.01,
        0.001,
        1,
        TIMESTAMPTZ '2026-07-27 19:00:00+00',
        TIMESTAMPTZ '2026-07-28 03:00:00+00',
        '{
            "profile_template_key": "default",
            "rule_key": "nvts-2026q2-nongaap-eps-neg0pt04",
            "ticker": "NVTS"
        }'::jsonb,
        'DISABLED'
    ),
    (
        'earnings-wwd-2026q3',
        'earnings:WWD:2026Q3',
        'earnings_resolution',
        'https://polymarket.com/event/wwd-quarterly-earnings-gaap-eps-07-27-2026-2pt42',
        'abccbaq',
        '0x4e84af80ebdd0c2e658c9b29f7a847289c758117d9d47382f3bfc5fb0df157ff',
        0.999,
        0.999,
        50,
        'reprice_on_tick_change',
        0.01,
        0.001,
        1,
        TIMESTAMPTZ '2026-07-29 18:00:00+00',
        TIMESTAMPTZ '2026-07-30 02:00:00+00',
        '{
            "profile_template_key": "default",
            "rule_key": "wwd-2026q3-gaap-eps-2pt42",
            "ticker": "WWD"
        }'::jsonb,
        'DISABLED'
    ),
    (
        'earnings-bbby-2026q2',
        'earnings:BBBY:2026Q2',
        'earnings_resolution',
        'https://polymarket.com/event/bbby-quarterly-earnings-nongaap-eps-07-27-2026-neg0pt26',
        'abccbaq',
        '0x2a6affd160ac8d394da6a12d8ff1479e20e1f6efa22e46001d82ea99665f1045',
        0.999,
        0.999,
        50,
        'reprice_on_tick_change',
        0.01,
        0.001,
        1,
        TIMESTAMPTZ '2026-08-04 18:00:00+00',
        TIMESTAMPTZ '2026-08-05 02:00:00+00',
        '{
            "profile_template_key": "default",
            "rule_key": "bbby-2026q2-nongaap-eps-neg0pt26",
            "ticker": "BBBY"
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

COMMIT;
