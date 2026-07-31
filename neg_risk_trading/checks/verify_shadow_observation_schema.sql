DO $block$
DECLARE
    invalid_session_count bigint;
BEGIN
    IF to_regclass('neg_risk_stream_sessions') IS NULL
       OR to_regclass('neg_risk_stream_messages') IS NULL
       OR to_regclass('neg_risk_route_observations') IS NULL
       OR to_regclass('neg_risk_stream_anomalies') IS NULL
    THEN
        RAISE EXCEPTION
            'neg-risk shadow observation tables are incomplete';
    END IF;

    IF (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_stream_sessions'
    ) <> 17
    OR (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_stream_messages'
    ) <> 12
    OR (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_route_observations'
    ) <> 23
    OR (
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'neg_risk_stream_anomalies'
    ) <> 6
    THEN
        RAISE EXCEPTION
            'neg-risk shadow observation columns are incomplete';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = 'neg_risk_stream_messages'::regclass
          AND tgname =
              'trg_neg_risk_stream_messages_append_only'
          AND NOT tgisinternal
    )
    OR NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid =
              'neg_risk_route_observations'::regclass
          AND tgname =
              'trg_neg_risk_route_observations_append_only'
          AND NOT tgisinternal
    )
    OR NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid =
              'neg_risk_stream_anomalies'::regclass
          AND tgname =
              'trg_neg_risk_stream_anomalies_append_only'
          AND NOT tgisinternal
    )
    THEN
        RAISE EXCEPTION
            'neg-risk append-only triggers are incomplete';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM neg_risk_route_observations
        WHERE route_direction NOT IN (
            'MAKER_BUY',
            'MAKER_SELL'
        )
    ) THEN
        RAISE EXCEPTION
            'neg-risk route direction invariant is violated';
    END IF;

    SELECT count(*)
    INTO invalid_session_count
    FROM neg_risk_stream_sessions
    WHERE mode <> 'SHADOW'
       OR live_orders_enabled;

    IF invalid_session_count <> 0 THEN
        RAISE EXCEPTION
            'neg-risk live-disabled invariant is violated';
    END IF;
END;
$block$;
