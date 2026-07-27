-- Add the remaining reviewed July 28 earnings rules as SEC-first profiles.
-- Starbucks is included with its official July 29 release time. Every
-- execution profile is deliberately disabled, and this seed cannot create
-- execution claims or enable trading.

BEGIN;

WITH batch (
    rule_key,
    scope_id,
    profile_key,
    ticker,
    cik,
    fiscal_quarter,
    period_end,
    estimated_release_at,
    metric_kind,
    strike,
    market_slug,
    condition_id,
    metric_selection
) AS (
    VALUES
    (
        'pypl-2026q2-nongaap-eps-1pt28',
        'earnings:PYPL:2026Q2',
        'earnings-pypl-2026q2',
        'PYPL',
        '1633917',
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-28 11:00:00+00',
        'non_gaap_eps',
        1.28::numeric,
        'pypl-quarterly-earnings-nongaap-eps-07-28-2026-1pt28',
        '0x886e4e085085f3e22e5d187872d974558b5aa8a2b8da97b838891b910328297a',
        'primary_headline_non_gaap_diluted_eps'
    ),
    (
        'ups-2026q2-nongaap-eps-1pt66',
        'earnings:UPS:2026Q2',
        'earnings-ups-2026q2',
        'UPS',
        '1090727',
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-28 10:00:00+00',
        'non_gaap_eps',
        1.66::numeric,
        'ups-quarterly-earnings-nongaap-eps-07-28-2026-1pt66',
        '0xf315abadca7a0a77f7c98cb8710dff265d5ba5a6324b4aeda8a0bb7ca9e25363',
        'reported_non_gaap_diluted_eps'
    ),
    (
        'hlt-2026q2-nongaap-eps-2pt25',
        'earnings:HLT:2026Q2',
        'earnings-hlt-2026q2',
        'HLT',
        '1585689',
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-28 10:00:00+00',
        'non_gaap_eps',
        2.25::numeric,
        'hlt-quarterly-earnings-nongaap-eps-07-28-2026-2pt25',
        '0x619d7bfd2a712815069f0c8972149287a6f6fdfe21020d11e721ccd6bf4c3b4f',
        'reported_diluted_eps_adjusted_for_special_items'
    ),
    (
        'ivz-2026q2-nongaap-eps-0pt66',
        'earnings:IVZ:2026Q2',
        'earnings-ivz-2026q2',
        'IVZ',
        '914208',
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-28 11:00:00+00',
        'non_gaap_eps',
        0.66::numeric,
        'ivz-quarterly-earnings-nongaap-eps-07-28-2026-0pt66',
        '0x82ec63891a948896db5b07aa8c9a69e3be4dea6aadff8cbffd0235de64add22a',
        'headline_adjusted_diluted_eps'
    ),
    (
        'ko-2026q2-nongaap-eps-0pt93',
        'earnings:KO:2026Q2',
        'earnings-ko-2026q2',
        'KO',
        '21344',
        2,
        DATE '2026-07-03',
        TIMESTAMPTZ '2026-07-28 10:55:00+00',
        'non_gaap_eps',
        0.93::numeric,
        'ko-quarterly-earnings-nongaap-eps-07-28-2026-0pt93',
        '0xe9bed1463db58e7022ec1c2e2cadb0d80d98594095eda33f28f24e4c72a0c13a',
        'headline_comparable_non_gaap_eps'
    ),
    (
        'jblu-2026q2-nongaap-eps-neg0pt68',
        'earnings:JBLU:2026Q2',
        'earnings-jblu-2026q2',
        'JBLU',
        '1158463',
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-28 10:00:00+00',
        'non_gaap_eps',
        -0.68::numeric,
        'jblu-quarterly-earnings-nongaap-eps-07-28-2026-neg0pt68',
        '0xaf185284cf45118d3b8516b2b999ebaa447ff2ce5ea98b908381cfc7895cba09',
        'diluted_eps_excluding_special_items_and_investments'
    ),
    (
        'spgi-2026q2-nongaap-eps-4pt95',
        'earnings:SPGI:2026Q2',
        'earnings-spgi-2026q2',
        'SPGI',
        '64040',
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-28 11:15:00+00',
        'non_gaap_eps',
        4.95::numeric,
        'spgi-quarterly-earnings-nongaap-eps-07-28-2026-4pt95',
        '0x58b58b75326faeebe77cbb9ff311e8a728af91da3e30a5a6c7407aa2a0c96243',
        'reported_adjusted_diluted_eps'
    ),
    (
        'sbux-2026q3-gaap-eps-0pt69',
        'earnings:SBUX:2026Q3',
        'earnings-sbux-2026q3',
        'SBUX',
        '829224',
        3,
        DATE '2026-06-28',
        TIMESTAMPTZ '2026-07-29 20:05:00+00',
        'gaap_eps',
        0.69::numeric,
        'sbux-quarterly-earnings-gaap-eps-07-28-2026-0pt69',
        '0xbe6f10dca602f8a71893486557fb9401303742f51ac4e12eaab55b3fb1bc2a30',
        'primary_headline_gaap_diluted_eps'
    ),
    (
        'v-2026q3-nongaap-eps-3pt22',
        'earnings:V:2026Q3',
        'earnings-v-2026q3',
        'V',
        '1403161',
        3,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-28 20:05:00+00',
        'non_gaap_eps',
        3.22::numeric,
        'v-quarterly-earnings-nongaap-eps-07-28-2026-3pt22',
        '0xcda59edf4df94ee2326a0686cc8375cedc01eca39471a116985019591a83e146',
        'headline_non_gaap_diluted_eps'
    ),
    (
        'f-2026q2-nongaap-eps-0pt35',
        'earnings:F:2026Q2',
        'earnings-f-2026q2',
        'F',
        '37996',
        2,
        DATE '2026-06-30',
        TIMESTAMPTZ '2026-07-28 20:05:00+00',
        'non_gaap_eps',
        0.35::numeric,
        'f-quarterly-earnings-nongaap-eps-07-28-2026-0pt35',
        '0xdbcc8b389165b2de94773f6074acba1ac689e2b585ea75dc2ae0980941036900',
        'adjusted_non_gaap_diluted_eps'
    )
)
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
SELECT
    rule_key,
    scope_id,
    ticker,
    cik,
    2026,
    fiscal_quarter,
    period_end,
    estimated_release_at,
    metric_kind,
    'diluted',
    'basic',
    '>',
    strike,
    2,
    'USD',
    market_slug,
    condition_id,
    jsonb_build_object(
        'initial_release_only', true,
        'metric_selection', metric_selection,
        'primary_authority', 'official_company',
        'sec', jsonb_build_object(
            'document_type', 'EX-99.1',
            'form_type', '8-K',
            'required_item', '2.02'
        )
    ),
    jsonb_build_object(
        CASE
            WHEN metric_kind = 'gaap_eps'
                THEN 'gaap_secondary'
            ELSE 'non_gaap_secondary'
        END,
        'seeking_alpha',
        'gaap_after_hours', 96,
        'gaap_fallback_basis', 'basic',
        'gaap_primary_basis', 'diluted',
        'no_release_after_days', 45
    ),
    'SHADOW'
