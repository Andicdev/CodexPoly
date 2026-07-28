-- Add the remaining confirmed July 29 pre-market earnings profiles and
-- public transports. All profiles remain DISABLED and all schedules remain
-- AUTO_PREFLIGHT. This seed cannot authorize live trading.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TEMP TABLE july29_premarket_additions (
    rule_key text PRIMARY KEY,
    profile_key text NOT NULL UNIQUE,
    scope_id text NOT NULL UNIQUE,
    ticker text NOT NULL UNIQUE,
    cik text NOT NULL,
    fiscal_quarter smallint NOT NULL,
    period_end date NOT NULL,
    estimated_release_at timestamptz NOT NULL,
    metric_kind text NOT NULL,
    strike numeric(20, 10) NOT NULL,
    market_slug text NOT NULL,
    condition_id text NOT NULL UNIQUE,
    metric_selection text NOT NULL,
    schedule_source_url text NOT NULL,
    conference_call_at timestamptz,
    source_additions jsonb NOT NULL,
    source_options jsonb NOT NULL
) ON COMMIT DROP;

INSERT INTO july29_premarket_additions VALUES
(
    'wing-2026q2-gaap-eps-1pt03',
    'earnings-wing-2026q2',
    'earnings:WING:2026Q2',
    'WING',
    '1636222',
    2,
    DATE '2026-06-27',
    TIMESTAMPTZ '2026-07-29 11:45:00+00',
    'gaap_eps',
    1.03,
    'wing-quarterly-earnings-gaap-eps-07-29-2026-1pt03',
    '0x364b6da0b6c766eb072c3be8ded36b6fc39e5b8c831346fd2e277d2c1d07714a',
    'headline_gaap_diluted_eps',
    'https://ir.wingstop.com/wingstop-inc-to-announce-fiscal-second-quarter-2026-financial-results-on-july-29-2026/',
    TIMESTAMPTZ '2026-07-29 14:00:00+00',
    '{
        "company_ir": {
            "allowed_document_hosts": ["ir.wingstop.com"],
            "feed_url": "https://ir.wingstop.com/feed/",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "Wingstop",
                "Second Quarter",
                "Financial Results"
            ],
            "title_none": ["to announce"]
        },
        "press_wire": {
            "allowed_document_hosts": ["www.prnewswire.com"],
            "feed_url": "https://www.prnewswire.com/rss/news-releases-list.rss",
            "kind": "rss",
            "provider": "prnewswire",
            "title_all": [
                "Wingstop",
                "Second Quarter",
                "Financial Results"
            ],
            "title_none": ["to announce"]
        }
    }'::jsonb,
    '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "rss",
            "provider": "company_ir",
            "status": "verified"
        },
        {
            "delivery": "rss",
            "provider": "prnewswire",
            "status": "verified"
        }
    ]'::jsonb
),
(
    'arcc-2026q2-nongaap-eps-0pt47',
    'earnings-arcc-2026q2',
    'earnings:ARCC:2026Q2',
    'ARCC',
    '1287750',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 11:00:00+00',
    'non_gaap_eps',
    0.47,
    'arcc-quarterly-earnings-nongaap-eps-07-29-2026-0pt47',
    '0xc1d7ebaa2951adedf0e111c0555e29426755d005dedb43ce71bf7d1c065a22b8',
    'operating_results_core_eps',
    'https://arcc.ares.com/news/ares-capital-corporation-schedules-earnings-release-for-the-second-quarter-ended-june-30-2026/e249695c-8669-49db-9d91-391c9212f9b2',
    TIMESTAMPTZ '2026-07-29 16:00:00+00',
    '{
        "press_wire": {
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": [
                "Ares Capital Corporation",
                "June 30, 2026",
                "Financial Results"
            ],
            "title_none": ["Schedules"]
        }
    }'::jsonb,
    '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "rss",
            "provider": "businesswire",
            "status": "verified"
        }
    ]'::jsonb
),
(
    'iart-2026q2-nongaap-eps-0pt48',
    'earnings-iart-2026q2',
    'earnings:IART:2026Q2',
    'IART',
    '917520',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 10:00:00+00',
    'non_gaap_eps',
    0.48,
    'iart-quarterly-earnings-nongaap-eps-07-29-2026-0pt48',
    '0x105f7e63b07c079be5e52a3c15ba8ce15022c45b189ea9a54d23c31bd972eb1f',
    'reported_adjusted_diluted_eps',
    'https://investor.integralife.com/news-releases/news-release-details/integra-lifesciences-host-second-quarter-2026-financial-results',
    TIMESTAMPTZ '2026-07-29 12:30:00+00',
    '{
        "company_ir": {
            "allowed_document_hosts": ["investor.integralife.com"],
            "feed_url": "https://investor.integralife.com/rss/news-releases.xml",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "Integra LifeSciences",
                "Second Quarter",
                "Financial Results"
            ],
            "title_none": ["to host"]
        },
        "press_wire": {
            "allowed_document_hosts": ["www.globenewswire.com"],
            "feed_url": "https://www.globenewswire.com/RssFeed/subjectcode/13-Earnings%20Releases%20And%20Operating%20Results/feedTitle/GlobeNewswire%20-%20Earnings%20Releases%20And%20Operating%20Results",
            "kind": "rss",
            "provider": "globenewswire",
            "title_all": [
                "Integra LifeSciences",
                "Second Quarter",
                "Financial Results"
            ],
            "title_none": ["to host"]
        }
    }'::jsonb,
    '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "rss",
            "provider": "company_ir",
            "status": "verified"
        },
        {
            "delivery": "rss",
            "provider": "globenewswire",
            "status": "verified"
        }
    ]'::jsonb
),
(
    'grmn-2026q2-nongaap-eps-2pt29',
    'earnings-grmn-2026q2',
    'earnings:GRMN:2026Q2',
    'GRMN',
    '1121788',
    2,
    DATE '2026-06-27',
    TIMESTAMPTZ '2026-07-29 11:00:00+00',
    'non_gaap_eps',
    2.29,
    'grmn-quarterly-earnings-nongaap-eps-07-29-2026-2pt29',
    '0xa8799cc9d0d491c736c76d6906e9cf9cf10913d285bcf50ca834ff4d50753116',
    'reported_pro_forma_diluted_eps',
    'https://www.garmin.com/en-US/newsroom/press-release/corporate/garmin-ltd-schedules-second-quarter-2026-earnings-call/',
    TIMESTAMPTZ '2026-07-29 14:30:00+00',
    '{
        "company_ir": {
            "allowed_document_hosts": ["www.garmin.com"],
            "feed_url": "https://www.garmin.com/en-US/newsroom/feed/",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "Garmin",
                "Second Quarter",
                "2026",
                "Results"
            ],
            "title_none": ["schedules"]
        },
        "press_wire": {
            "allowed_document_hosts": ["www.prnewswire.com"],
            "feed_url": "https://www.prnewswire.com/rss/news-releases-list.rss",
            "kind": "rss",
            "provider": "prnewswire",
            "title_all": [
                "Garmin",
                "Second Quarter",
                "2026",
                "Results"
            ],
            "title_none": ["schedules"]
        }
    }'::jsonb,
    '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "rss",
            "provider": "company_ir",
            "status": "verified"
        },
        {
            "delivery": "rss",
            "provider": "prnewswire",
            "status": "verified"
        }
    ]'::jsonb
),
(
    'cbre-2026q2-gaap-eps-1pt32',
    'earnings-cbre-2026q2',
    'earnings:CBRE:2026Q2',
    'CBRE',
    '1138118',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 10:55:00+00',
    'gaap_eps',
    1.32,
    'cbre-quarterly-earnings-gaap-eps-07-29-2026-1pt32',
    '0x27211249b8125a43a4b850ce763030142709ee1402ebac8b3a8543bee0cd9d22',
    'headline_gaap_diluted_eps',
    'https://ir.cbre.com/press-releases/detail/267/cbre-group-inc-announces-details-of-conference-call-and',
    TIMESTAMPTZ '2026-07-29 12:30:00+00',
    '{
        "company_ir": {
            "allowed_document_hosts": ["ir.cbre.com"],
            "feed_url": "https://ir.cbre.com/press-releases/rss",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "CBRE",
                "Reports",
                "Financial Results",
                "2026"
            ],
            "title_none": ["conference call"]
        }
    }'::jsonb,
    '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "rss",
            "provider": "company_ir",
            "status": "verified"
        }
    ]'::jsonb
),
(
    'pag-2026q2-gaap-eps-3pt39',
    'earnings-pag-2026q2',
    'earnings:PAG:2026Q2',
    'PAG',
    '1019849',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 12:00:00+00',
    'gaap_eps',
    3.39,
    'pag-quarterly-earnings-gaap-eps-07-29-2026-3pt39',
    '0xdb3c1e0e76010fb23f1c29d2adf701c1e56eadc2d0d45282863296367ba64e71',
    'reported_gaap_diluted_eps',
    'https://investors.penskeautomotive.com/news/news-details/2026/PENSKE-AUTOMOTIVE-GROUP-SCHEDULES-SECOND-QUARTER-AND-SIX-MONTHS-2026-FINANCIAL-RESULTS-CONFERENCE-CALL/default.aspx',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    '{
        "press_wire": {
            "allowed_document_hosts": ["www.prnewswire.com"],
            "feed_url": "https://www.prnewswire.com/rss/news-releases-list.rss",
            "kind": "rss",
            "provider": "prnewswire",
            "title_all": [
                "Penske Automotive Group",
                "Reports",
                "Quarter",
                "Results"
            ],
            "title_none": ["schedules"]
        }
    }'::jsonb,
    '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "rss",
            "provider": "prnewswire",
            "status": "verified"
        }
    ]'::jsonb
);

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
        'primary_authority', 'official_company',
        'initial_release_only', true,
        'metric_selection', metric_selection,
        'sec', jsonb_build_object(
            'form_type', '8-K',
            'required_item', '2.02',
            'document_type', 'EX-99.1'
        )
    ) || source_additions,
    jsonb_build_object(
        CASE
            WHEN metric_kind = 'gaap_eps'
                THEN 'gaap_secondary'
            ELSE 'non_gaap_secondary'
        END,
        'seeking_alpha',
        'gaap_after_hours', 96,
        'no_release_after_days', 45,
        'gaap_primary_basis', 'diluted',
        'gaap_fallback_basis', 'basic'
    ),
    'SHADOW'
