-- Add BEN, CBOE, CVX, CL, MRNA, and ARES for July 31 PRE_MARKET.
-- Profiles remain DISABLED; AUTO_PREFLIGHT cannot enable trading.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-31 09:45:00+00' THEN
        RAISE EXCEPTION 'July 31 batch preparation deadline has passed';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id IN (
            'earnings:BEN:2026Q3',
            'earnings:CBOE:2026Q2',
            'earnings:CVX:2026Q2',
            'earnings:CL:2026Q2',
            'earnings:MRNA:2026Q2',
            'earnings:ARES:2026Q2'
        )
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:BEN:2026Q3',
            'earnings:CBOE:2026Q2',
            'earnings:CVX:2026Q2',
            'earnings:CL:2026Q2',
            'earnings:MRNA:2026Q2',
            'earnings:ARES:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'July 31 batch scopes already contain facts or claims';
    END IF;
END
$guard$;

INSERT INTO earnings_market_rules (
    rule_key, scope_id, ticker, cik, fiscal_year, fiscal_quarter,
    period_end, estimated_release_at, metric_kind, primary_basis,
    fallback_basis, comparison_op, strike, rounding_places, currency,
    market_slug, condition_id, source_policy, fallback_policy, status
)
VALUES
(
    'ben-2026q3-non-gaap-eps-0pt66',
    'earnings:BEN:2026Q3', 'BEN', '38777', 2026, 3,
    DATE '2026-06-30', TIMESTAMPTZ '2026-07-31 12:30:00+00',
    'non_gaap_eps', 'diluted', 'basic', '>', 0.66, 2, 'USD',
    'ben-quarterly-earnings-nongaap-eps-07-31-2026-0pt66',
    '0xe96fd9c6959d0483dc0cd457db695ba432fc34c3b210fa5762d550eeebb38e1c',
    '{
      "primary_authority":"official_company",
      "initial_release_only":true,
      "metric_selection":"primary_adjusted_diluted_eps",
      "sec":{"form_type":"8-K","required_item":"2.02","document_type":"EX-99.1"},
      "company_ir":{
        "allowed_document_hosts":["investors.franklinresources.com","news.franklinresources.com"],
        "feed_url":"https://investors.franklinresources.com/rss/news-releases.xml",
        "kind":"rss","provider":"company_ir",
        "title_all":["Franklin Resources","Third Quarter","Results"],
        "title_none":["to announce","conference call"]
      },
      "press_wire":{
        "allowed_document_hosts":["www.businesswire.com"],
        "feed_url":"https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
        "kind":"rss","provider":"businesswire",
        "title_all":["Franklin Resources","Third Quarter","Results"],
        "title_none":["to announce","conference call"]
      }
    }'::jsonb,
    '{"non_gaap_secondary":"seeking_alpha","gaap_after_hours":96,"no_release_after_days":45,"gaap_primary_basis":"diluted","gaap_fallback_basis":"basic"}'::jsonb,
    'SHADOW'
),
(
    'cboe-2026q2-non-gaap-eps-3pt49',
    'earnings:CBOE:2026Q2', 'CBOE', '1374310', 2026, 2,
    DATE '2026-06-30', TIMESTAMPTZ '2026-07-31 11:30:00+00',
    'non_gaap_eps', 'diluted', 'basic', '>', 3.49, 2, 'USD',
    'cboe-quarterly-earnings-nongaap-eps-07-31-2026-3pt49',
    '0xf9c9b9019399a2ad6422bab7ac14280852187f84d21d77f0f7f9dc34e76ebee3',
    '{
      "primary_authority":"official_company",
      "initial_release_only":true,
      "metric_selection":"primary_adjusted_diluted_eps",
      "sec":{"form_type":"8-K","required_item":"2.02","document_type":"EX-99.1"},
      "company_ir":{
        "allowed_document_hosts":["ir.cboe.com"],
        "feed_url":"https://ir.cboe.com/rss/news-releases.xml",
        "kind":"rss","provider":"company_ir",
        "title_all":["Cboe","Second Quarter","2026","Results"],
        "title_none":["announces date","trading volume"]
      },
      "press_wire":{
        "allowed_document_hosts":["www.prnewswire.com"],
        "feed_url":"https://www.prnewswire.com/rss/news-releases-list.rss",
        "kind":"rss","provider":"prnewswire",
        "title_all":["Cboe","Second Quarter","2026","Results"],
        "title_none":["announces date","trading volume"]
      }
    }'::jsonb,
    '{"non_gaap_secondary":"seeking_alpha","gaap_after_hours":96,"no_release_after_days":45,"gaap_primary_basis":"diluted","gaap_fallback_basis":"basic"}'::jsonb,
    'SHADOW'
),
(
    'cvx-2026q2-non-gaap-eps-5pt32',
    'earnings:CVX:2026Q2', 'CVX', '93410', 2026, 2,
    DATE '2026-06-30', TIMESTAMPTZ '2026-07-31 10:15:00+00',
    'non_gaap_eps', 'diluted', 'basic', '>', 5.32, 2, 'USD',
    'cvx-quarterly-earnings-nongaap-eps-07-31-2026-5pt32',
    '0x612ac685fca390b9190dff33d0a273d0346c9365af9419e39187658e0fe08381',
    '{
      "primary_authority":"official_company",
      "initial_release_only":true,
      "metric_selection":"earnings_cash_flow_summary_adjusted_eps_diluted",
      "sec":{"form_type":"8-K","required_item":"2.02","document_type":"EX-99.1"},
      "company_ir":{
        "allowed_document_hosts":["www.chevron.com","chevron.com"],
        "feed_url":"https://www.chevron.com/newsroom/archive?contenttype=press+release",
        "kind":"html_listing","listing_utc_offset_minutes":-240,
        "provider":"company_ir",
        "title_all":["Chevron","second quarter","2026","results"],
        "title_none":["conference call"]
      }
    }'::jsonb,
    '{"non_gaap_secondary":"seeking_alpha","gaap_after_hours":96,"no_release_after_days":45,"gaap_primary_basis":"diluted","gaap_fallback_basis":"basic"}'::jsonb,
    'SHADOW'
),
(
    'cl-2026q2-non-gaap-eps-0pt95',
    'earnings:CL:2026Q2', 'CL', '21665', 2026, 2,
    DATE '2026-06-30', TIMESTAMPTZ '2026-07-31 11:00:00+00',
    'non_gaap_eps', 'diluted', 'basic', '>', 0.95, 2, 'USD',
    'cl-quarterly-earnings-nongaap-eps-07-31-2026-0pt95',
    '0x68386ae98143460fcedbe8db947999d9167bb610e6c12118e8f79a66250e14ea',
    '{
      "primary_authority":"official_company",
      "initial_release_only":true,
      "metric_selection":"primary_base_business_eps_diluted",
      "sec":{"form_type":"8-K","required_item":"2.02","document_type":"EX-99.1"},
      "company_ir":{
        "allowed_document_hosts":["investor.colgatepalmolive.com"],
        "feed_url":"https://investor.colgatepalmolive.com/rss/news-releases.xml",
        "kind":"rss","provider":"company_ir",
        "title_all":["Colgate","2nd Quarter","2026","Results"],
        "title_none":["webcasts","conference call"]
      },
      "press_wire":{
        "allowed_document_hosts":["www.businesswire.com"],
        "feed_url":"https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
        "kind":"rss","provider":"businesswire",
        "title_all":["Colgate","2nd Quarter","2026","Results"],
        "title_none":["webcasts","conference call"]
      }
    }'::jsonb,
    '{"non_gaap_secondary":"seeking_alpha","gaap_after_hours":96,"no_release_after_days":45,"gaap_primary_basis":"diluted","gaap_fallback_basis":"basic"}'::jsonb,
    'SHADOW'
),
(
    'mrna-2026q2-gaap-eps-neg2pt06',
    'earnings:MRNA:2026Q2', 'MRNA', '1682852', 2026, 2,
    DATE '2026-06-30', TIMESTAMPTZ '2026-07-31 10:30:00+00',
    'gaap_eps', 'diluted', 'basic', '>', -2.06, 2, 'USD',
    'mrna-quarterly-earnings-gaap-eps-07-31-2026-neg2pt06',
    '0x12dd0955557fbc7aa18fbbb53579783661bbd7443065f421f53429ff60e752cc',
    '{
      "primary_authority":"official_company",
      "initial_release_only":true,
      "metric_selection":"current_period_gaap_basic_and_diluted_eps_row",
      "sec":{"form_type":"8-K","required_item":"2.02","document_type":"EX-99.1"},
      "company_ir":{
        "allowed_document_hosts":["news.modernatx.com","investors.modernatx.com"],
        "feed_url":"https://feeds.issuerdirect.com/news.html?latest=25&symbol=MRNA",
        "kind":"html_listing","listing_utc_offset_minutes":-240,
        "provider":"company_ir",
        "title_all":["Moderna","Second Quarter","2026","Financial Results"],
        "title_none":["earnings call"]
      }
    }'::jsonb,
    '{"gaap_secondary":"seeking_alpha","gaap_after_hours":96,"no_release_after_days":45,"gaap_primary_basis":"diluted","gaap_fallback_basis":"basic"}'::jsonb,
    'SHADOW'
),
(
    'ares-2026q2-non-gaap-eps-1pt27',
    'earnings:ARES:2026Q2', 'ARES', '1176948', 2026, 2,
    DATE '2026-06-30', TIMESTAMPTZ '2026-07-31 11:00:00+00',
    'non_gaap_eps', 'diluted', 'basic', '>', 1.27, 2, 'USD',
    'ares-quarterly-earnings-nongaap-eps-07-31-2026-1pt27',
    '0x6fc29d9fc5a9d0955eb8b610b028ccf38a5c82d33013fc06b261f441fa8ec6c8',
    '{
      "primary_authority":"official_company",
      "initial_release_only":true,
      "metric_selection":"primary_after_tax_realized_income_per_share",
      "sec":{"form_type":"8-K","required_item":"2.02","document_type":"EX-99.1"},
      "press_wire":{
        "allowed_document_hosts":["www.businesswire.com"],
        "feed_url":"https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
        "kind":"rss","provider":"businesswire",
        "title_all":["Ares Management","Second Quarter","2026","Results"],
        "title_none":["schedules","updates the time"]
      }
    }'::jsonb,
    '{"non_gaap_secondary":"seeking_alpha","gaap_after_hours":96,"no_release_after_days":45,"gaap_primary_basis":"diluted","gaap_fallback_basis":"basic"}'::jsonb,
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
    updated_at = now()
