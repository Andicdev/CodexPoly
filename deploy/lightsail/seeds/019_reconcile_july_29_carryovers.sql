-- Reconcile releases whose public market date differs from the issuer's
-- confirmed schedule. WWD receives a disabled AUTO_PREFLIGHT schedule; ETSY
-- remains research-only and receives no executable profile or schedule.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

-- If an August 5 Etsy catalog row already exists, retain the old discovery as
-- a cancelled historical row. Otherwise move the existing discovery forward.
UPDATE earnings_release_catalog
SET
    schedule_status = 'CANCELLED',
    notes = (
        'Superseded: Etsy officially scheduled Q2 2026 results for '
        '2026-08-05 after market close.'
    ),
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'ETSY:2026-07-29'
  AND EXISTS (
      SELECT 1
      FROM earnings_release_catalog
      WHERE event_key = 'ETSY:2026-08-05'
  );

UPDATE earnings_release_catalog
SET
    event_key = 'ETSY:2026-08-05',
    release_date = DATE '2026-08-05',
    market_session = 'POST_MARKET',
    scheduled_release_at = TIMESTAMPTZ '2026-08-05 20:05:00+00',
    conference_call_at = TIMESTAMPTZ '2026-08-06 12:30:00+00',
    schedule_status = 'CONFIRMED',
    schedule_source_url = (
        'https://investors.etsy.com/news-events/press-releases/detail/223/'
        'etsy-to-announce-second-quarter-2026-financial-results-on-'
        'august-5-2026'
    ),
    integration_status = 'RESEARCH_PENDING',
    notes = (
        'Official issuer schedule supersedes the July 29 Polymarket '
        'discovery; parser and executable profile remain pending.'
    ),
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'ETSY:2026-07-29'
  AND NOT EXISTS (
      SELECT 1
      FROM earnings_release_catalog
      WHERE event_key = 'ETSY:2026-08-05'
  );

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
    'ETSY:2026-08-05',
    'ETSY',
    DATE '2026-08-05',
    'POST_MARKET',
    TIMESTAMPTZ '2026-08-05 20:05:00+00',
    TIMESTAMPTZ '2026-08-06 12:30:00+00',
    'CONFIRMED',
    (
        'https://investors.etsy.com/news-events/press-releases/detail/223/'
        'etsy-to-announce-second-quarter-2026-financial-results-on-'
        'august-5-2026'
    ),
    'RESEARCH_PENDING',
    'UNKNOWN',
    '{
        "comparison_op": ">",
        "market_basis": "gaap_eps",
        "primary_basis": "diluted",
        "fallback_basis": "basic",
        "strike": "0.72"
    }'::jsonb,
    '[
        {
            "delivery": "websocket",
            "provider": "sec_api",
            "status": "needs_parser"
        },
        {
            "delivery": "polling",
            "provider": "sec",
            "status": "needs_parser"
        }
    ]'::jsonb,
    (
        'Official issuer schedule supersedes the July 29 Polymarket '
        'discovery; parser and executable profile remain pending.'
    ),
    now()
)
ON CONFLICT (ticker, release_date) DO UPDATE
SET
    event_key = EXCLUDED.event_key,
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
    'WWD:2026-07-29',
    'WWD',
    DATE '2026-07-29',
    'POST_MARKET',
    TIMESTAMPTZ '2026-07-29 20:00:00+00',
    TIMESTAMPTZ '2026-07-29 21:00:00+00',
    'CONFIRMED',
    (
        'https://ir.woodward.com/news/news-details/2026/'
        'Woodward-Schedules-Fiscal-2026-Third-Quarter-Earnings-Release-'
        'and-Conference-Call/default.aspx'
    ),
    'PARSER_ONLY',
    'FULL_HTML',
    '{
        "comparison_op": ">",
        "market_basis": "gaap_eps",
        "primary_basis": "diluted",
        "fallback_basis": "basic",
        "reported": ["gaap_eps", "adjusted_eps"],
        "strike": "2.42"
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
            "status": "available"
        },
        {
            "delivery": "wordpress_rest",
            "provider": "company_ir",
            "status": "verified"
        },
        {
            "delivery": "rss",
            "provider": "globenewswire",
            "status": "verified"
        }
    ]'::jsonb,
    (
        'Carryover confirmed by Woodward IR for July 29 at '
        'approximately 16:00 ET; parser and two public transports exist.'
    ),
    now()
)
ON CONFLICT (ticker, release_date) DO UPDATE
SET
    event_key = EXCLUDED.event_key,
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

