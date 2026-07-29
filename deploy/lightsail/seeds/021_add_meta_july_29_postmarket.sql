-- Add only the reviewed July 29 META POST_MARKET event. The profile remains
-- disabled and AUTO_PREFLIGHT cannot authorize live trading.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-29 17:45:00+00' THEN
        RAISE EXCEPTION 'META profile preparation deadline has passed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id = 'earnings:META:2026Q2'
          AND status = 'VALIDATED'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:META:2026Q2'
    ) THEN
        RAISE EXCEPTION 'META scope already contains facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id =
              '0x5b725d76638a67ec53ced1221dd6140ff0b419edb72a1653ba4aa82551601704'
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'META market has an active order group';
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
    'meta-2026q2-gaap-eps-7pt20',
    'earnings:META:2026Q2',
    'META',
    '1326801',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    'gaap_eps',
    'diluted',
    'basic',
    '>',
    7.20,
    2,
    'USD',
    'meta-quarterly-earnings-gaap-eps-07-29-2026-7pt2',
    '0x5b725d76638a67ec53ced1221dd6140ff0b419edb72a1653ba4aa82551601704',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "financial_highlights_gaap_diluted_eps",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "company_ir": {
            "allowed_document_hosts": ["investor.atmeta.com"],
            "feed_url": "https://investor.atmeta.com/rss/pressrelease.aspx",
            "kind": "rss",
            "provider": "company_ir",
            "title_all": [
                "Meta Reports",
                "Second Quarter",
                "2026",
                "Results"
            ],
            "title_none": ["to announce"]
        },
        "press_wire": {
            "allowed_document_hosts": ["www.prnewswire.com"],
            "feed_url": "https://www.prnewswire.com/rss/news-releases-list.rss",
            "kind": "rss",
            "provider": "prnewswire",
            "title_all": [
                "Meta Reports",
                "Second Quarter",
                "2026",
                "Results"
            ],
            "title_none": ["to announce"]
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
    'earnings-meta-2026q2',
    'earnings:META:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/meta-quarterly-earnings-gaap-eps-07-29-2026-7pt2',
    'abccbaq',
    '0x5b725d76638a67ec53ced1221dd6140ff0b419edb72a1653ba4aa82551601704',
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
        "rule_key": "meta-2026q2-gaap-eps-7pt20",
        "ticker": "META",
        "live_block": "POST_MARKET",
        "block_id": "2026-07-29-meta-post-market"
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
    'META:2026-07-29',
    'META',
    DATE '2026-07-29',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-29 20:05:00+00',
    TIMESTAMPTZ '2026-07-29 20:30:00+00',
    'CONFIRMED',
    'https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-to-Announce-Second-Quarter-2026-Results/default.aspx',
    'PARSER_ONLY',
    'FULL_HTML',
    '{
        "comparison_op": ">",
        "fallback_basis": "basic",
        "market_basis": "gaap_eps",
        "primary_basis": "diluted",
        "reported": ["gaap_eps"],
        "strike": "7.20"
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
            "delivery": "polling",
            "provider": "company_ir",
            "status": "profile_gated"
        },
        {
            "delivery": "polling",
            "provider": "prnewswire",
            "status": "profile_gated"
        }
    ]'::jsonb,
    'Reviewed META GAAP diluted EPS parser and disabled profile.',
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
    'schedule:earnings-meta-2026q2',
    'earnings-meta-2026q2',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-29 17:45:00+00',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    '{
        "seed": "021_add_meta_july_29_postmarket",
        "preflight_lead_minutes": 15,
        "live_block": "POST_MARKET",
        "block_id": "2026-07-29-meta-post-market",
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
        WHERE rule_key = 'meta-2026q2-gaap-eps-7pt20'
          AND scope_id = 'earnings:META:2026Q2'
          AND ticker = 'META'
          AND cik = '1326801'
          AND metric_kind = 'gaap_eps'
          AND primary_basis = 'diluted'
          AND fallback_basis = 'basic'
          AND comparison_op = '>'
          AND strike = 7.20
          AND condition_id =
              '0x5b725d76638a67ec53ced1221dd6140ff0b419edb72a1653ba4aa82551601704'
          AND source_policy -> 'sec' ->> 'required_item' = '2.02'
          AND source_policy -> 'company_ir' ->> 'provider' = 'company_ir'
          AND source_policy -> 'press_wire' ->> 'provider' = 'prnewswire'
          AND status = 'SHADOW'
    ) <> 1 THEN
        RAISE EXCEPTION 'META rule verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-meta-2026q2'
          AND scope_id = 'earnings:META:2026Q2'
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND prepare_from =
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND expires_at =
              TIMESTAMPTZ '2026-07-30 02:00:00+00'
          AND status = 'DISABLED'
    ) <> 1 THEN
        RAISE EXCEPTION 'META profile verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-meta-2026q2'
          AND profile_key = 'earnings-meta-2026q2'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at =
              TIMESTAMPTZ '2026-07-29 17:45:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND deactivate_at =
              TIMESTAMPTZ '2026-07-30 02:00:00+00'
          AND metadata ->> 'block_id' =
              '2026-07-29-meta-post-market'
    ) <> 1 THEN
        RAISE EXCEPTION 'META schedule verification failed';
    END IF;

    SELECT quantity * greatest(yes_desired_price, no_desired_price)
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-meta-2026q2';

    IF reviewed_notional <> 99.9 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'META reviewed notional is invalid';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:META:2026Q2'
    ) THEN
        RAISE EXCEPTION 'META execution claim must not exist';
    END IF;
END
$verify$;

COMMIT;