FROM july29_premarket_additions
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
    updated_at = now()
WHERE earnings_market_rules.status <> 'WATCHING';

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
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-29 09:00:00+00',
    TIMESTAMPTZ '2026-07-29 17:00:00+00',
    jsonb_build_object(
        'profile_template_key', 'default',
        'rule_key', rule_key,
        'ticker', ticker
    ),
    'DISABLED'
FROM july29_premarket_additions
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

INSERT INTO earnings_release_catalog (
    event_key,
    ticker,
    release_date,
    market_session,
    scheduled_release_at,
    conference_call_at,
    schedule_status,
    schedule_source_url,
    integration_status,
    document_format,
    metric_options,
    source_options,
    notes,
    verified_at
)
SELECT
    ticker || ':2026-07-29',
    ticker,
    DATE '2026-07-29',
    'PRE_MARKET',
    estimated_release_at,
    conference_call_at,
    'CONFIRMED',
    schedule_source_url,
    'PARSER_ONLY',
    'FULL_HTML',
    jsonb_build_object(
        'comparison_op', '>',
        'fallback_basis', 'basic',
        'market_basis', metric_kind,
        'primary_basis', 'diluted',
        'reported', jsonb_build_array(metric_kind),
        'strike', strike::text
    ),
    source_options,
    'Reviewed fail-closed parser and disabled execution profile.',
    now()
