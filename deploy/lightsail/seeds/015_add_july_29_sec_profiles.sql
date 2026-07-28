-- Add the first reviewed July 29 SEC earnings batch.
-- Profiles remain DISABLED and schedules remain AUTO_PREFLIGHT. This seed
-- cannot authorize live trading.

BEGIN;

CREATE TEMP TABLE july29_sec_batch (
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
    prepare_from timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    market_session text NOT NULL,
    conference_call_at timestamptz,
    schedule_status text NOT NULL,
    schedule_source_url text NOT NULL
) ON COMMIT DROP;

INSERT INTO july29_sec_batch VALUES
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
    TIMESTAMPTZ '2026-07-29 09:00:00+00',
    TIMESTAMPTZ '2026-07-29 17:00:00+00',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-29 12:00:00+00',
    'CONFIRMED',
    'https://investors.sofi.com/news/news-details/2026/SoFi-Schedules-Conference-Call-to-Discuss-Q2-2026-Results/default.aspx'
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
    TIMESTAMPTZ '2026-07-29 09:00:00+00',
    TIMESTAMPTZ '2026-07-29 17:00:00+00',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-29 12:30:00+00',
    'CONFIRMED',
    'https://us.pg.com/newsroom/news-releases/PG-to-Webcast-Discussion-of-Fourth-Quarter-2526-Earnings-Results-on-July-29/'
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
    TIMESTAMPTZ '2026-07-29 09:00:00+00',
    TIMESTAMPTZ '2026-07-29 17:00:00+00',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-29 12:00:00+00',
    'CONFIRMED',
    'https://humana.gcs-web.com/news-releases/news-release-details/humana-inc-release-second-quarter-2026-results-july-29-2026'
),
(
    'qcom-2026q3-nongaap-eps-2pt23',
    'earnings-qcom-2026q3',
    'earnings:QCOM:2026Q3',
    'QCOM',
    '804328',
    3,
    DATE '2026-06-28',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    'non_gaap_eps',
    2.23,
    'qcom-quarterly-earnings-nongaap-eps-07-29-2026-2pt23',
    '0xe13b3b5087385775af2dbacd02af3386acb815b6c8a9d09bc013f158a172ba0a',
    'primary_headline_non_gaap_eps',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-29 20:45:00+00',
    'CONFIRMED',
    'https://investor.qualcomm.com/news-events/press-releases/news-details/2026/Qualcomm-Schedules-Third-Quarter-Fiscal-2026-Earnings-Release-and-Conference-Call/default.aspx'
),
(
    'msft-2026q4-gaap-eps-4pt21',
    'earnings-msft-2026q4',
    'earnings:MSFT:2026Q4',
    'MSFT',
    '789019',
    4,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    'gaap_eps',
    4.21,
    'msft-quarterly-earnings-gaap-eps-07-29-2026-4pt21',
    '0xa7a5a986a14d3c5b47b9892c6aefc48a85ff3e8e02d999ff7dd015f735ad38d8',
    'primary_headline_gaap_diluted_eps',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-29 21:30:00+00',
    'CONFIRMED',
    'https://news.microsoft.com/source/2026/07/08/microsoft-announces-quarterly-earnings-release-date-68/'
),
(
    'meta-2026q2-gaap-eps-7pt20',
    'earnings-meta-2026q2',
    'earnings:META:2026Q2',
    'META',
    '1326801',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    'gaap_eps',
    7.20,
    'meta-quarterly-earnings-gaap-eps-07-29-2026-7pt2',
    '0x5b725d76638a67ec53ced1221dd6140ff0b419edb72a1653ba4aa82551601704',
    'financial_highlights_gaap_diluted_eps',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-29 20:30:00+00',
    'CONFIRMED',
    'https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-to-Announce-Second-Quarter-2026-Results/default.aspx'
),
(
    'ebay-2026q2-nongaap-eps-1pt51',
    'earnings-ebay-2026q2',
    'earnings:EBAY:2026Q2',
    'EBAY',
    '1065088',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    'non_gaap_eps',
    1.51,
    'ebay-quarterly-earnings-nongaap-eps-07-29-2026-1pt51',
    '0x550698cb57f581259106ad2934b1eb7fd7bd7f6044f092341773883ebf52f319',
    'primary_headline_non_gaap_diluted_eps',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    'POST_MARKET',
    NULL,
    'ESTIMATED',
    'https://investors.ebayinc.com/overview/default.aspx'
),
(
    'hood-2026q2-gaap-eps-0pt43',
    'earnings-hood-2026q2',
    'earnings:HOOD:2026Q2',
    'HOOD',
    '1783879',
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    'gaap_eps',
    0.43,
    'hood-quarterly-earnings-gaap-eps-07-29-2026-0pt43',
    '0x00d480ad192a0cf494a9663a8d0fe22578b06ea4702f83acfb79bde049a5cf85',
    'primary_headline_gaap_diluted_eps',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-29 21:00:00+00',
    'CONFIRMED',
    'https://investors.robinhood.com/node/16131/pdf'
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
FROM july29_sec_batch
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
FROM july29_sec_batch
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
    market_session,
    estimated_release_at,
    conference_call_at,
    schedule_status,
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
            'provider', 'sec',
            'status', 'available'
        )
    ),
    'Reviewed SEC-only parser and disabled execution profile.',
    now()