WHERE earnings_market_rules.status = 'SHADOW';

WITH profile_config(
    ticker, quarter, rule_key, condition_id, market_slug
) AS (
    VALUES
    ('BEN', 3, 'ben-2026q3-non-gaap-eps-0pt66',
     '0xe96fd9c6959d0483dc0cd457db695ba432fc34c3b210fa5762d550eeebb38e1c',
     'ben-quarterly-earnings-nongaap-eps-07-31-2026-0pt66'),
    ('CBOE', 2, 'cboe-2026q2-non-gaap-eps-3pt49',
     '0xf9c9b9019399a2ad6422bab7ac14280852187f84d21d77f0f7f9dc34e76ebee3',
     'cboe-quarterly-earnings-nongaap-eps-07-31-2026-3pt49'),
    ('CVX', 2, 'cvx-2026q2-non-gaap-eps-5pt32',
     '0x612ac685fca390b9190dff33d0a273d0346c9365af9419e39187658e0fe08381',
     'cvx-quarterly-earnings-nongaap-eps-07-31-2026-5pt32'),
    ('CL', 2, 'cl-2026q2-non-gaap-eps-0pt95',
     '0x68386ae98143460fcedbe8db947999d9167bb610e6c12118e8f79a66250e14ea',
     'cl-quarterly-earnings-nongaap-eps-07-31-2026-0pt95'),
    ('MRNA', 2, 'mrna-2026q2-gaap-eps-neg2pt06',
     '0x12dd0955557fbc7aa18fbbb53579783661bbd7443065f421f53429ff60e752cc',
     'mrna-quarterly-earnings-gaap-eps-07-31-2026-neg2pt06'),
    ('ARES', 2, 'ares-2026q2-non-gaap-eps-1pt27',
     '0x6fc29d9fc5a9d0955eb8b610b028ccf38a5c82d33013fc06b261f441fa8ec6c8',
     'ares-quarterly-earnings-nongaap-eps-07-31-2026-1pt27')
)
INSERT INTO resolution_execution_profiles (
    profile_key, scope_id, source_name, source_reference, account_name,
    condition_id, yes_desired_price, no_desired_price, quantity,
    lifecycle_kind, old_tick, new_tick, max_reprices, prepare_from,
    expires_at, metadata, status
)
SELECT
    'earnings-' || lower(ticker) || '-2026q' || quarter,
    'earnings:' || ticker || ':2026Q' || quarter,
    'earnings_resolution',
    'https://polymarket.com/event/' || market_slug,
    'abccbaq',
    condition_id,
    0.999, 0.999, 100,
    'reprice_on_tick_change', 0.01, 0.001, 1,
    TIMESTAMPTZ '2026-07-31 08:45:00+00',
    TIMESTAMPTZ '2026-07-31 14:30:00+00',
    jsonb_build_object(
        'profile_template_key', 'default',
        'quantity_policy', '100_shares',
        'rule_key', rule_key,
        'ticker', ticker,
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-31-pre-market'
    ),
    'DISABLED'
