DO $block$
DECLARE
    invalid_scan_count bigint;
BEGIN
    IF to_regclass('neg_risk_catalog_scans') IS NULL
       OR to_regclass('neg_risk_catalog_scan_events') IS NULL
       OR to_regclass('neg_risk_catalog_scan_markets') IS NULL
       OR to_regclass('neg_risk_catalog_events_current') IS NULL
       OR to_regclass('neg_risk_catalog_markets_current') IS NULL
       OR to_regclass('neg_risk_catalog_ranked_events') IS NULL
       OR to_regclass('neg_risk_catalog_category_summary') IS NULL
    THEN
        RAISE EXCEPTION
            'neg-risk catalog schema is incomplete';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_catalog_events_current'
          AND column_name = 'launch_status'
    )
    OR NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_catalog_markets_current'
          AND column_name = 'fee_rate'
    )
    OR NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_catalog_markets_current'
          AND column_name = 'tick_size'
    )
    THEN
        RAISE EXCEPTION
            'neg-risk catalog columns are incomplete';
    END IF;

    SELECT count(*)
    INTO invalid_scan_count
    FROM neg_risk_catalog_scans
    WHERE mode <> 'SHADOW'
       OR live_orders_enabled;

    IF invalid_scan_count <> 0 THEN
        RAISE EXCEPTION
            'neg-risk catalog live-disabled invariant is violated';
    END IF;
END;
$block$;
