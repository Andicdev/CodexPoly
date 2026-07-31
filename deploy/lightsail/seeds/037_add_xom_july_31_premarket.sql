-- Add the issuer-confirmed July 31 XOM PRE_MARKET event. The profile
-- remains disabled and AUTO_PREFLIGHT cannot authorize live trading.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-31 09:45:00+00' THEN
        RAISE EXCEPTION 'XOM profile preparation deadline has passed';
    END IF;
    IF EXISTS (
        SELECT 1 FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:XOM:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1 FROM resolution_execution_claims
        WHERE scope_id = 'earnings:XOM:2026Q2'
    ) THEN
        RAISE EXCEPTION 'XOM scope already contains facts or claims';
    END IF;
    IF EXISTS (
        SELECT 1 FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'XOM market has an active order group';
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
    'xom-2026q2-nongaap-eps-3pt66',
    'earnings:XOM:2026Q2',
    'XOM',
    '2115436',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-31 10:30:00+00',
    'non_gaap_eps',
    'diluted',
    'basic',
    '>',
    3.66,
    2,
    'USD',
    'xom-quarterly-earnings-nongaap-eps-07-31-2026-3pt66',
    '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "earnings_excluding_identified_items_per_common_share",
        "issuer_successor_effective_date": "2026-07-01",
        "predecessor_cik": "34088",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "company_ir": {
            "allowed_document_hosts": ["investor.exxonmobil.com"],
            "feed_url": "https://investor.exxonmobil.com/company-information/press-releases/rss",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "ExxonMobil", "Announces", "Second",
                "Quarter", "2026", "Results"
            ],
            "title_none": [
                "to Release", "Earnings Call",
                "Earnings Considerations", "Preliminary"
            ]
        },
        "press_wire": {
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": [
                "ExxonMobil", "Announces", "Second",
                "Quarter", "2026", "Results"
            ],
            "title_none": [
                "to Release", "Earnings Call",
                "Earnings Considerations", "Preliminary"
            ]
        }
    }'::jsonb,
    '{
        "non_gaap_secondary": "seeking_alpha",
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
    'earnings-xom-2026q2',
    'earnings:XOM:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/xom-quarterly-earnings-nongaap-eps-07-31-2026-3pt66',
    'abccbaq',
    '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd',
    0.999,
    0.999,
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-31 08:30:00+00',
    TIMESTAMPTZ '2026-07-31 14:00:00+00',
    '{
        "profile_template_key": "default",
        "quantity_policy": "100_shares",
        "rule_key": "xom-2026q2-nongaap-eps-3pt66",
        "ticker": "XOM",
        "live_block": "PRE_MARKET",
        "block_id": "2026-07-31-pre-market"
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
    'XOM:2026-07-31',
    'XOM',
    DATE '2026-07-31',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-31 10:30:00+00',
    TIMESTAMPTZ '2026-07-31 13:30:00+00',
    TIMESTAMPTZ '2026-07-31 10:30:00+00',
    'OFFICIAL_EXACT',
    'HIGH',
    7200,
    'https://investor.exxonmobil.com/company-information/press-releases/detail/1207/exxonmobil-to-release-second-quarter-2026-financial-results',
    'CONFIRMED',
    'https://investor.exxonmobil.com/news-events/ir-calendar/detail/20260731-2q-2026-earnings-call',
    'PARSER_ONLY',
    'FULL_HTML',
    '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "non_gaap_eps",
        "primary_basis": "diluted",
        "reported_label": "Earnings Excluding Identified Items Per Common Share",
        "strike": "3.66"
    }'::jsonb,
    '[
        {"delivery":"websocket","provider":"sec_api","status":"available"},
        {"delivery":"polling","provider":"sec_current","status":"profile_gated"},
        {"delivery":"polling","provider":"sec_latest","status":"profile_gated_observation_only"},
        {"delivery":"rss","provider":"company_ir","status":"profile_gated_replay_verified"},
        {"delivery":"rss","provider":"businesswire","status":"profile_gated_configured_fallback"}
    ]'::jsonb,
    (
        'Issuer confirms the release at 05:30 CT and the call at 08:30 CT. '
        'The official IR RSS exposed Q1 at 06:30 ET, while the Q1 SEC filing '
        'was accepted at 06:31:52 ET. ExxonMobil Holdings CIK 2115436 '
        'succeeded predecessor CIK 34088 on July 1, 2026.'
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
    'schedule:earnings-xom-2026q2',
    'earnings-xom-2026q2',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-31 08:15:00+00',
    TIMESTAMPTZ '2026-07-31 08:30:00+00',
    TIMESTAMPTZ '2026-07-31 14:00:00+00',
    TIMESTAMPTZ '2026-07-31 10:30:00+00',
    7200,
    'OFFICIAL_EXACT',
    'https://investor.exxonmobil.com/company-information/press-releases/detail/1207/exxonmobil-to-release-second-quarter-2026-financial-results',
    1,
    '{
        "seed": "037_add_xom_july_31_premarket",
        "preflight_lead_minutes": 15,
        "live_block": "PRE_MARKET",
        "block_id": "2026-07-31-pre-market",
        "temporarily_paused": false,
        "armed_for_live": false,
        "quantity_policy": "100_shares",
        "aggregate_notional_cap": 1000,
        "earliest_signal_at": "2026-07-31T10:30:00Z",
        "timing_basis": "OFFICIAL_EXACT",
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
        WHERE rule_key = 'xom-2026q2-nongaap-eps-3pt66'
          AND scope_id = 'earnings:XOM:2026Q2'
          AND cik = '2115436'
          AND metric_kind = 'non_gaap_eps'
          AND primary_basis = 'diluted'
          AND comparison_op = '>'
          AND strike = 3.66
          AND condition_id =
              '0x4f47cfcf38650017dfcbf87a05776eb9692bdfab37d8bd8bcdba8733c7eb0fcd'
          AND source_policy ->> 'predecessor_cik' = '34088'
          AND source_policy -> 'company_ir' ->> 'provider' = 'company_ir'
          AND source_policy -> 'press_wire' ->> 'provider' = 'businesswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM rule verification failed';
    END IF;
    IF (
        SELECT count(*) FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-xom-2026q2'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM profile verification failed';
    END IF;
    IF (
        SELECT count(*) FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-xom-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at = TIMESTAMPTZ '2026-07-31 08:15:00+00'
          AND activate_at = TIMESTAMPTZ '2026-07-31 08:30:00+00'
          AND earliest_signal_at =
              TIMESTAMPTZ '2026-07-31 10:30:00+00'
          AND activation_safety_lead_seconds = 7200
          AND timing_basis = 'OFFICIAL_EXACT'
          AND timing_contract_version = 1
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
          AND metadata ->> 'armed_for_live' = 'false'
    ) <> 1 THEN
        RAISE EXCEPTION 'XOM schedule verification failed';
    END IF;
    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-xom-2026q2';
    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'XOM reviewed notional is invalid';
    END IF;
END
$verify$;

COMMIT;