FROM profile_config
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

WITH catalog_config(
    ticker, scheduled_release_at, conference_call_at,
    earliest_expected_release_at, timing_basis, timing_confidence,
    timing_source_url, metric_label, strike
) AS (
    VALUES
    ('BEN', TIMESTAMPTZ '2026-07-31 12:30:00+00',
     TIMESTAMPTZ '2026-07-31 14:00:00+00',
     TIMESTAMPTZ '2026-07-31 12:30:00+00',
     'OFFICIAL_EXACT', 'HIGH',
     'https://investors.franklinresources.com/news-center/press-releases/press-release-details/2026/Franklin-Resources-Inc--to-Announce-Third-Quarter-Results-on-July-31-2026/default.aspx',
     'Adjusted diluted earnings per share', '0.66'),
    ('CBOE', TIMESTAMPTZ '2026-07-31 11:30:00+00',
     TIMESTAMPTZ '2026-07-31 12:30:00+00',
     TIMESTAMPTZ '2026-07-31 11:30:00+00',
     'HISTORICAL_PATTERN', 'MEDIUM',
     'https://ir.cboe.com/news/news-details/2026/Cboe-Global-Markets-Announces-Date-of-Second-Quarter-2026-Earnings-Release-and-Conference-Call/default.aspx',
     'Adjusted diluted EPS', '3.49'),
    ('CVX', TIMESTAMPTZ '2026-07-31 10:15:00+00',
     NULL::timestamptz,
     TIMESTAMPTZ '2026-07-31 10:15:00+00',
     'HISTORICAL_PATTERN', 'MEDIUM',
     'https://www.chevron.com/investors/events-presentations/2q-2026-earnings',
     'Adjusted Earnings Per Share - Diluted', '5.32'),
    ('CL', TIMESTAMPTZ '2026-07-31 11:00:00+00',
     TIMESTAMPTZ '2026-07-31 12:30:00+00',
     TIMESTAMPTZ '2026-07-31 11:00:00+00',
     'HISTORICAL_PATTERN', 'MEDIUM',
     'https://investor.colgatepalmolive.com/investor-news?ReleasesType=Earnings&page=1',
     'Base Business EPS (diluted)', '0.95'),
    ('MRNA', TIMESTAMPTZ '2026-07-31 10:30:00+00',
     TIMESTAMPTZ '2026-07-31 12:00:00+00',
     TIMESTAMPTZ '2026-07-31 10:30:00+00',
     'HISTORICAL_PATTERN', 'MEDIUM',
     'https://investors.modernatx.com/events-presentations',
     'GAAP Basic and Diluted net income/loss per share', '-2.06'),
    ('ARES', TIMESTAMPTZ '2026-07-31 11:00:00+00',
     TIMESTAMPTZ '2026-07-31 13:00:00+00',
     TIMESTAMPTZ '2026-07-31 10:30:00+00',
     'HISTORICAL_PATTERN', 'MEDIUM',
     'https://www.prnewswire.com/news-releases/ares-management-corporation-updates-the-time-of-its-earnings-conference-call-for-the-second-quarter-ending-june-30-2026-302822342.html',
     'After-tax realized income per share', '1.27')
)
INSERT INTO earnings_release_catalog (
    event_key, ticker, release_date, market_session, scheduled_release_at,
    conference_call_at, earliest_expected_release_at, timing_basis,
    timing_confidence, activation_safety_lead_seconds, timing_source_url,
    schedule_status, schedule_source_url, integration_status,
    document_format, metric_options, source_options, notes, verified_at
)
SELECT
    ticker || ':2026-07-31',
    ticker,
    DATE '2026-07-31',
    'PRE_MARKET',
    scheduled_release_at,
    conference_call_at,
    earliest_expected_release_at,
    timing_basis,
    timing_confidence,
    CASE WHEN ticker = 'BEN' THEN 7200 ELSE 5400 END,
    timing_source_url,
    'CONFIRMED',
    timing_source_url,
    'PARSER_ONLY',
    'FULL_HTML',
    jsonb_build_object(
        'comparison_op', '>',
        'primary_basis', 'diluted',
        'reported_label', metric_label,
        'strike', strike
    ),
    jsonb_build_array(
        jsonb_build_object(
            'delivery', 'websocket',
            'provider', 'sec_api',
            'status', 'available'
        ),
        jsonb_build_object(
            'delivery', 'polling',
            'provider', 'sec_current',
            'status', 'profile_gated'
        ),
        jsonb_build_object(
            'delivery', 'public',
            'provider', 'company_or_wire',
            'status', 'profile_gated_configured'
        )
    ),
    (
        'Parser replayed against the latest prior official SEC earnings '
        'exhibit. Release timing is kept separate from conference-call time.'
    ),
    now()
