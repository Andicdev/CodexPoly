-- Additive terminal classification for order-supervision outcomes.
-- Existing order-group statuses and rows remain unchanged.

CREATE TABLE IF NOT EXISTS resolution_order_group_terminal_audits (
    order_group_id text PRIMARY KEY
        REFERENCES resolution_order_groups(order_group_id)
        ON DELETE RESTRICT,
    event_id text NOT NULL,
    terminal_kind text NOT NULL
        CHECK (terminal_kind IN ('OVERFILLED')),
    target_quantity numeric(38, 18) NOT NULL
        CHECK (target_quantity > 0),
    filled_quantity numeric(38, 18) NOT NULL
        CHECK (filled_quantity > 0),
    excess_quantity numeric(38, 18) NOT NULL
        CHECK (excess_quantity > 0),
    detected_at timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (filled_quantity = target_quantity + excess_quantity)
);

CREATE INDEX IF NOT EXISTS
    ix_resolution_order_group_terminal_audits_kind
    ON resolution_order_group_terminal_audits (
        terminal_kind,
        detected_at
    );