FROM batch
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

WITH batch (
    rule_key,
    scope_id,
    profile_key,
    ticker,
    market_slug,
    condition_id,
    prepare_from,
    expires_at
) AS (
    VALUES
    (
        'pypl-2026q2-nongaap-eps-1pt28',
        'earnings:PYPL:2026Q2',
        'earnings-pypl-2026q2',
        'PYPL',
        'pypl-quarterly-earnings-nongaap-eps-07-28-2026-1pt28',
        '0x886e4e085085f3e22e5d187872d974558b5aa8a2b8da97b838891b910328297a',
        TIMESTAMPTZ '2026-07-28 09:00:00+00',
        TIMESTAMPTZ '2026-07-28 17:00:00+00'
    ),
    (
        'ups-2026q2-nongaap-eps-1pt66',
        'earnings:UPS:2026Q2',
        'earnings-ups-2026q2',
        'UPS',
        'ups-quarterly-earnings-nongaap-eps-07-28-2026-1pt66',
        '0xf315abadca7a0a77f7c98cb8710dff265d5ba5a6324b4aeda8a0bb7ca9e25363',
        TIMESTAMPTZ '2026-07-28 09:00:00+00',
        TIMESTAMPTZ '2026-07-28 17:00:00+00'
    ),
    (
        'hlt-2026q2-nongaap-eps-2pt25',
        'earnings:HLT:2026Q2',
        'earnings-hlt-2026q2',
        'HLT',
        'hlt-quarterly-earnings-nongaap-eps-07-28-2026-2pt25',
        '0x619d7bfd2a712815069f0c8972149287a6f6fdfe21020d11e721ccd6bf4c3b4f',
        TIMESTAMPTZ '2026-07-28 09:00:00+00',
        TIMESTAMPTZ '2026-07-28 17:00:00+00'
    ),
    (
        'ivz-2026q2-nongaap-eps-0pt66',
        'earnings:IVZ:2026Q2',
        'earnings-ivz-2026q2',
        'IVZ',
        'ivz-quarterly-earnings-nongaap-eps-07-28-2026-0pt66',
        '0x82ec63891a948896db5b07aa8c9a69e3be4dea6aadff8cbffd0235de64add22a',
        TIMESTAMPTZ '2026-07-28 09:00:00+00',
        TIMESTAMPTZ '2026-07-28 17:00:00+00'
    ),
    (
        'ko-2026q2-nongaap-eps-0pt93',
        'earnings:KO:2026Q2',
        'earnings-ko-2026q2',
        'KO',
        'ko-quarterly-earnings-nongaap-eps-07-28-2026-0pt93',
        '0xe9bed1463db58e7022ec1c2e2cadb0d80d98594095eda33f28f24e4c72a0c13a',
        TIMESTAMPTZ '2026-07-28 09:00:00+00',
        TIMESTAMPTZ '2026-07-28 17:00:00+00'
    ),
    (
        'jblu-2026q2-nongaap-eps-neg0pt68',
        'earnings:JBLU:2026Q2',
        'earnings-jblu-2026q2',
        'JBLU',
        'jblu-quarterly-earnings-nongaap-eps-07-28-2026-neg0pt68',
        '0xaf185284cf45118d3b8516b2b999ebaa447ff2ce5ea98b908381cfc7895cba09',
        TIMESTAMPTZ '2026-07-28 09:00:00+00',
        TIMESTAMPTZ '2026-07-28 17:00:00+00'
    ),
    (
        'spgi-2026q2-nongaap-eps-4pt95',
        'earnings:SPGI:2026Q2',
        'earnings-spgi-2026q2',
        'SPGI',
        'spgi-quarterly-earnings-nongaap-eps-07-28-2026-4pt95',
        '0x58b58b75326faeebe77cbb9ff311e8a728af91da3e30a5a6c7407aa2a0c96243',
        TIMESTAMPTZ '2026-07-28 09:00:00+00',
        TIMESTAMPTZ '2026-07-28 17:00:00+00'
    ),
    (
        'sbux-2026q3-gaap-eps-0pt69',
        'earnings:SBUX:2026Q3',
        'earnings-sbux-2026q3',
        'SBUX',
        'sbux-quarterly-earnings-gaap-eps-07-28-2026-0pt69',
        '0xbe6f10dca602f8a71893486557fb9401303742f51ac4e12eaab55b3fb1bc2a30',
        TIMESTAMPTZ '2026-07-29 18:00:00+00',
        TIMESTAMPTZ '2026-07-30 02:00:00+00'
    ),
    (
        'v-2026q3-nongaap-eps-3pt22',
        'earnings:V:2026Q3',
        'earnings-v-2026q3',
        'V',
        'v-quarterly-earnings-nongaap-eps-07-28-2026-3pt22',
        '0xcda59edf4df94ee2326a0686cc8375cedc01eca39471a116985019591a83e146',
        TIMESTAMPTZ '2026-07-28 18:00:00+00',
        TIMESTAMPTZ '2026-07-29 02:00:00+00'
    ),
    (
        'f-2026q2-nongaap-eps-0pt35',
        'earnings:F:2026Q2',
        'earnings-f-2026q2',
        'F',
        'f-quarterly-earnings-nongaap-eps-07-28-2026-0pt35',
        '0xdbcc8b389165b2de94773f6074acba1ac689e2b585ea75dc2ae0980941036900',
        TIMESTAMPTZ '2026-07-28 18:00:00+00',
        TIMESTAMPTZ '2026-07-29 02:00:00+00'
    )
)
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
SELECT
    profile_key,
    scope_id,
    'earnings_resolution',
    'https://polymarket.com/event/' || market_slug,
    'abccbaq',
    condition_id,
    0.999,
    0.999,
    50,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    prepare_from,
    expires_at,
    jsonb_build_object(
        'profile_template_key', 'default',
        'rule_key', rule_key,
        'ticker', ticker
    ),
    'DISABLED'
