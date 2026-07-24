-- Additive remote-order observation history for OrderSupervisor.
-- This migration intentionally does not alter or drop any existing object.

CREATE TABLE IF NOT EXISTS resolution_order_observations (
    event_id text NOT NULL,
    order_group_id text NOT NULL,
    order_id text NOT NULL,
    phase text NOT NULL
        CHECK (phase IN ('PRE_CANCEL', 'POST_CANCEL', 'RECONCILE')),
    condition_id text NOT NULL,
    asset_id text NOT NULL,
    side text NOT NULL CHECK (side IN ('BUY', 'SELL')),
    remote_state text NOT NULL
        CHECK (
            remote_state IN (
                'OPEN',
                'CANCELLED',
                'FILLED',
                'UNKNOWN'
            )
        ),
    remote_status text NOT NULL,
    limit_price numeric(20, 10) NOT NULL
        CHECK (limit_price > 0 AND limit_price < 1),
    original_quantity numeric(38, 18) NOT NULL
        CHECK (original_quantity > 0),
    matched_quantity numeric(38, 18) NOT NULL
        CHECK (
            matched_quantity >= 0
            AND matched_quantity <= original_quantity
        ),
    remaining_quantity numeric(38, 18) NOT NULL
        CHECK (
            remaining_quantity >= 0
            AND remaining_quantity
                = original_quantity - matched_quantity
        ),
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        event_id,
        order_group_id,
        order_id,
        phase
    ),
    FOREIGN KEY (event_id, order_group_id)
        REFERENCES resolution_supervision_events (
            event_id,
            order_group_id
        )
        ON DELETE RESTRICT,
    FOREIGN KEY (order_group_id, order_id)
        REFERENCES resolution_order_group_orders (
            order_group_id,
            order_id
        )
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ix_resolution_order_observations_group_time
    ON resolution_order_observations (
        order_group_id,
        observed_at
    );