FROM july29_premarket_additions
ON CONFLICT (event_key) DO UPDATE
SET
    ticker = EXCLUDED.ticker,
    release_date = EXCLUDED.release_date,
    market_session = EXCLUDED.market_session,
    scheduled_release_at = EXCLUDED.scheduled_release_at,
    conference_call_at = EXCLUDED.conference_call_at,
    schedule_status = EXCLUDED.schedule_status,
    schedule_source_url = EXCLUDED.schedule_source_url,
    integration_status = EXCLUDED.integration_status,
    document_format = EXCLUDED.document_format,
    metric_options = EXCLUDED.metric_options,
    source_options = EXCLUDED.source_options,
    notes = EXCLUDED.notes,
    verified_at = EXCLUDED.verified_at,
    updated_at = now();

INSERT INTO resolution_profile_schedules (
    schedule_key,
    profile_key,
    automation_mode,
    preflight_at,
    activate_at,
    deactivate_at,
    metadata,
    state
)
SELECT
    'schedule:' || profile_key,
    profile_key,
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-29 08:45:00+00',
    TIMESTAMPTZ '2026-07-29 09:00:00+00',
    TIMESTAMPTZ '2026-07-29 17:00:00+00',
    jsonb_build_object(
        'seed', '018_add_july_29_premarket_profiles',
        'preflight_lead_minutes', 15,
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-29-pre-market'
    ),
    'PENDING'