FROM july29_sec_batch
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
    prepare_from - interval '15 minutes',
    prepare_from,
    expires_at,
    jsonb_build_object(
        'seed', '015_add_july_29_sec_profiles',
        'preflight_lead_minutes', 15,
        'live_block', market_session,
        'block_id',
            '2026-07-29-'
            || replace(lower(market_session), '_', '-')
    ),
    'PENDING'
FROM july29_sec_batch
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
        JOIN july29_sec_batch AS batch
          ON batch.rule_key = rule.rule_key
        WHERE rule.status = 'SHADOW'
          AND rule.scope_id = batch.scope_id
          AND rule.condition_id = batch.condition_id
          AND rule.metric_kind = batch.metric_kind
          AND rule.strike = batch.strike
          AND rule.source_policy -> 'sec' ->> 'form_type' = '8-K'
          AND rule.source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND rule.source_policy -> 'sec' ->> 'document_type' = 'EX-99.1'
    ) <> 8 THEN
        RAISE EXCEPTION 'July 29 SEC rule batch mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles AS profile
        JOIN july29_sec_batch AS batch
          ON batch.profile_key = profile.profile_key
        WHERE profile.status = 'DISABLED'
          AND profile.account_name = 'abccbaq'
          AND profile.yes_desired_price = 0.999
          AND profile.no_desired_price = 0.999
          AND profile.quantity = 50
          AND profile.lifecycle_kind = 'reprice_on_tick_change'
          AND profile.old_tick = 0.01
          AND profile.new_tick = 0.001
          AND profile.max_reprices = 1
    ) <> 8 THEN
        RAISE EXCEPTION 'July 29 execution profile batch mismatch';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules AS schedule
        JOIN july29_sec_batch AS batch
          ON batch.profile_key = schedule.profile_key
        WHERE schedule.automation_mode = 'AUTO_PREFLIGHT'
          AND schedule.state = 'PENDING'
          AND schedule.preflight_at =
              batch.prepare_from - interval '15 minutes'
          AND schedule.activate_at = batch.prepare_from
          AND schedule.deactivate_at = batch.expires_at
          AND schedule.metadata ->> 'live_block' =
              batch.market_session
          AND schedule.metadata ->> 'block_id' =
              '2026-07-29-'
              || replace(lower(batch.market_session), '_', '-')
    ) <> 8 THEN
        RAISE EXCEPTION 'July 29 AUTO_PREFLIGHT schedule batch mismatch';
    END IF;

    SELECT SUM(
        profile.quantity * GREATEST(
            profile.yes_desired_price,
            profile.no_desired_price
        )
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles AS profile
    JOIN july29_sec_batch AS batch
      ON batch.profile_key = profile.profile_key;

    IF reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'July 29 reviewed notional exceeds 1000';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims AS claim
        JOIN july29_sec_batch AS batch
          ON batch.scope_id = claim.scope_id
    ) THEN
        RAISE EXCEPTION 'July 29 execution claim must not exist';
    END IF;
END
$verification$;

COMMIT;
