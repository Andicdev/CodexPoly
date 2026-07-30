-- Add the issuer-confirmed July 30 RIVN POST_MARKET event. This is a late
-- preparation: the profile remains disabled and AUTO_PREFLIGHT cannot trade.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 18:30:00+00' THEN
        RAISE EXCEPTION 'RIVN profile preparation deadline has passed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:RIVN:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = 'earnings:RIVN:2026Q2'
    ) THEN
        RAISE EXCEPTION 'RIVN scope already contains facts or claims';
    END IF;
    IF EXISTS (
        SELECT 1 FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0xa99739deef61f908379c067815f2b9d5ba8aab1af77b2a65b216fa12d7e1f751'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'RIVN market has an active order group';
    END IF;
END
$guard$;

INSERT INTO earnings_market_rules (
    rule_key, scope_id, ticker, cik, fiscal_year, fiscal_quarter,
    period_end, estimated_release_at, metric_kind, primary_basis,
    fallback_basis, comparison_op, strike, rounding_places, currency,
    market_slug, condition_id, source_policy, fallback_policy, status
)
VALUES (
    'rivn-2026q2-gaap-eps-neg0pt78',
    'earnings:RIVN:2026Q2',
    'RIVN',
    '1874178',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    'gaap_eps',
    'diluted',
    'basic',
    '>',
    -0.78,
    2,
    'USD',
    'rivn-quarterly-earnings-gaap-eps-07-30-2026-neg0pt78',
    '0xa99739deef61f908379c067815f2b9d5ba8aab1af77b2a65b216fa12d7e1f751',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "current_period_gaap_basic_and_diluted_eps_row",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "company_ir": {
            "allowed_document_hosts": ["rivian.com", "www.rivian.com"],
            "feed_url": "https://rivian.com/newsroom",
            "kind": "html_listing",
            "listing_utc_offset_minutes": -240,
            "provider": "company_ir",
            "title_all": [
                "Rivian", "Second Quarter", "2026", "Financial Results"
            ],
            "title_none": [
                "Production and Delivery", "Sets Date", "Preliminary"
            ]
        },
        "press_wire": {
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": [
                "Rivian", "Second Quarter", "2026", "Financial Results"
            ],
            "title_none": [
                "Production and Delivery", "Sets Date", "Preliminary"
            ]
        }
    }'::jsonb,
    '{
        "gaap_secondary": "seeking_alpha",
        "gaap_after_hours": 96,
        "no_release_after_days": 45,
        "gaap_primary_basis": "diluted",
        "gaap_fallback_basis": "basic"
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
    updated_at = now()
WHERE earnings_market_rules.status = 'SHADOW';

INSERT INTO resolution_execution_profiles (
    profile_key, scope_id, source_name, source_reference, account_name,
    condition_id, yes_desired_price, no_desired_price, quantity,
    lifecycle_kind, old_tick, new_tick, max_reprices, prepare_from,
    expires_at, metadata, status
)
VALUES (
    'earnings-rivn-2026q2',
    'earnings:RIVN:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/rivn-quarterly-earnings-gaap-eps-07-30-2026-neg0pt78',
    'abccbaq',
    '0xa99739deef61f908379c067815f2b9d5ba8aab1af77b2a65b216fa12d7e1f751',
    0.999,
    0.999,
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-30 18:45:00+00',
    TIMESTAMPTZ '2026-07-31 02:00:00+00',
    '{
        "profile_template_key": "default",
        "quantity_policy": "100_shares",
        "rule_key": "rivn-2026q2-gaap-eps-neg0pt78",
        "ticker": "RIVN",
        "live_block": "POST_MARKET",
        "block_id": "2026-07-30-rivn-post-market"
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

INSERT INTO earnings_release_catalog (
    event_key, ticker, release_date, market_session, scheduled_release_at,
    conference_call_at, earliest_expected_release_at, timing_basis,
    timing_confidence, activation_safety_lead_seconds, timing_source_url,
    schedule_status, schedule_source_url, integration_status,
    document_format, metric_options, source_options, notes, verified_at
)
VALUES (
    'RIVN:2026-07-30',
    'RIVN',
    DATE '2026-07-30',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    TIMESTAMPTZ '2026-07-30 21:00:00+00',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    'HISTORICAL_PATTERN',
    'HIGH',
    4500,
    'https://www.sec.gov/Archives/edgar/data/1874178/000187417826000033/0001874178-26-000033-index.htm',
    'CONFIRMED',
    'https://www.sec.gov/Archives/edgar/data/1874178/000187417826000048/ex-9912q26deliveryproducti.htm',
    'PARSER_ONLY',
    'FULL_HTML',
    '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "gaap_eps",
        "primary_basis": "diluted",
        "reported_label": "GAAP basic and diluted EPS",
        "strike": "-0.78"
    }'::jsonb,
    '[
        {"delivery":"websocket","provider":"sec_api","status":"available"},
        {"delivery":"polling","provider":"sec_current","status":"profile_gated"},
        {"delivery":"polling","provider":"sec_latest","status":"profile_gated_observation_only"},
        {"delivery":"polling","provider":"company_ir","status":"profile_gated"},
        {"delivery":"rss","provider":"businesswire","status":"profile_gated"}
    ]'::jsonb,
    (
        'Issuer confirms the July 30 after-close release and 17:00 ET call. '
        'Q1 2026 and Q2 2025 SEC filings were accepted near 16:00 ET. '
        'Late preparation uses a reduced 75-minute activation lead.'
    ),
    now()
)
ON CONFLICT (event_key) DO UPDATE
SET
    ticker = EXCLUDED.ticker,
    release_date = EXCLUDED.release_date,
    market_session = EXCLUDED.market_session,
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

