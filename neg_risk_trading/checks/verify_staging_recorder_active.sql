DO $block$
DECLARE
    latest_session_id uuid;
    latest_status text;
    latest_live_orders_enabled boolean;
    latest_message_count bigint;
    persisted_message_count bigint;
    persisted_route_count bigint;
    maker_buy_route_count bigint;
    maker_sell_route_count bigint;
    event_contract_version integer;
BEGIN
    SELECT
        session_id,
        status,
        live_orders_enabled,
        message_count,
        CASE
            WHEN metadata ? 'event_contract'
             AND jsonb_typeof(metadata -> 'event_contract')
                 = 'object'
            THEN (
                metadata -> 'event_contract' ->> 'version'
            )::integer
            ELSE NULL
        END
    INTO
        latest_session_id,
        latest_status,
        latest_live_orders_enabled,
        latest_message_count,
        event_contract_version
    FROM neg_risk_stream_sessions
    WHERE event_slug = 'fed-decision-in-september-762'
    ORDER BY started_at DESC
    LIMIT 1;

    IF latest_session_id IS NULL THEN
        RAISE EXCEPTION
            'neg-risk staging recorder has no session';
    END IF;

    IF latest_status <> 'READY'
       OR latest_live_orders_enabled
       OR latest_message_count < 1
       OR event_contract_version <> 1
    THEN
        RAISE EXCEPTION
            'neg-risk staging recorder is not ready';
    END IF;

    SELECT count(*)
    INTO persisted_message_count
    FROM neg_risk_stream_messages
    WHERE session_id = latest_session_id;

    SELECT count(*)
    INTO persisted_route_count
    FROM neg_risk_route_observations
    WHERE session_id = latest_session_id;

    SELECT
        count(*) FILTER (
            WHERE route_direction = 'MAKER_BUY'
        ),
        count(*) FILTER (
            WHERE route_direction = 'MAKER_SELL'
        )
    INTO
        maker_buy_route_count,
        maker_sell_route_count
    FROM neg_risk_route_observations
    WHERE session_id = latest_session_id;

    IF persisted_message_count < 1
       OR persisted_route_count < 1
       OR maker_buy_route_count < 1
       OR maker_sell_route_count < 1
    THEN
        RAISE EXCEPTION
            'neg-risk staging recorder has no observations';
    END IF;
END;
$block$;
