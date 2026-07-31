BEGIN;

ALTER TABLE neg_risk_route_observations
ADD COLUMN IF NOT EXISTS route_direction text
    NOT NULL DEFAULT 'MAKER_SELL';

DO $block$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid =
              'neg_risk_route_observations'::regclass
          AND conname =
              'neg_risk_route_observations_direction_check'
    ) THEN
        ALTER TABLE neg_risk_route_observations
        ADD CONSTRAINT
            neg_risk_route_observations_direction_check
        CHECK (
            route_direction IN ('MAKER_BUY', 'MAKER_SELL')
        );
    END IF;
END;
$block$;

ALTER TABLE neg_risk_route_observations
DROP CONSTRAINT IF EXISTS
    ux_neg_risk_route_observations_route;

ALTER TABLE neg_risk_route_observations
ADD CONSTRAINT ux_neg_risk_route_observations_route
UNIQUE (
    stream_message_id,
    route_direction,
    maker_condition_id,
    quantity
);

CREATE INDEX IF NOT EXISTS
    ix_neg_risk_route_observations_direction_edge
ON neg_risk_route_observations (
    route_direction,
    maker_condition_id,
    quantity,
    observed_at DESC,
    base_edge_per_share DESC
)
WHERE available;

CREATE TABLE IF NOT EXISTS neg_risk_stream_anomalies (
    id bigserial PRIMARY KEY,
    session_id uuid NOT NULL
        REFERENCES neg_risk_stream_sessions(session_id),
    connection_epoch integer NOT NULL,
    observed_at timestamptz NOT NULL,
    reason_code text NOT NULL,
    diagnostics jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT neg_risk_stream_anomalies_epoch_check
        CHECK (connection_epoch > 0),
    CONSTRAINT neg_risk_stream_anomalies_reason_check
        CHECK (length(reason_code) BETWEEN 1 AND 160),
    CONSTRAINT neg_risk_stream_anomalies_diagnostics_check
        CHECK (jsonb_typeof(diagnostics) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_neg_risk_stream_anomalies_session
ON neg_risk_stream_anomalies (
    session_id,
    observed_at DESC,
    reason_code
);

DO $block$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgrelid =
              'neg_risk_stream_anomalies'::regclass
          AND tgname =
              'trg_neg_risk_stream_anomalies_append_only'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER
            trg_neg_risk_stream_anomalies_append_only
        BEFORE UPDATE OR DELETE ON neg_risk_stream_anomalies
        FOR EACH ROW
        EXECUTE FUNCTION neg_risk_reject_append_only_mutation();
    END IF;
END;
$block$;

COMMIT;
