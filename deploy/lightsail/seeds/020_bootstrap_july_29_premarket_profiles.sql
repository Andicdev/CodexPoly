-- Bootstrap the three July 29 pre-market profiles that were originally
-- bundled with a broader SEC batch. This production-safe subset deliberately
-- excludes every POST_MARKET profile. Profiles remain DISABLED and schedules
-- remain AUTO_PREFLIGHT; this seed cannot authorize live trading.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE TEMP TABLE july29_premarket_bootstrap (
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
    conference_call_at timestamptz
) ON COMMIT DROP;

INSERT INTO july29_premarket_bootstrap VALUES
(
    'sofi-2026q2-gaap-eps-0pt11',
    'earnings-sofi-2026q2',
    'earnings:SOFI:2026Q2',
    'SOFI',
    '1818874',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 11:00:00+00',
    'gaap_eps',
    0.11,
    'sofi-quarterly-earnings-gaap-eps-07-29-2026-0pt11',
    '0xf5e41999c536ba01d79d9b36fadc8b4beeb5735ac2bd57dfb041145e0d709033',
    'reported_gaap_diluted_eps',
    'https://investors.sofi.com/news/news-details/2026/SoFi-Schedules-Conference-Call-to-Discuss-Q2-2026-Results/default.aspx',
    TIMESTAMPTZ '2026-07-29 12:00:00+00'
),
(
    'pg-2026q4-nongaap-eps-1pt41',
    'earnings-pg-2026q4',
    'earnings:PG:2026Q4',
    'PG',
    '80424',
    4,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 11:00:00+00',
    'non_gaap_eps',
    1.41,
    'pg-quarterly-earnings-nongaap-eps-07-29-2026-1pt41',
    '0x161d914e2eda4a1757ad969175add854146ec6a7cff5627e31040459f5c20725',
    'quarterly_primary_headline_non_gaap_core_eps',
    'https://us.pg.com/newsroom/news-releases/PG-to-Webcast-Discussion-of-Fourth-Quarter-2526-Earnings-Results-on-July-29/',
    TIMESTAMPTZ '2026-07-29 12:30:00+00'
),
(
    'hum-2026q2-nongaap-eps-7pt00',
    'earnings-hum-2026q2',
    'earnings:HUM:2026Q2',
    'HUM',
    '49071',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 10:00:00+00',
    'non_gaap_eps',
    7.00,
    'hum-quarterly-earnings-nongaap-eps-07-29-2026-7',
    '0xdc4eaee1d80f2b50f30d35f6e8209e2e47dc283de1e77980f399cc206dcb019e',
    'headline_adjusted_non_gaap_eps',
    'https://humana.gcs-web.com/news-releases/news-release-details/humana-inc-release-second-quarter-2026-results-july-29-2026',
    TIMESTAMPTZ '2026-07-29 12:00:00+00'
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
    ),
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
FROM july29_premarket_bootstrap
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
FROM july29_premarket_bootstrap
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
    jsonb_build_array(
        jsonb_build_object(
            'delivery', 'websocket',
            'provider', 'sec_api',
            'status', 'available'
        ),
        jsonb_build_object(
            'delivery', 'polling',
            'provider', 'sec',
            'status', 'available'
        )
    ),
    'Reviewed SEC parser and disabled execution profile.',
    now()
FROM july29_premarket_bootstrap
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
        'seed', '020_bootstrap_july_29_premarket_profiles',
        'preflight_lead_minutes', 15,
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-29-pre-market'
    ),
    'PENDING'
FROM july29_premarket_bootstrap
ON CONFLICT (schedule_key) DO UPDATE
SET
    automation_mode = EXCLUDED.automation_mode,
    preflight_at = EXCLUDED.preflight_at,
    activate_at = EXCLUDED.activate_at,
    deactivate_at = EXCLUDED.deactivate_at,
    metadata = EXCLUDED.metadata,
    updated_at = now()
WHERE resolution_profile_schedules.state = 'PENDING';

DO $verification$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_market_rules AS rule
        JOIN july29_premarket_bootstrap AS batch
          ON batch.rule_key = rule.rule_key
        WHERE rule.status = 'SHADOW'
          AND rule.scope_id = batch.scope_id
          AND rule.condition_id = batch.condition_id
          AND rule.metric_kind = batch.metric_kind
          AND rule.strike = batch.strike
          AND rule.source_policy -> 'sec' ->> 'form_type' = '8-K'
          AND rule.source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND rule.source_policy -> 'sec' ->> 'document_type' = 'EX-99.1'
    ) <> 3 THEN
        RAISE EXCEPTION 'July 29 pre-market bootstrap rule mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN july29_premarket_bootstrap AS batch
          ON batch.profile_key = profile.profile_key
        WHERE profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 100
          AND profile.prepare_from =
              TIMESTAMPTZ '2026-07-29 09:00:00+00'
          AND profile.expires_at =
              TIMESTAMPTZ '2026-07-29 17:00:00+00'
    ) <> 3 THEN
        RAISE EXCEPTION 'July 29 pre-market bootstrap profile mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN july29_premarket_bootstrap AS batch
          ON batch.profile_key = schedule.profile_key
        WHERE schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'PENDING'
          AND schedule.preflight_at =
              TIMESTAMPTZ '2026-07-29 08:45:00+00'
          AND schedule.activate_at =
              TIMESTAMPTZ '2026-07-29 09:00:00+00'
          AND schedule.deactivate_at =
              TIMESTAMPTZ '2026-07-29 17:00:00+00'
          AND schedule.metadata ->> 'live_block' = 'PRE_MARKET'
    ) <> 3 THEN
        RAISE EXCEPTION 'July 29 pre-market bootstrap schedule mismatch';
    END IF;

    SELECT SUM(
        quantity * GREATEST(yes_desired_price, no_desired_price)
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-sofi-2026q2',
        'earnings-pg-2026q4',
        'earnings-hum-2026q2'
    );

    IF reviewed_notional > 300 THEN
        RAISE EXCEPTION 'July 29 pre-market bootstrap notional exceeds 300';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:SOFI:2026Q2',
            'earnings:PG:2026Q4',
            'earnings:HUM:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION
            'July 29 pre-market bootstrap execution claim must not exist';
    END IF;
END
$verification$;

COMMIT;
