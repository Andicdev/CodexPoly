-- Add only issuer-confirmed July 30 YUM, ICE, and CI PRE_MARKET events.
-- Profiles remain disabled and AUTO_PREFLIGHT cannot authorize live trading.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $guard$
BEGIN
    IF now() >= TIMESTAMPTZ '2026-07-30 09:40:00+00' THEN
        RAISE EXCEPTION 'YUM/ICE/CI preparation deadline has passed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_fact_candidates
        WHERE scope_id IN (
            'earnings:YUM:2026Q2',
            'earnings:ICE:2026Q2',
            'earnings:CI:2026Q2'
        )
          AND status IN ('VALIDATED', 'EMITTED')
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id IN (
            'earnings:YUM:2026Q2',
            'earnings:ICE:2026Q2',
            'earnings:CI:2026Q2'
        )
    ) THEN
        RAISE EXCEPTION 'YUM/ICE/CI scopes already contain facts or claims';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_order_groups
        WHERE account_name = 'abccbaq'
          AND condition_id IN (
              '0xf12f1d26c9f7c02c36e0986be4e32f5adc2b30642f0f1f4dda2b5a51bf3e20dd',
              '0x52f96f0d385691c1534d86c7fbad89abd4358da382624b79882279a4ec3eaa20',
              '0xecdbab51723875aee7d00faa3b5a8adbbfe7054763dff375c92443a670bb6a61'
          )
          AND status IN ('ACTIVE', 'REPRICING')
    ) THEN
        RAISE EXCEPTION 'YUM/ICE/CI market has an active order group';
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
VALUES
(
    'yum-2026q2-nongaap-eps-1pt56',
    'earnings:YUM:2026Q2',
    'YUM',
    '1041061',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-30 11:00:00+00',
    'non_gaap_eps',
    'diluted',
    'basic',
    '>',
    1.56,
    2,
    'USD',
    'yum-quarterly-earnings-nongaap-eps-07-30-2026-1pt56',
    '0xf12f1d26c9f7c02c36e0986be4e32f5adc2b30642f0f1f4dda2b5a51bf3e20dd',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "primary_headline_eps_excluding_special_items",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "press_wire": {
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": ["Yum", "Second", "Quarter", "Results"],
            "title_none": ["Conference Call Details", "to release"]
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
),
(
    'ice-2026q2-nongaap-eps-1pt84',
    'earnings:ICE:2026Q2',
    'ICE',
    '1571949',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-30 11:30:00+00',
    'non_gaap_eps',
    'diluted',
    'basic',
    '>',
    1.84,
    2,
    'USD',
    'ice-quarterly-earnings-nongaap-eps-07-30-2026-1pt84',
    '0x52f96f0d385691c1534d86c7fbad89abd4358da382624b79882279a4ec3eaa20',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "primary_headline_adjusted_diluted_eps",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "press_wire": {
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": [
                "Intercontinental Exchange",
                "Second Quarter",
                "2026"
            ],
            "title_none": ["Statistics", "Conference Call"]
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
),
(
    'ci-2026q2-nongaap-eps-7pt60',
    'earnings:CI:2026Q2',
    'CI',
    '1739940',
    2026,
    2,
    DATE '2026-06-30',
    TIMESTAMPTZ '2026-07-30 12:30:00+00',
    'non_gaap_eps',
    'diluted',
    'basic',
    '>',
    7.60,
    2,
    'USD',
    'ci-quarterly-earnings-nongaap-eps-07-30-2026-7pt6',
    '0xecdbab51723875aee7d00faa3b5a8adbbfe7054763dff375c92443a670bb6a61',
    '{
        "primary_authority": "official_company",
        "initial_release_only": true,
        "metric_selection": "primary_headline_adjusted_income_per_share",
        "sec": {
            "form_type": "8-K",
            "required_item": "2.02",
            "document_type": "EX-99.1"
        },
        "press_wire": {
            "allowed_document_hosts": ["www.businesswire.com"],
            "feed_url": "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtQWw==",
            "kind": "rss",
            "provider": "businesswire",
            "title_all": ["Cigna", "Second Quarter", "2026", "Results"],
            "title_none": ["Conference", "to report"]
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
VALUES
(
    'earnings-yum-2026q2',
    'earnings:YUM:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/yum-quarterly-earnings-nongaap-eps-07-30-2026-1pt56',
    'abccbaq',
    '0xf12f1d26c9f7c02c36e0986be4e32f5adc2b30642f0f1f4dda2b5a51bf3e20dd',
    0.999,
    0.999,
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-30 09:45:00+00',
    TIMESTAMPTZ '2026-07-30 13:30:00+00',
    '{"profile_template_key":"default","quantity_policy":"100_shares","rule_key":"yum-2026q2-nongaap-eps-1pt56","ticker":"YUM","live_block":"PRE_MARKET","block_id":"2026-07-30-extra-pre-market"}'::jsonb,
    'DISABLED'
),
(
    'earnings-ice-2026q2',
    'earnings:ICE:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/ice-quarterly-earnings-nongaap-eps-07-30-2026-1pt84',
    'abccbaq',
    '0x52f96f0d385691c1534d86c7fbad89abd4358da382624b79882279a4ec3eaa20',
    0.999,
    0.999,
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-30 09:45:00+00',
    TIMESTAMPTZ '2026-07-30 14:00:00+00',
    '{"profile_template_key":"default","quantity_policy":"100_shares","rule_key":"ice-2026q2-nongaap-eps-1pt84","ticker":"ICE","live_block":"PRE_MARKET","block_id":"2026-07-30-extra-pre-market"}'::jsonb,
    'DISABLED'
),
(
    'earnings-ci-2026q2',
    'earnings:CI:2026Q2',
    'earnings_resolution',
    'https://polymarket.com/event/ci-quarterly-earnings-nongaap-eps-07-30-2026-7pt6',
    'abccbaq',
    '0xecdbab51723875aee7d00faa3b5a8adbbfe7054763dff375c92443a670bb6a61',
    0.999,
    0.999,
    100,
    'reprice_on_tick_change',
    0.01,
    0.001,
    1,
    TIMESTAMPTZ '2026-07-30 09:45:00+00',
    TIMESTAMPTZ '2026-07-30 14:30:00+00',
    '{"profile_template_key":"default","quantity_policy":"100_shares","rule_key":"ci-2026q2-nongaap-eps-7pt60","ticker":"CI","live_block":"PRE_MARKET","block_id":"2026-07-30-extra-pre-market"}'::jsonb,
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
VALUES
(
    'YUM:2026-07-30',
    'YUM',
    DATE '2026-07-30',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-30 11:00:00+00',
    TIMESTAMPTZ '2026-07-30 12:15:00+00',
    'CONFIRMED',
    'https://investors.yum.com/news-events/financial-releases/news-details/2026/Yum-Brands-Announces-Q2-2026-Earnings-and-Conference-Call-Details/default.aspx',
    'PARSER_ONLY',
    'FULL_HTML',
    '{"comparison_op":">","market_basis":"non_gaap_eps","primary_basis":"diluted","reported_label":"EPS excluding Special Items","strike":"1.56"}'::jsonb,
    '[{"delivery":"websocket","provider":"sec_api","status":"available"},{"delivery":"polling","provider":"sec","status":"profile_gated"},{"delivery":"rss","provider":"businesswire","status":"profile_gated"}]'::jsonb,
    'Issuer confirms release at 07:00 ET and call at 08:15 ET.',
    now()
),
(
    'ICE:2026-07-30',
    'ICE',
    DATE '2026-07-30',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-30 11:30:00+00',
    TIMESTAMPTZ '2026-07-30 12:30:00+00',
    'CONFIRMED',
    'https://ir.theice.com/press/news-details/2026/Intercontinental-Exchange-Reports-Record-First-Quarter-2026/default.aspx',
    'PARSER_ONLY',
    'FULL_HTML',
    '{"comparison_op":">","market_basis":"non_gaap_eps","primary_basis":"diluted","reported_label":"Adjusted diluted EPS","strike":"1.84"}'::jsonb,
    '[{"delivery":"websocket","provider":"sec_api","status":"available"},{"delivery":"polling","provider":"sec","status":"profile_gated"},{"delivery":"rss","provider":"businesswire","status":"profile_gated"}]'::jsonb,
    'Issuer confirms the 08:30 ET call; 07:30 ET is a historical release estimate.',
    now()
),
(
    'CI:2026-07-30',
    'CI',
    DATE '2026-07-30',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-07-30 12:30:00+00',
    TIMESTAMPTZ '2026-07-30 12:30:00+00',
    'CONFIRMED',
    'https://investors.thecignagroup.com/events-and-presentations/events/event-details/2026/Second-Quarter-2026-Earnings-Release-2026-MLPNK-N11I/default.aspx',
    'PARSER_ONLY',
    'FULL_HTML',
    '{"comparison_op":">","market_basis":"non_gaap_eps","primary_basis":"diluted","reported_label":"Adjusted income from operations per share","strike":"7.60"}'::jsonb,
    '[{"delivery":"websocket","provider":"sec_api","status":"available"},{"delivery":"polling","provider":"sec","status":"profile_gated"},{"delivery":"rss","provider":"businesswire","status":"profile_gated"}]'::jsonb,
    'Issuer calendar confirms the earnings release at 08:30 ET.',
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
    metadata,
    state
)
VALUES
(
    'schedule:earnings-yum-2026q2',
    'earnings-yum-2026q2',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-30 09:45:00+00',
    TIMESTAMPTZ '2026-07-30 10:00:00+00',
    TIMESTAMPTZ '2026-07-30 13:30:00+00',
    '{"seed":"030_add_yum_ice_ci_july_30_premarket","preflight_lead_minutes":15,"live_block":"PRE_MARKET","block_id":"2026-07-30-extra-pre-market","temporarily_paused":false,"armed_for_live":false,"quantity_policy":"100_shares","aggregate_notional_cap":1000}'::jsonb,
    'PENDING'
),
(
    'schedule:earnings-ice-2026q2',
    'earnings-ice-2026q2',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-30 09:45:00+00',
    TIMESTAMPTZ '2026-07-30 10:00:00+00',
    TIMESTAMPTZ '2026-07-30 14:00:00+00',
    '{"seed":"030_add_yum_ice_ci_july_30_premarket","preflight_lead_minutes":15,"live_block":"PRE_MARKET","block_id":"2026-07-30-extra-pre-market","temporarily_paused":false,"armed_for_live":false,"quantity_policy":"100_shares","aggregate_notional_cap":1000}'::jsonb,
    'PENDING'
),
(
    'schedule:earnings-ci-2026q2',
    'earnings-ci-2026q2',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-30 09:45:00+00',
    TIMESTAMPTZ '2026-07-30 10:00:00+00',
    TIMESTAMPTZ '2026-07-30 14:30:00+00',
    '{"seed":"030_add_yum_ice_ci_july_30_premarket","preflight_lead_minutes":15,"live_block":"PRE_MARKET","block_id":"2026-07-30-extra-pre-market","temporarily_paused":false,"armed_for_live":false,"quantity_policy":"100_shares","aggregate_notional_cap":1000}'::jsonb,
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
        WHERE rule_key IN (
            'yum-2026q2-nongaap-eps-1pt56',
            'ice-2026q2-nongaap-eps-1pt84',
            'ci-2026q2-nongaap-eps-7pt60'
        )
          AND status = 'SHADOW'
          AND source_policy -> 'press_wire' ->> 'provider' =
              'businesswire'
    ) <> 3 THEN
        RAISE EXCEPTION 'YUM/ICE/CI rule verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_execution_profiles
        WHERE profile_key IN (
            'earnings-yum-2026q2',
            'earnings-ice-2026q2',
            'earnings-ci-2026q2'
        )
          AND account_name = 'abccbaq'
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND quantity = 100
          AND lifecycle_kind = 'reprice_on_tick_change'
          AND old_tick = 0.01
          AND new_tick = 0.001
          AND max_reprices = 1
          AND status = 'DISABLED'
    ) <> 3 THEN
        RAISE EXCEPTION 'YUM/ICE/CI profile verification failed';
    END IF;

    IF (
        SELECT count(*)
        FROM resolution_profile_schedules
        WHERE schedule_key IN (
            'schedule:earnings-yum-2026q2',
            'schedule:earnings-ice-2026q2',
            'schedule:earnings-ci-2026q2'
        )
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at =
              TIMESTAMPTZ '2026-07-30 09:45:00+00'
          AND activate_at =
              TIMESTAMPTZ '2026-07-30 10:00:00+00'
          AND metadata ->> 'armed_for_live' = 'false'
    ) <> 3 THEN
        RAISE EXCEPTION 'YUM/ICE/CI schedule verification failed';
    END IF;

    SELECT sum(
        quantity * greatest(yes_desired_price, no_desired_price)
    )
    INTO reviewed_notional
    FROM resolution_execution_profiles
    WHERE profile_key IN (
        'earnings-yum-2026q2',
        'earnings-ice-2026q2',
        'earnings-ci-2026q2'
    );

    IF reviewed_notional <> 299.7 OR reviewed_notional > 1000 THEN
        RAISE EXCEPTION 'YUM/ICE/CI reviewed notional is invalid';
    END IF;
END
$verify$;

COMMIT;