FROM july29_premarket_additions
ON CONFLICT (schedule_key) DO UPDATE
SET
    automation_mode = EXCLUDED.automation_mode,
    preflight_at = EXCLUDED.preflight_at,
    activate_at = EXCLUDED.activate_at,
    deactivate_at = EXCLUDED.deactivate_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
WHERE resolution_profile_schedules.state = 'PENDING';

-- Bring the three previously reviewed July 29 pre-market profiles in line
-- with the operator's current quantity-100 default. Profiles must still be
-- disabled and must have no claim or active order group.
UPDATE resolution_execution_profiles AS profile
SET
    quantity = 100,
    updated_at = now()
WHERE profile.profile_key IN (
        'earnings-sofi-2026q2',
        'earnings-pg-2026q4',
        'earnings-hum-2026q2'
    )
  AND profile.status = 'DISABLED'
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_execution_claims AS claim
      WHERE claim.scope_id = profile.scope_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_order_groups AS order_group
      WHERE order_group.account_name = profile.account_name
        AND order_group.condition_id = profile.condition_id
        AND order_group.status IN ('ACTIVE', 'REPRICING')
  );

UPDATE earnings_market_rules
SET
    source_policy = jsonb_set(
        source_policy,
        '{company_ir}',
        '{
            "allowed_document_hosts": ["humana.gcs-web.com"],
            "feed_url": "https://humana.gcs-web.com/rss/news-releases.xml",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "Humana",
                "Second Quarter",
                "Financial Results"
            ],
            "title_none": ["to release"]
        }'::jsonb,
        true
    ),
    updated_at = now()
WHERE rule_key = 'hum-2026q2-nongaap-eps-7pt00'
  AND scope_id = 'earnings:HUM:2026Q2'
  AND status = 'SHADOW';

UPDATE earnings_market_rules
SET
    source_policy = jsonb_set(
        source_policy,
        '{press_wire}',
        '{
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": [
                "SoFi",
                "Reports Second Quarter",
                "2026"
            ],
            "title_none": ["Schedules"]
        }'::jsonb,
        true
    ),
    updated_at = now()
WHERE rule_key = 'sofi-2026q2-gaap-eps-0pt11'
  AND scope_id = 'earnings:SOFI:2026Q2'
  AND status = 'SHADOW';

UPDATE earnings_market_rules
SET
    source_policy = jsonb_set(
        source_policy,
        '{press_wire}',
        '{
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": [
                "P&G",
                "Fourth Quarter",
                "Fiscal Year 2026",
                "Results"
            ],
            "title_none": ["Webcast"]
        }'::jsonb,
        true
    ),
    updated_at = now()
WHERE rule_key = 'pg-2026q4-nongaap-eps-1pt41'
  AND scope_id = 'earnings:PG:2026Q4'
  AND status = 'SHADOW';

UPDATE earnings_release_catalog
SET
    source_options = '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "rss",
            "provider": "company_ir",
            "status": "verified"
        }
    ]'::jsonb,
    notes = 'SEC WebSocket, official SEC polling, and Humana IR RSS prepared.',
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'HUM:2026-07-29';

UPDATE earnings_release_catalog
SET
    source_options = '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "available"
        },
        {
            "delivery": "rss",
            "provider": "businesswire",
            "status": "verified"
        }
    ]'::jsonb,
    notes = 'SEC WebSocket, official SEC polling, and Business Wire RSS prepared.',
    verified_at = now(),
    updated_at = now()
