-- Add the issuer-confirmed July 30 AMZN POST_MARKET event. The profile
-- remains disabled and AUTO_PREFLIGHT cannot authorize live trading.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 17:45:00+00' THEN
        RAISE EXCEPTION 'AMZN profile preparation deadline has passed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:AMZN:2026Q2'
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:AMZN:2026Q2'
    ) THEN
        RAISE EXCEPTION 'AMZN scope already contains facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x778f7b1584c2d2585944ac4020dcb187ac86f4552293ad7dd9bb1c79e458e4fb'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'AMZN market has an active order group';
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
    'amzn-2026q2-gaap-eps-1pt82',
    'earnings:AMZN:2026Q2',
    'AMZN',
    '1018724',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-30 20:01:00+00',
    'gaap_eps',
    'diluted',
    'basic',
    '>',
    1.82,
    2,
    'USD',
    'amzn-quarterly-earnings-gaap-eps-07-30-2026-1pt82',
    '0x778f7b1584c2d2585944ac4020dcb187ac86f4552293ad7dd9bb1c79e458e4fb',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "current_quarter_net_income_or_loss_per_diluted_share",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "company_ir": {
            "allowed_document_hosts": ["ir.aboutamazon.com"],
            "feed_url": "https://ir.aboutamazon.com/rss/pressrelease.aspx",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "Amazon.com",
                "Announces",
                "Second Quarter",
                "Results"
            ],
            "title_none": ["to Webcast", "Conference Call"]
        },
        "press_wire": {
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": [
                "Amazon.com",
                "Announces",
                "Second Quarter",
                "Results"
            ],
            "title_none": ["to Webcast", "Conference Call"]
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
    'earnings-amzn-2026q2',
    'earnings:AMZN:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/amzn-quarterly-earnings-gaap-eps-07-30-2026-1pt82',
    'abccbaq',
    '0x778f7b1584c2d2585944ac4020dcb187ac86f4552293ad7dd9bb1c79e458e4fb',
    0.999,
    0.999,
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-30 18:00:00+00',
    TIMESTAMPTZ '2026-07-31 02:00:00+00',
    '{
        "profile_template_key": "default",
        "quantity_policy": "100_shares",
        "rule_key": "amzn-2026q2-gaap-eps-1pt82",
        "ticker": "AMZN",
        "live_block": "POST_MARKET",
        "block_id": "2026-07-30-amzn-post-market"
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
    'AMZN:2026-07-30',
    'AMZN',
    DATE '2026-07-30',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-30 20:01:00+00',
    TIMESTAMPTZ '2026-07-30 21:00:00+00',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    'HISTORICAL_PATTERN',
    'MEDIUM',
    7200,
    'https://ir.aboutamazon.com/rss/pressrelease.aspx',
    'CONFIRMED',
    'https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-to-Webcast-Second-Quarter-2026-Financial-Results-Conference-Call/default.aspx',
    'PARSER_ONLY',
    'FULL_HTML',
    '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "gaap_eps",
        "primary_basis": "diluted",
        "reported_label": "net income or loss per diluted share",
        "strike": "1.82"
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
            "delivery": "rss",
            "provider": "company_ir",
            "status": "profile_gated"
        },
        {
            "delivery": "rss",
            "provider": "businesswire",
            "status": "profile_gated"
        }
    ]'::jsonb,
    (
        'Issuer confirms the July 30 date and the 17:00 ET call. '
        'Amazon IR published the prior 2026 quarterly result at 16:01 ET; '
        'the executable window uses the 16:00 ET session floor, not the call.'
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
    'schedule:earnings-amzn-2026q2',
    'earnings-amzn-2026q2',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-30 17:45:00+00',
    TIMESTAMPTZ '2026-07-30 18:00:00+00',
    TIMESTAMPTZ '2026-07-31 02:00:00+00',
    TIMESTAMPTZ '2026-07-30 20:00:00+00',
    7200,
    'HISTORICAL_PATTERN',
    'https://ir.aboutamazon.com/rss/pressrelease.aspx',
    1,
    '{
        "seed": "031_add_amzn_july_30_postmarket",
        "preflight_lead_minutes": 15,
        "live_block": "POST_MARKET",
        "block_id": "2026-07-30-amzn-post-market",
        "temporarily_paused": false,
        "armed_for_live": false,
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
        SELECT count(*)
        FROM earnings_market_rules
        WHERE rule_key = 'amzn-2026q2-gaap-eps-1pt82'
          AND scope_id = 'earnings:AMZN:2026Q2'
          AND ticker = 'AMZN'
          AND cik = '1018724'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 1.82
          AND condition_id =
              '0x778f7b1584c2d2585944ac4020dcb187ac86f4552293ad7dd9bb1c79e458e4fb'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'company_ir' ->> 'provider' =
              'company_ir'
          AND source_policy -> 'press_wire' ->> 'provider' =
              'businesswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'AMZN rule verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-amzn-2026q2'
          AND scope_id = 'earnings:AMZN:2026Q2'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND prepare_from =
              TIMESTAMPTZ '2026-07-30 18:00:00+00'
          AND expires_at =
              TIMESTAMPTZ '2026-07-31 02:00:00+00'
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'AMZN profile verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'AMZN:2026-07-30'
          AND ticker = 'AMZN'
          AND release_date = DATE '2026-07-30'
          AND market_session = 'POST_MARKET'
          AND earliest_expected_release_at =
              TIMESTAMPTZ '2026-07-30 20:00:00+00'
          AND conference_call_at =
              TIMESTAMPTZ '2026-07-30 21:00:00+00'
          AND timing_basis = 'HISTORICAL_PATTERN'
          AND timing_confidence = 'MEDIUM'
          AND activation_safety_lead_seconds = 7200
          AND schedule_status = 'CONFIRMED'
          AND integration_status = 'PARSER_ONLY'
    ) <> 1 THEN
        RAISE EXCEPTION 'AMZN catalog verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-amzn-2026q2'
          AND profile_key = 'earnings-amzn-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at =
              TIMESTAMPTZ '2026-07-30 17:45:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-30 18:00:00+00'
          AND deactivate_at =
              TIMESTAMPTZ '2026-07-31 02:00:00+00'
          AND earliest_signal_at =
              TIMESTAMPTZ '2026-07-30 20:00:00+00'
          AND activation_safety_lead_seconds = 7200
          AND timing_basis = 'HISTORICAL_PATTERN'
          AND timing_contract_version = 1
          AND activate_at <= earliest_signal_at
              - activation_safety_lead_seconds * interval '1 second'
          AND metadata ->> 'block_id' =
              '2026-07-30-amzn-post-market'
    ) <> 1 THEN
        RAISE EXCEPTION 'AMZN schedule verification failed';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-amzn-2026q2';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'AMZN reviewed notional is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:AMZN:2026Q2'
    ) THEN
        RAISE EXCEPTION 'AMZN execution claim must not exist';
    END IF;
END
$verify$;

COMMIT;
