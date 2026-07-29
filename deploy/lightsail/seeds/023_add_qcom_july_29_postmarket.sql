-- Add only the reviewed July 29 QCOM POST_MARKET event. The profile remains
-- disabled and AUTO_PREFLIGHT cannot authorize live trading.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-29 17:45:00+00' THEN
        RAISE EXCEPTION 'QCOM profile preparation deadline has passed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:QCOM:2026Q3'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:QCOM:2026Q3'
    ) THEN
        RAISE EXCEPTION 'QCOM scope already contains facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0xe13b3b5087385775af2dbacd02af3386acb815b6c8a9d09bc013f158a172ba0a'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'QCOM market has an active order group';
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
    'qcom-2026q3-nongaap-eps-2pt23',
    'earnings:QCOM:2026Q3',
    'QCOM',
    '804328',
    2026,
    3,
    DATE '2026-06-28',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    'non_gaap_eps',
    'diluted',
    'basic',
    '>',
    2.23,
    2,
    'USD',
    'qcom-quarterly-earnings-nongaap-eps-07-29-2026-2pt23',
    '0xe13b3b5087385775af2dbacd02af3386acb815b6c8a9d09bc013f158a172ba0a',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "primary_headline_non_gaap_eps",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "company_ir": {
            "allowed_document_hosts": ["s204.q4cdn.com"],
            "feed_url": "https://s204.q4cdn.com/645488518/files/doc_financials/2026/q3/FY2026-3rd-Quarter-Earnings-Release.pdf",
            "kind": "direct_document",
            "provider": "company_ir",
            "title_all": [
                "Qualcomm",
                "Third Quarter",
                "Fiscal 2026",
                "Earnings Release"
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
    'earnings-qcom-2026q3',
    'earnings:QCOM:2026Q3',
    'earnings_resolution',
    'https://polymarket.com/event/qcom-quarterly-earnings-nongaap-eps-07-29-2026-2pt23',
    'abccbaq',
    '0xe13b3b5087385775af2dbacd02af3386acb815b6c8a9d09bc013f158a172ba0a',
    0.999,
    0.999,
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    '{
        "profile_template_key": "default",
        "quantity_policy": "100_shares",
        "rule_key": "qcom-2026q3-nongaap-eps-2pt23",
        "ticker": "QCOM",
        "live_block": "POST_MARKET",
        "block_id": "2026-07-29-qcom-post-market"
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
    'QCOM:2026-07-29',
    'QCOM',
    DATE '2026-07-29',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    TIMESTAMPTZ '2026-07-29 20:45:00+00',
    'CONFIRMED',
    'https://investor.qualcomm.com/news-events/press-releases/news-details/2026/Qualcomm-Schedules-Third-Quarter-Fiscal-2026-Earnings-Release-and-Conference-Call/default.aspx',
    'PARSER_ONLY',
    'PDF',
    '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "non_gaap_eps",
        "primary_basis": "diluted",
        "reported": ["gaap_eps", "non_gaap_eps"],
        "strike": "2.23"
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
            "status": "profile_gated"
        },
        {
            "delivery": "direct_document",
            "provider": "company_ir",
            "status": "profile_gated"
        }
    ]'::jsonb,
    'Reviewed QCOM non-GAAP diluted EPS parser and disabled profile.',
    now()
)
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
VALUES (
    'schedule:earnings-qcom-2026q3',
    'earnings-qcom-2026q3',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-29 17:45:00+00',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    '{
        "seed": "023_add_qcom_july_29_postmarket",
        "preflight_lead_minutes": 15,
        "live_block": "POST_MARKET",
        "block_id": "2026-07-29-qcom-post-market",
        "temporarily_paused": false,
        "armed_for_live": false,
        "quantity_policy": "100_shares",
        "aggregate_notional_cap": 1000
    }'::jsonb,
    'PENDING'
)
ON CONFLICT (schedule_key) DO UPDATE
SET
    automation_mode = EXCLUDED.automation_mode,
    preflight_at = EXCLUDED.preflight_at,
    activate_at = EXCLUDED.activate_at,
    deactivate_at = EXCLUDED.deactivate_at,
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
        WHERE rule_key = 'qcom-2026q3-nongaap-eps-2pt23'
          AND scope_id = 'earnings:QCOM:2026Q3'
          AND ticker = 'QCOM'
          AND cik = '804328'
          AND metric_kind = 'non_gaap_eps'
          AND comparison_op = '>'
          AND strike = 2.23
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'company_ir' ->> 'kind' =
              'direct_document'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'QCOM rule verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-qcom-2026q3'
          AND scope_id = 'earnings:QCOM:2026Q3'
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
        RAISE EXCEPTION 'QCOM profile verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-qcom-2026q3'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at =
              TIMESTAMPTZ '2026-07-29 17:45:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND deactivate_at =
              TIMESTAMPTZ '2026-07-30 02:00:00+00'
    ) <> 1 THEN
        RAISE EXCEPTION 'QCOM schedule verification failed';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-qcom-2026q3';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'QCOM reviewed notional is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:QCOM:2026Q3'
    ) THEN
        RAISE EXCEPTION 'QCOM execution claim must not exist';
    END IF;
END
$verify$;

COMMIT;
