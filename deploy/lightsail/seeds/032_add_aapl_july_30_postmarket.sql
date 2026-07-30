-- Add the issuer-confirmed July 30 AAPL POST_MARKET event. The profile
-- remains disabled and AUTO_PREFLIGHT cannot authorize live trading.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 18:15:00+00' THEN
        RAISE EXCEPTION 'AAPL profile preparation deadline has passed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:AAPL:2026Q3'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:AAPL:2026Q3'
    ) THEN
        RAISE EXCEPTION 'AAPL scope already contains facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x48af8cf39c8f44b70f951255fb29a956f2093e8596defc9a7da87e52c8464377'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'AAPL market has an active order group';
    END IF;
END
$guard$;

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
    'aapl-2026q3-gaap-eps-1pt89',
    'earnings:AAPL:2026Q3',
    'AAPL',
    '320193',
    2026,
    3,
    DATE '2026-06-27',
    TIMESTAMPTZ '2026-07-30 20:30:00+00',
    'gaap_eps',
    'diluted',
    'basic',
    '>',
    1.89,
    2,
    'USD',
    'aapl-quarterly-earnings-gaap-eps-07-30-2026-1pt89',
    '0x48af8cf39c8f44b70f951255fb29a956f2093e8596defc9a7da87e52c8464377',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "current_quarter_headline_gaap_diluted_eps",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "company_ir": {
            "allowed_document_hosts": ["www.apple.com"],
            "feed_url": "https://www.apple.com/newsroom/rss-feed.rss",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "Apple",
                "reports",
                "third quarter",
                "results"
            ],
            "title_none": ["conference call", "earnings call"]
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
    'earnings-aapl-2026q3',
    'earnings:AAPL:2026Q3',
    'earnings_resolution',
    'https://polymarket.com/event/aapl-quarterly-earnings-gaap-eps-07-30-2026-1pt89',
    'abccbaq',
    '0x48af8cf39c8f44b70f951255fb29a956f2093e8596defc9a7da87e52c8464377',
    0.999,
    0.999,
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-30 18:30:00+00',
    TIMESTAMPTZ '2026-07-31 02:00:00+00',
    '{
        "profile_template_key": "default",
        "quantity_policy": "100_shares",
        "rule_key": "aapl-2026q3-gaap-eps-1pt89",
        "ticker": "AAPL",
        "live_block": "POST_MARKET",
        "block_id": "2026-07-30-aapl-post-market"
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
    event_key,
    ticker,
    release_date,
    market_session,
    scheduled_release_at,
    conference_call_at,
    earliest_expected_release_at,
    timing_basis,
    timing_confidence,
    activation_safety_lead_seconds,
    timing_source_url,
    schedule_status,
    schedule_source_url,
    integration_status,
    document_format,
    metric_options,
    source_options,
    notes,
    verified_at
)
VALUES (
    'AAPL:2026-07-30',
    'AAPL',
    DATE '2026-07-30',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-30 20:30:00+00',
    TIMESTAMPTZ '2026-07-30 21:00:00+00',
    TIMESTAMPTZ '2026-07-30 20:30:00+00',
    'HISTORICAL_PATTERN',
    'HIGH',
    7200,
    'https://www.sec.gov/Archives/edgar/data/320193/000032019325000071/0000320193-25-000071-index.htm',
    'CONFIRMED',
    'https://investor.apple.com/investor-relations/default.aspx',
    'PARSER_ONLY',
    'FULL_HTML',
    '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "gaap_eps",
        "primary_basis": "diluted",
        "reported_label": "diluted earnings per share",
        "strike": "1.89"
    }'::jsonb,
    '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "available"
        },
        {
            "delivery": "polling",
            "provider": "sec_current",
            "status": "profile_gated"
        },
        {
            "delivery": "polling",
            "provider": "sec_latest",
            "status": "profile_gated_observation_only"
        },
        {
            "delivery": "atom",
            "provider": "company_ir",
            "status": "profile_gated"
        }
    ]'::jsonb,
    (
        'Apple confirms the July 30 date and 14:00 PT call. '
        'The comparable 2025 Q3 and 2026 Q2 8-K filings were accepted '
        'at 16:30 ET; the executable window uses that release pattern.'
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
    earliest_expected_release_at =
        EXCLUDED.earliest_expected_release_at,
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
    'RESEARCH_PENDING',
    'PARSER_ONLY'
);

INSERT INTO resolution_profile_schedules (
    schedule_key,
    profile_key,
    automation_mode,
    preflight_at,
    activate_at,
    deactivate_at,
    earliest_signal_at,
    activation_safety_lead_seconds,
    timing_basis,
    timing_source_url,
    timing_contract_version,
    metadata,
    state
)
VALUES (
    'schedule:earnings-aapl-2026q3',
    'earnings-aapl-2026q3',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-30 18:15:00+00',
    TIMESTAMPTZ '2026-07-30 18:30:00+00',
    TIMESTAMPTZ '2026-07-31 02:00:00+00',
    TIMESTAMPTZ '2026-07-30 20:30:00+00',
    7200,
    'HISTORICAL_PATTERN',
    'https://www.sec.gov/Archives/edgar/data/320193/000032019325000071/0000320193-25-000071-index.htm',
    1,
    '{
        "seed": "032_add_aapl_july_30_postmarket",
        "preflight_lead_minutes": 15,
        "live_block": "POST_MARKET",
        "block_id": "2026-07-30-aapl-post-market",
        "temporarily_paused": false,
        "armed_for_live": false,
        "quantity_policy": "100_shares",
        "aggregate_notional_cap": 1000,
        "earliest_signal_at": "2026-07-30T20:30:00Z",
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
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'aapl-2026q3-gaap-eps-1pt89'
          AND scope_id = 'earnings:AAPL:2026Q3'
          AND ticker = 'AAPL'
          AND cik = '320193'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 1.89
          AND condition_id =
              '0x48af8cf39c8f44b70f951255fb29a956f2093e8596defc9a7da87e52c8464377'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'AAPL rule verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-aapl-2026q3'
          AND scope_id = 'earnings:AAPL:2026Q3'
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
        RAISE EXCEPTION 'AAPL profile verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'AAPL:2026-07-30'
          AND market_session = 'POST_MARKET'
          AND earliest_expected_release_at =
              TIMESTAMPTZ '2026-07-30 20:30:00+00'
          AND conference_call_at =
              TIMESTAMPTZ '2026-07-30 21:00:00+00'
          AND timing_basis = 'HISTORICAL_PATTERN'
          AND timing_confidence = 'HIGH'
          AND activation_safety_lead_seconds = 7200
          AND schedule_status = 'CONFIRMED'
    ) <> 1 THEN
        RAISE EXCEPTION 'AAPL catalog verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-aapl-2026q3'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at =
              TIMESTAMPTZ '2026-07-30 18:15:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-30 18:30:00+00'
          AND earliest_signal_at =
              TIMESTAMPTZ '2026-07-30 20:30:00+00'
          AND activation_safety_lead_seconds = 7200
          AND timing_contract_version = 1
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
    ) <> 1 THEN
        RAISE EXCEPTION 'AAPL schedule verification failed';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-aapl-2026q3';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'AAPL reviewed notional is invalid';
    END IF;
END
$verify$;

COMMIT;
