-- Additive public account metadata for secret-backed trading accounts.
-- This migration intentionally does not alter or drop any legacy object.

CREATE TABLE IF NOT EXISTS trading_account_metadata (
    account_name text PRIMARY KEY,
    wallet_address text NOT NULL
        CHECK (
            wallet_address ~ '^0x[0-9A-Fa-f]{40}$'
        ),
    venue text NOT NULL DEFAULT 'polymarket_clob'
        CHECK (length(btrim(venue)) > 0),
    signature_type integer NOT NULL
        CHECK (signature_type BETWEEN 0 AND 3),
    is_active boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_trading_account_metadata_name_ci
    ON trading_account_metadata (lower(account_name));
