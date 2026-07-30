DO $block$
DECLARE
    latest_scan_id uuid;
    latest_completed_at timestamptz;
    latest_page_count integer;
    latest_gamma_market_count bigint;
    latest_neg_risk_market_count bigint;
    latest_event_count bigint;
    latest_ready_event_count bigint;
    latest_skipped_market_count bigint;
    listed_event_count bigint;
    listed_market_count bigint;
BEGIN
    SELECT
        scan_id,
        completed_at,
        page_count,
        gamma_market_count,
        neg_risk_market_count,
        event_count,
        ready_event_count,
        skipped_market_count
    INTO
        latest_scan_id,
        latest_completed_at,
        latest_page_count,
        latest_gamma_market_count,
        latest_neg_risk_market_count,
        latest_event_count,
        latest_ready_event_count,
        latest_skipped_market_count
    FROM neg_risk_catalog_scans
    WHERE status = 'COMPLETE'
      AND mode = 'SHADOW'
      AND NOT live_orders_enabled
    ORDER BY completed_at DESC
    LIMIT 1;

    IF latest_scan_id IS NULL
       OR latest_completed_at < clock_timestamp() - interval '2 hours'
       OR latest_page_count < 1
       OR latest_gamma_market_count < 1
       OR latest_neg_risk_market_count < 1
       OR latest_event_count < 1
       OR latest_ready_event_count < 1
       OR latest_skipped_market_count <> 0
    THEN
        RAISE EXCEPTION
            'neg-risk staging catalog has no complete fresh scan';
    END IF;

    SELECT count(*)
    INTO listed_event_count
    FROM neg_risk_catalog_events_current
    WHERE is_listed
      AND last_seen_scan_id = latest_scan_id;

    SELECT count(*)
    INTO listed_market_count
    FROM neg_risk_catalog_markets_current
    WHERE is_listed
      AND last_seen_scan_id = latest_scan_id;

    IF listed_event_count <> latest_event_count
       OR listed_market_count < 2
    THEN
        RAISE EXCEPTION
            'neg-risk staging catalog current snapshot is incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM neg_risk_catalog_scan_events
        WHERE scan_id = latest_scan_id
    )
    OR EXISTS (
        SELECT 1
        FROM neg_risk_catalog_scan_markets
        WHERE scan_id = latest_scan_id
    )
    THEN
        RAISE EXCEPTION
            'neg-risk staging catalog promotion is incomplete';
    END IF;
END;
$block$;
