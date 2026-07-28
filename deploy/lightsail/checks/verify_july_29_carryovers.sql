BEGIN TRANSACTION READ ONLY;

DO $verification$
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
          AND scheduled_release_at =
              TIMESTAMPTZ '2026-08-05 20:05:00+00'
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
          AND status = 'DISABLED'
          AND quantity = 100
          AND yes_desired_price = 0.999
          AND no_desired_price = 0.999
    ) THEN
        RAISE EXCEPTION 'WWD disabled profile mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM resolution_profile_schedules
        WHERE profile_key = 'earnings-wwd-2026q3'
          AND automation_mode = 'AUTO_PREFLIGHT'
          AND state = 'PENDING'
          AND activate_at = TIMESTAMPTZ '2026-07-29 18:00:00+00'
          AND deactivate_at = TIMESTAMPTZ '2026-07-30 02:00:00+00'
          AND metadata ->> 'live_block' = 'POST_MARKET'
          AND metadata ->> 'block_id' = '2026-07-29-post-market'
    ) THEN
        RAISE EXCEPTION 'WWD AUTO_PREFLIGHT schedule mismatch';
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

ROLLBACK;