UPDATE resolution_execution_profiles AS profile
SET
    quantity = 100,
    prepare_from = TIMESTAMPTZ '2026-07-29 18:00:00+00',
    expires_at = TIMESTAMPTZ '2026-07-30 02:00:00+00',
    updated_at = now()
WHERE profile.profile_key = 'earnings-wwd-2026q3'
  AND profile.scope_id = 'earnings:WWD:2026Q3'
  AND profile.status = 'DISABLED'
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_execution_claims AS claim
      WHERE claim.scope_id = profile.scope_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM resolution_order_groups AS order_group
      WHERE order_group.account_name = profile.account_name
        AND order_group.condition_id = profile.condition_id
        AND order_group.status IN ('ACTIVE', 'REPRICING')
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
VALUES (
    'schedule:earnings-wwd-2026q3',
    'earnings-wwd-2026q3',
    'AUTO_PREFLIGHT',
    TIMESTAMPTZ '2026-07-29 17:45:00+00',
    TIMESTAMPTZ '2026-07-29 18:00:00+00',
    TIMESTAMPTZ '2026-07-30 02:00:00+00',
    '{
        "seed": "019_reconcile_july_29_carryovers",
        "preflight_lead_minutes": 15,
        "live_block": "POST_MARKET",
        "block_id": "2026-07-29-post-market"
    }'::jsonb,
    'PENDING'
)
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
    wwd_notional numeric;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM earnings_release_catalog
        WHERE event_key = 'ETSY:2026-08-05'
          AND ticker = 'ETSY'
          AND release_date = DATE '2026-08-05'
          AND market_session = 'POST_MARKET'
          AND schedule_status = 'CONFIRMED'
          AND integration_status = 'RESEARCH_PENDING'
    ) THEN
        RAISE EXCEPTION 'Etsy official schedule reconciliation failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE scope_id = 'earnings:ETSY:2026Q2'
    ) THEN
        RAISE EXCEPTION 'Etsy reconciliation must not create a profile';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM earnings_release_catalog
        WHERE event_key = 'WWD:2026-07-29'
          AND ticker = 'WWD'
          AND release_date = DATE '2026-07-29'
          AND market_session = 'POST_MARKET'
          AND scheduled_release_at =
              TIMESTAMPTZ '2026-07-29 20:00:00+00'
          AND integration_status = 'PARSER_ONLY'
    ) THEN
        RAISE EXCEPTION 'WWD carryover catalog mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE profile_key = 'earnings-wwd-2026q3'
          AND scope_id = 'earnings:WWD:2026Q3'
          AND status = 'DISABLED'
          AND quantity = 100
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
          AND prepare_from = TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND expires_at = TIMESTAMPTZ '2026-07-30 02:00:00+00'
    ) THEN
        RAISE EXCEPTION 'WWD disabled profile mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_schedules
        WHERE schedule_key = 'schedule:earnings-wwd-2026q3'
          AND profile_key = 'earnings-wwd-2026q3'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND preflight_at = TIMESTAMPTZ '2026-07-29 17:45:00+00'
          AND activate_at = TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND deactivate_at = TIMESTAMPTZ '2026-07-30 02:00:00+00'
          AND metadata ->> 'block_id' = '2026-07-29-post-market'
    ) THEN
        RAISE EXCEPTION 'WWD AUTO_PREFLIGHT schedule mismatch';
    END IF;

    SELECT quantity * GREATEST(yes_desired_price, no_desired_price)
    INTO wwd_notional
    FROM resolution_execution_profiles
    WHERE profile_key = 'earnings-wwd-2026q3';

    IF wwd_notional > 100 THEN
        RAISE EXCEPTION 'WWD reviewed notional exceeds 100';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM resolution_execution_claims
        WHERE scope_id = 'earnings:WWD:2026Q3'
    ) THEN
        RAISE EXCEPTION 'WWD execution claim must not exist';
    END IF;
END
$verification$;

COMMIT;