WHERE event_key IN (
    'SOFI:2026-07-29',
    'PG:2026-07-29'
);

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules AS rule
        JOIN july29_premarket_additions AS batch
          ON batch.rule_key = rule.rule_key
        WHERE rule.status = 'SHADOW'
          AND rule.scope_id = batch.scope_id
          AND rule.condition_id = batch.condition_id
          AND rule.metric_kind = batch.metric_kind
          AND rule.strike = batch.strike
          AND rule.source_policy -> 'sec' ->> 'form_type' = '8-K'
          AND rule.source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND rule.source_policy -> 'sec' ->> 'document_type' = 'EX-99.1'
    ) <> 6 THEN
        RAISE EXCEPTION 'July 29 pre-market rule batch mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'earnings-sofi-2026q2',
            'earnings-pg-2026q4',
            'earnings-hum-2026q2',
            'earnings-wing-2026q2',
            'earnings-arcc-2026q2',
            'earnings-iart-2026q2',
            'earnings-grmn-2026q2',
            'earnings-cbre-2026q2',
            'earnings-pag-2026q2'
        )
          AND status = 'DISABLED'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
    ) <> 9 THEN
        RAISE EXCEPTION 'July 29 pre-market profile set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE profile_key IN (
            'earnings-sofi-2026q2',
            'earnings-pg-2026q4',
            'earnings-hum-2026q2',
            'earnings-wing-2026q2',
            'earnings-arcc-2026q2',
            'earnings-iart-2026q2',
            'earnings-grmn-2026q2',
            'earnings-cbre-2026q2',
            'earnings-pag-2026q2'
        )
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND activate_at = TIMESTAMPTZ '2026-07-29 09:00:00+00'
          AND deactivate_at = TIMESTAMPTZ '2026-07-29 17:00:00+00'
          AND metadata ->> 'live_block' = 'PRE_MARKET'
          AND metadata ->> 'block_id' = '2026-07-29-pre-market'
    ) <> 9 THEN
        RAISE EXCEPTION 'July 29 pre-market schedule set mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE ticker IN (
            'SOFI',
            'PG',
            'HUM',
            'WING',
            'ARCC',
            'IART',
            'GRMN',
            'CBRE',
            'PAG'
        )
          AND release_date = DATE '2026-07-29'
          AND market_session = 'PRE_MARKET'
          AND integration_status = 'PARSER_ONLY'
    ) <> 9 THEN
        RAISE EXCEPTION 'July 29 pre-market catalog mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_market_rules
        WHERE (
            rule_key = 'hum-2026q2-nongaap-eps-7pt00'
            AND source_policy -> 'company_ir' ->> 'provider' =
                'company_ir'
            AND source_policy -> 'company_ir' ->> 'kind' = 'rss'
        )
        OR (
            rule_key IN (
                'sofi-2026q2-gaap-eps-0pt11',
                'pg-2026q4-nongaap-eps-1pt41',
                'arcc-2026q2-nongaap-eps-0pt47'
            )
            AND source_policy -> 'press_wire' ->> 'provider' =
                'businesswire'
            AND source_policy -> 'press_wire' ->> 'kind' = 'rss'
        )
    ) <> 4 THEN
        RAISE EXCEPTION 'July 29 added public source mismatch';
    END IF;

    SELECT SUM(
        quantity * GREATEST(yes_desired_price, no_desired_price)
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-sofi-2026q2',
        'earnings-pg-2026q4',
        'earnings-hum-2026q2',
        'earnings-wing-2026q2',
        'earnings-arcc-2026q2',
        'earnings-iart-2026q2',
        'earnings-grmn-2026q2',
        'earnings-cbre-2026q2',
        'earnings-pag-2026q2'
    );

    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'July 29 pre-market notional exceeds 1000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:SOFI:2026Q2',
            'earnings:PG:2026Q4',
            'earnings:HUM:2026Q2',
            'earnings:WING:2026Q2',
            'earnings:ARCC:2026Q2',
            'earnings:IART:2026Q2',
            'earnings:GRMN:2026Q2',
            'earnings:CBRE:2026Q2',
            'earnings:PAG:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'July 29 pre-market execution claim must not exist';
    END IF;
END
$verification$;

COMMIT;
