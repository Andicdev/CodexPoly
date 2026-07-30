BEGIN;

CREATE TABLE IF NOT EXISTS neg_risk_stream_sessions (
    session_id uuid PRIMARY KEY,
    event_id text NOT NULL,
    event_slug text NOT NULL,
    mode text NOT NULL DEFAULT 'SHADOW',
    status text NOT NULL DEFAULT 'STARTING',
    market_count integer NOT NULL,
    asset_count integer NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ready_at timestamptz,
    ended_at timestamptz,
    last_message_at timestamptz,
    message_count bigint NOT NULL DEFAULT 0,
    update_count bigint NOT NULL DEFAULT 0,
    reconnect_count integer NOT NULL DEFAULT 0,
    reason_code text,
    live_orders_enabled boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT neg_risk_stream_sessions_mode_check
        CHECK (mode = 'SHADOW'),
    CONSTRAINT neg_risk_stream_sessions_status_check
        CHECK (
            status IN (
                'STARTING',
                'READY',
                'RECONNECTING',
                'STOPPED',
                'ERROR',
                'HALTED'
            )
        ),
    CONSTRAINT neg_risk_stream_sessions_counts_check
        CHECK (market_count >= 2 AND asset_count >= 4),
    CONSTRAINT neg_risk_stream_sessions_message_count_check
        CHECK (message_count >= 0 AND update_count >= 0),
    CONSTRAINT neg_risk_stream_sessions_reconnect_count_check
        CHECK (reconnect_count >= 0),
    CONSTRAINT neg_risk_stream_sessions_live_disabled_check
        CHECK (live_orders_enabled = false),
    CONSTRAINT neg_risk_stream_sessions_metadata_check
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_neg_risk_stream_sessions_event_started
    ON neg_risk_stream_sessions (event_slug, started_at DESC);

CREATE TABLE IF NOT EXISTS neg_risk_stream_messages (
    id bigserial PRIMARY KEY,
    session_id uuid NOT NULL
        REFERENCES neg_risk_stream_sessions(session_id),
    connection_epoch integer NOT NULL,
    message_sequence bigint NOT NULL,
    received_at timestamptz NOT NULL,
    server_timestamp_min_ms bigint,
    server_timestamp_max_ms bigint,
    event_types jsonb NOT NULL,
    affected_asset_ids jsonb NOT NULL,
    payload jsonb NOT NULL,
    payload_bytes integer NOT NULL,
    event_count integer NOT NULL,
    CONSTRAINT ux_neg_risk_stream_messages_sequence
        UNIQUE (
            session_id,
            connection_epoch,
            message_sequence
        ),
    CONSTRAINT neg_risk_stream_messages_epoch_check
        CHECK (connection_epoch > 0),
    CONSTRAINT neg_risk_stream_messages_sequence_check
        CHECK (message_sequence > 0),
    CONSTRAINT neg_risk_stream_messages_timestamp_check
        CHECK (
            server_timestamp_min_ms IS NULL
            OR server_timestamp_min_ms >= 1000000000000
        ),
    CONSTRAINT neg_risk_stream_messages_timestamp_order_check
        CHECK (
            server_timestamp_min_ms IS NULL
            OR server_timestamp_max_ms IS NULL
            OR server_timestamp_max_ms >= server_timestamp_min_ms
        ),
    CONSTRAINT neg_risk_stream_messages_event_types_check
        CHECK (jsonb_typeof(event_types) = 'array'),
    CONSTRAINT neg_risk_stream_messages_assets_check
        CHECK (jsonb_typeof(affected_asset_ids) = 'array'),
    CONSTRAINT neg_risk_stream_messages_payload_check
        CHECK (jsonb_typeof(payload) IN ('object', 'array')),
    CONSTRAINT neg_risk_stream_messages_size_check
        CHECK (payload_bytes > 0 AND payload_bytes <= 8388608),
    CONSTRAINT neg_risk_stream_messages_event_count_check
        CHECK (event_count > 0)
);

CREATE INDEX IF NOT EXISTS ix_neg_risk_stream_messages_received
    ON neg_risk_stream_messages (session_id, received_at);

CREATE INDEX IF NOT EXISTS ix_neg_risk_stream_messages_payload
    ON neg_risk_stream_messages USING gin (payload jsonb_path_ops);

CREATE TABLE IF NOT EXISTS neg_risk_route_observations (
    id bigserial PRIMARY KEY,
    session_id uuid NOT NULL
        REFERENCES neg_risk_stream_sessions(session_id),
    stream_message_id bigint NOT NULL
        REFERENCES neg_risk_stream_messages(id),
    connection_epoch integer NOT NULL,
    observed_at timestamptz NOT NULL,
    trigger_event_type text NOT NULL,
    maker_condition_id text NOT NULL,
    maker_question text NOT NULL,
    quantity numeric(38, 18) NOT NULL,
    available boolean NOT NULL,
    reason_code text,
    maker_price numeric(20, 10),
    queue_ahead numeric(38, 18),
    gross_collateral numeric(38, 18),
    conservative_taker_fees numeric(38, 18),
    base_profit numeric(38, 18),
    base_edge_per_share numeric(38, 18),
    estimated_maker_rebate numeric(38, 18),
    profit_with_rebate numeric(38, 18),
    edge_with_rebate_per_share numeric(38, 18),
    reward_top_of_book_candidate boolean,
    hedge_legs jsonb NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT ux_neg_risk_route_observations_route
        UNIQUE (
            stream_message_id,
            maker_condition_id,
            quantity
        ),
    CONSTRAINT neg_risk_route_observations_epoch_check
        CHECK (connection_epoch > 0),
    CONSTRAINT neg_risk_route_observations_condition_check
        CHECK (
            maker_condition_id
            ~ '^0x[0-9a-f]{64}$'
        ),
    CONSTRAINT neg_risk_route_observations_quantity_check
        CHECK (quantity > 0),
    CONSTRAINT neg_risk_route_observations_available_check
        CHECK (
            (
                available
                AND reason_code IS NULL
                AND maker_price IS NOT NULL
                AND queue_ahead IS NOT NULL
                AND gross_collateral IS NOT NULL
                AND conservative_taker_fees IS NOT NULL
                AND base_profit IS NOT NULL
                AND base_edge_per_share IS NOT NULL
                AND estimated_maker_rebate IS NOT NULL
                AND profit_with_rebate IS NOT NULL
                AND edge_with_rebate_per_share IS NOT NULL
            )
            OR (
                NOT available
                AND reason_code IS NOT NULL
                AND maker_price IS NULL
                AND queue_ahead IS NULL
                AND gross_collateral IS NULL
                AND conservative_taker_fees IS NULL
                AND base_profit IS NULL
                AND base_edge_per_share IS NULL
                AND estimated_maker_rebate IS NULL
                AND profit_with_rebate IS NULL
                AND edge_with_rebate_per_share IS NULL
            )
        ),
    CONSTRAINT neg_risk_route_observations_hedges_check
        CHECK (jsonb_typeof(hedge_legs) = 'array')
);

CREATE INDEX IF NOT EXISTS ix_neg_risk_route_observations_edge
    ON neg_risk_route_observations (
        maker_condition_id,
        quantity,
        observed_at DESC
    )
    WHERE available;

CREATE INDEX IF NOT EXISTS ix_neg_risk_route_observations_profitable
    ON neg_risk_route_observations (
        observed_at DESC,
        base_edge_per_share DESC
    )
    WHERE available AND base_profit > 0;

CREATE OR REPLACE FUNCTION neg_risk_reject_append_only_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$function$;

DO $block$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid = 'neg_risk_stream_messages'::regclass
          AND tgname =
              'trg_neg_risk_stream_messages_append_only'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_neg_risk_stream_messages_append_only
        BEFORE UPDATE OR DELETE ON neg_risk_stream_messages
        FOR EACH ROW
        EXECUTE FUNCTION neg_risk_reject_append_only_mutation();
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid =
              'neg_risk_route_observations'::regclass
          AND tgname =
              'trg_neg_risk_route_observations_append_only'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_neg_risk_route_observations_append_only
        BEFORE UPDATE OR DELETE ON neg_risk_route_observations
        FOR EACH ROW
        EXECUTE FUNCTION neg_risk_reject_append_only_mutation();
    END IF;
END;
$block$;

COMMIT;
