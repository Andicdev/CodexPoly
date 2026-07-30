-- Record the issuer-confirmed TDAY date. This informational seed creates no
-- rule, execution profile, schedule, claim, or order.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

UPDATE earnings_release_catalog
SET
    schedule_status = 'CANCELLED',
    notes = (
        'Superseded: USA TODAY Co. officially scheduled Q2 2026 '
        'results for 2026-08-06 before market open.'
    ),
    verified_at = now(),
    updated_at = now()
WHERE event_key = 'TDAY:2026-07-30';

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
    'TDAY:2026-08-06',
    'TDAY',
    DATE '2026-08-06',
    'PRE_MARKET',
    TIMESTAMPTZ '2026-08-06 11:30:00+00',
    TIMESTAMPTZ '2026-08-06 12:30:00+00',
    'CONFIRMED',
    'https://investors.usatodayco.com/press-releases',
    'RESEARCH_PENDING',
    'UNKNOWN',
    '{
        "comparison_op": ">",
        "market_basis": "gaap_eps",
        "polymarket_listed_date": "2026-07-30",
        "primary_basis": "diluted",
        "strike": "-0.02"
    }'::jsonb,
    '[
        {"delivery": "websocket", "provider": "sec_api", "status": "needs_parser"},
        {"delivery": "polling", "provider": "sec", "status": "needs_parser"},
        {"delivery": "polling", "provider": "company_ir", "status": "research_pending"},
        {"delivery": "rss", "provider": "businesswire", "status": "research_pending"}
    ]'::jsonb,
    (
        'Issuer announcement dated 2026-07-23 supersedes the '
        'July 30 Polymarket estimate. No executable profile exists.'
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

DO $verify$
BEGIN
    IF (
        SELECT count(*)
        FROM earnings_release_catalog
        WHERE event_key = 'TDAY:2026-08-06'
          AND ticker = 'TDAY'
          AND release_date = DATE '2026-08-06'
          AND market_session = 'PRE_MARKET'
          AND schedule_status = 'CONFIRMED'
          AND integration_status = 'RESEARCH_PENDING'
    ) <> 1 THEN
        RAISE EXCEPTION 'TDAY official catalog reconciliation failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM earnings_market_rules
        WHERE scope_id = 'earnings:TDAY:2026Q2'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_execution_profiles
        WHERE scope_id = 'earnings:TDAY:2026Q2'
    ) OR EXISTS (
        SELECT 1
        FROM resolution_profile_schedules
        WHERE profile_key = 'earnings-tday-2026q2'
    ) THEN
        RAISE EXCEPTION 'TDAY executable state must not exist';
    END IF;
END
$verify$;

COMMIT;