FROM catalog_config
ON CONFLICT (event_key) DO UPDATE
SET
    scheduled_release_at = EXCLUDED.scheduled_release_at,
    conference_call_at = EXCLUDED.conference_call_at,
    earliest_expected_release_at = EXCLUDED.earliest_expected_release_at,
    timing_basis = EXCLUDED.timing_basis,
    timing_confidence = EXCLUDED.timing_confidence,
    activation_safety_lead_seconds =
        EXCLUDED.activation_safety_lead_seconds,
    timing_source_url = EXCLUDED.timing_source_url,
    schedule_status = EXCLUDED.schedule_status,
    schedule_source_url = EXCLUDED.schedule_source_url,
    integration_status = EXCLUDED.integration_status,
    document_format = EXCLUDED.document_format,
    metric_options = EXCLUDED.metric_options,
    source_options = EXCLUDED.source_options,
    notes = EXCLUDED.notes,
    verified_at = EXCLUDED.verified_at,
    updated_at = now()
WHERE earnings_release_catalog.integration_status IN (
    'RESEARCH_PENDING', 'PARSER_ONLY'
);

WITH schedule_config(
    ticker, quarter, earliest_signal_at, timing_basis, timing_source_url,
    safety_lead_seconds
) AS (
    VALUES
    ('BEN', 3, TIMESTAMPTZ '2026-07-31 12:30:00+00',
     'OFFICIAL_EXACT',
     'https://investors.franklinresources.com/news-center/press-releases/press-release-details/2026/Franklin-Resources-Inc--to-Announce-Third-Quarter-Results-on-July-31-2026/default.aspx',
     7200),
    ('CBOE', 2, TIMESTAMPTZ '2026-07-31 11:30:00+00',
     'HISTORICAL_PATTERN',
     'https://ir.cboe.com/news/news-details/2026/Cboe-Global-Markets-Announces-Date-of-Second-Quarter-2026-Earnings-Release-and-Conference-Call/default.aspx',
     5400),
    ('CVX', 2, TIMESTAMPTZ '2026-07-31 10:15:00+00',
     'HISTORICAL_PATTERN',
     'https://www.chevron.com/investors/events-presentations/2q-2026-earnings',
     5400),
    ('CL', 2, TIMESTAMPTZ '2026-07-31 11:00:00+00',
     'HISTORICAL_PATTERN',
     'https://investor.colgatepalmolive.com/investor-news?ReleasesType=Earnings&page=1',
     5400),
    ('MRNA', 2, TIMESTAMPTZ '2026-07-31 10:30:00+00',
     'HISTORICAL_PATTERN',
     'https://investors.modernatx.com/events-presentations',
     5400),
    ('ARES', 2, TIMESTAMPTZ '2026-07-31 10:30:00+00',
     'HISTORICAL_PATTERN',
     'https://www.prnewswire.com/news-releases/ares-management-corporation-updates-the-time-of-its-earnings-conference-call-for-the-second-quarter-ending-june-30-2026-302822342.html',
     5400)
)
INSERT INTO resolution_profile_schedules (
    schedule_key, profile_key, automation_mode, preflight_at, activate_at,
    deactivate_at, earliest_signal_at, activation_safety_lead_seconds,
    timing_basis, timing_source_url, timing_contract_version, metadata, state
)
SELECT
    'schedule:earnings-' || lower(ticker) || '-2026q' || quarter,
    'earnings-' || lower(ticker) || '-2026q' || quarter,
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-31 08:30:00+00',
    TIMESTAMPTZ '2026-07-31 08:45:00+00',
    TIMESTAMPTZ '2026-07-31 14:30:00+00',
    earliest_signal_at,
    safety_lead_seconds,
    timing_basis,
    timing_source_url,
    1,
    jsonb_build_object(
        'seed', '038_add_july_31_premarket_batch',
        'preflight_lead_minutes', 15,
        'live_block', 'PRE_MARKET',
        'block_id', '2026-07-31-pre-market',
        'temporarily_paused', false,
        'armed_for_live', false,
        'quantity_policy', '100_shares',
        'aggregate_notional_cap', 1000,
        'earliest_signal_at', earliest_signal_at,
        'timing_basis', timing_basis,
        'timing_contract_version', 1
    ),
    'PENDING'