FROM batch
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

WITH batch (
    event_key,
    metric_kind,
    strike
) AS (
    VALUES
    ('PYPL:2026-07-28', 'non_gaap_eps', '1.28'),
    ('UPS:2026-07-28', 'non_gaap_eps', '1.66'),
    ('HLT:2026-07-28', 'non_gaap_eps', '2.25'),
    ('IVZ:2026-07-28', 'non_gaap_eps', '0.66'),
    ('KO:2026-07-28', 'non_gaap_eps', '0.93'),
    ('JBLU:2026-07-28', 'non_gaap_eps', '-0.68'),
    ('SPGI:2026-07-28', 'non_gaap_eps', '4.95'),
    ('SBUX:2026-07-29', 'gaap_eps', '0.69'),
    ('V:2026-07-28', 'non_gaap_eps', '3.22'),
    ('F:2026-07-28', 'non_gaap_eps', '0.35')
)
UPDATE earnings_release_catalog AS catalog
SET
    metric_options = jsonb_build_object(
        'comparison_op', '>',
        'fallback_basis', 'basic',
        'market_basis', batch.metric_kind,
        'primary_basis', 'diluted',
        'reported', jsonb_build_array(batch.metric_kind),
        'strike', batch.strike
    ),
    notes = (
        'Exact Polymarket EPS basis verified; initial official SEC '
        'Item 2.02 / EX-99.1 parser and disabled profile are ready.'
    ),
    verified_at = now(),
    updated_at = now()
FROM batch
WHERE catalog.event_key = batch.event_key;

COMMIT;