INSERT INTO resolution_profile_schedules (
    schedule_key, profile_key, automation_mode, preflight_at, activate_at,
    deactivate_at, earliest_signal_at, activation_safety_lead_seconds,
    timing_basis, timing_source_url, timing_contract_version, metadata, state
)
VALUES (
    'schedule:earnings-rivn-2026q2',
    'earnings-rivn-2026q2',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-30 18:30:00+00',
    TIMESTAMPTZ '2026-07-30 18:45:00+00',
    TIMESTAMPTZ '2026-07-31 02:00:00+00',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    4500,
    'HISTORICAL_PATTERN',
    'https://www.sec.gov/Archives/edgar/data/1874178/000187417826000033/0001874178-26-000033-index.htm',
    1,
    '{
        "seed": "035_add_rivn_july_30_postmarket",
        "preflight_lead_minutes": 15,
        "live_block": "POST_MARKET",
        "block_id": "2026-07-30-rivn-post-market",
        "temporarily_paused": false,
        "armed_for_live": false,
        "late_preparation": true,
        "operator_acceptance_required": true,
        "standard_lead_seconds": 7200,
        "quantity_policy": "100_shares",
        "aggregate_notional_cap": 1000,
        "earliest_signal_at": "2026-07-30T20:00:00Z",
        "timing_basis": "HISTORICAL_PATTERN",
        "timing_contract_version": 1
    }'::jsonb,
    'PENDING'
)
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
        WHERE rule_key = 'rivn-2026q2-gaap-eps-neg0pt78'
          AND scope_id = 'earnings:RIVN:2026Q2'
          AND cik = '1874178'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND comparison_op = '>'
          AND strike = -0.78
          AND condition_id =
              '0xa99739deef61f908379c067815f2b9d5ba8aab1af77b2a65b216fa12d7e1f751'
          AND source_policy -> 'press_wire' ->> 'provider' = 'businesswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN rule verification failed';
    END IF;
    IF (
        SELECT count(*) FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-rivn-2026q2'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN profile verification failed';
    END IF;
    IF (
        SELECT count(*) FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-rivn-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at = TIMESTAMPTZ '2026-07-30 18:30:00+00'
          AND activate_at = TIMESTAMPTZ '2026-07-30 18:45:00+00'
          AND earliest_signal_at = TIMESTAMPTZ '2026-07-30 20:00:00+00'
          AND activation_safety_lead_seconds = 4500
          AND metadata ->> 'operator_acceptance_required' = 'true'
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
    ) <> 1 THEN
        RAISE EXCEPTION 'RIVN schedule verification failed';
    END IF;
    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-rivn-2026q2';
    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'RIVN reviewed notional is invalid';
    END IF;
END
$verify$;

COMMIT;