FROM schedule_config
ON CONFLICT (schedule_key) DO UPDATE
SET
    automation_mode = EXCLUDED.automation_mode,
    preflight_at = EXCLUDED.preflight_at,
    activate_at = EXCLUDED.activate_at,
    deactivate_at = EXCLUDED.deactivate_at,
    earliest_signal_at = EXCLUDED.earliest_signal_at,
    activation_safety_lead_seconds =
        EXCLUDED.activation_safety_lead_seconds,
    timing_basis = EXCLUDED.timing_basis,
    timing_source_url = EXCLUDED.timing_source_url,
    timing_contract_version = EXCLUDED.timing_contract_version,
    preflight_request_id = NULL,
    preflight_requested_at = NULL,
    preflight_lease_until = NULL,
    readiness_checked_at = NULL,
    readiness_valid_until = NULL,
    readiness_evidence = '{}'::jsonb,
    last_error_code = NULL,
    metadata = EXCLUDED.metadata,
    state = 'PENDING',
    updated_at = now()
WHERE resolution_profile_schedules.state = 'PENDING';

DO $verify$
DECLARE
    reviewed_notional numeric;
BEGIN
    IF (
        SELECT count(*) FROM earnings_market_rules
        WHERE scope_id IN (
            'earnings:BEN:2026Q3',
            'earnings:CBOE:2026Q2',
            'earnings:CVX:2026Q2',
            'earnings:CL:2026Q2',
            'earnings:MRNA:2026Q2',
            'earnings:ARES:2026Q2'
        )
          AND comparison_op = '>'
          AND primary_basis = 'diluted'
          AND status = 'SHADOW'
    ) <> 6 THEN
        RAISE EXCEPTION 'July 31 batch rule verification failed';
    END IF;
    IF (
        SELECT count(*) FROM resolution_execution_profiles
        WHERE profile_key IN (
            'earnings-ben-2026q3',
            'earnings-cboe-2026q2',
            'earnings-cvx-2026q2',
            'earnings-cl-2026q2',
            'earnings-mrna-2026q2',
            'earnings-ares-2026q2'
        )
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND status = 'DISABLED'
    ) <> 6 THEN
        RAISE EXCEPTION 'July 31 batch profile verification failed';
    END IF;
    IF (
        SELECT count(*) FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-ben-2026q3',
            'schedule:earnings-cboe-2026q2',
            'schedule:earnings-cvx-2026q2',
            'schedule:earnings-cl-2026q2',
            'schedule:earnings-mrna-2026q2',
            'schedule:earnings-ares-2026q2'
        )
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at = TIMESTAMPTZ '2026-07-31 08:30:00+00'
          AND activate_at = TIMESTAMPTZ '2026-07-31 08:45:00+00'
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
          AND metadata ->> 'armed_for_live' = 'false'
    ) <> 6 THEN
        RAISE EXCEPTION 'July 31 batch schedule verification failed';
    END IF;
    SELECT sum(quantity * greatest(yes_desired_price, no_desired_price))
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-ben-2026q3',
        'earnings-cboe-2026q2',
        'earnings-cvx-2026q2',
        'earnings-cl-2026q2',
        'earnings-mrna-2026q2',
        'earnings-ares-2026q2'
    );
    IF reviewed_notional <> 599.4 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'July 31 batch reviewed notional is invalid';
    END IF;
END
$verify$;

COMMIT;
