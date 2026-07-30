BEGIN;

CREATE TABLE IF NOT EXISTS neg_risk_catalog_scans (
    scan_id uuid PRIMARY KEY,
    mode text NOT NULL DEFAULT 'SHADOW',
    status text NOT NULL DEFAULT 'RUNNING',
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    page_count integer NOT NULL DEFAULT 0,
    gamma_market_count bigint NOT NULL DEFAULT 0,
    neg_risk_market_count bigint NOT NULL DEFAULT 0,
    event_count bigint NOT NULL DEFAULT 0,
    ready_event_count bigint NOT NULL DEFAULT 0,
    issue_count bigint NOT NULL DEFAULT 0,
    skipped_market_count bigint NOT NULL DEFAULT 0,
    duration_ms bigint,
    reason_code text,
    live_orders_enabled boolean NOT NULL DEFAULT false,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT neg_risk_catalog_scans_mode_check
        CHECK (mode = 'SHADOW'),
    CONSTRAINT neg_risk_catalog_scans_status_check
        CHECK (status IN ('RUNNING', 'COMPLETE', 'ERROR')),
    CONSTRAINT neg_risk_catalog_scans_counts_check
        CHECK (
            page_count >= 0
            AND gamma_market_count >= 0
            AND neg_risk_market_count >= 0
            AND event_count >= 0
            AND ready_event_count >= 0
            AND issue_count >= 0
            AND skipped_market_count >= 0
        ),
    CONSTRAINT neg_risk_catalog_scans_duration_check
        CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT neg_risk_catalog_scans_live_disabled_check
        CHECK (live_orders_enabled = false),
    CONSTRAINT neg_risk_catalog_scans_metadata_check
        CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_neg_risk_catalog_scans_started
    ON neg_risk_catalog_scans (started_at DESC);

CREATE TABLE IF NOT EXISTS neg_risk_catalog_scan_events (
    scan_id uuid NOT NULL
        REFERENCES neg_risk_catalog_scans(scan_id)
        ON DELETE CASCADE,
    event_id text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (scan_id, event_id),
    CONSTRAINT neg_risk_catalog_scan_events_payload_check
        CHECK (jsonb_typeof(payload) = 'object')
);

CREATE TABLE IF NOT EXISTS neg_risk_catalog_scan_markets (
    scan_id uuid NOT NULL
        REFERENCES neg_risk_catalog_scans(scan_id)
        ON DELETE CASCADE,
    market_id text NOT NULL,
    event_id text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (scan_id, market_id),
    CONSTRAINT neg_risk_catalog_scan_markets_payload_check
        CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX IF NOT EXISTS ix_neg_risk_catalog_scan_markets_event
    ON neg_risk_catalog_scan_markets (scan_id, event_id);

CREATE TABLE IF NOT EXISTS neg_risk_catalog_events_current (
    event_id text PRIMARY KEY,
    slug text NOT NULL,
    title text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    closed boolean NOT NULL DEFAULT false,
    archived boolean NOT NULL DEFAULT false,
    neg_risk boolean NOT NULL DEFAULT true,
    augmented boolean NOT NULL,
    enable_order_book boolean NOT NULL,
    end_date timestamptz,
    source_updated_at timestamptz,
    volume numeric(38, 18) NOT NULL DEFAULT 0,
    volume_24h numeric(38, 18) NOT NULL DEFAULT 0,
    volume_1wk numeric(38, 18) NOT NULL DEFAULT 0,
    volume_1mo numeric(38, 18) NOT NULL DEFAULT 0,
    volume_1yr numeric(38, 18) NOT NULL DEFAULT 0,
    liquidity numeric(38, 18) NOT NULL DEFAULT 0,
    open_interest numeric(38, 18) NOT NULL DEFAULT 0,
    tags jsonb NOT NULL DEFAULT '[]'::jsonb,
    market_count integer NOT NULL DEFAULT 0,
    accepting_market_count integer NOT NULL DEFAULT 0,
    metadata_complete boolean NOT NULL DEFAULT false,
    all_accepting_orders boolean NOT NULL DEFAULT false,
    all_books_enabled boolean NOT NULL DEFAULT false,
    primary_fee_category text NOT NULL DEFAULT 'unknown',
    fee_profile text NOT NULL DEFAULT 'INCOMPLETE',
    tick_profile text NOT NULL DEFAULT 'INCOMPLETE',
    has_explicit_other boolean NOT NULL DEFAULT false,
    has_reward_terms boolean NOT NULL DEFAULT false,
    tail_market_count integer NOT NULL DEFAULT 0,
    launch_status text NOT NULL DEFAULT 'REVIEW_REQUIRED',
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    missing_since timestamptz,
    is_listed boolean NOT NULL DEFAULT true,
    last_seen_scan_id uuid NOT NULL
        REFERENCES neg_risk_catalog_scans(scan_id),
    CONSTRAINT neg_risk_catalog_events_state_check
        CHECK (neg_risk),
    CONSTRAINT neg_risk_catalog_events_values_check
        CHECK (
            volume >= 0
            AND volume_24h >= 0
            AND volume_1wk >= 0
            AND volume_1mo >= 0
            AND volume_1yr >= 0
            AND liquidity >= 0
            AND open_interest >= 0
            AND market_count >= 0
            AND accepting_market_count >= 0
            AND tail_market_count >= 0
        ),
    CONSTRAINT neg_risk_catalog_events_tags_check
        CHECK (jsonb_typeof(tags) = 'array'),
    CONSTRAINT neg_risk_catalog_events_fee_profile_check
        CHECK (
            fee_profile IN (
                'INCOMPLETE',
                'FEE_FREE',
                'UNIFORM',
                'MIXED'
            )
        ),
    CONSTRAINT neg_risk_catalog_events_tick_profile_check
        CHECK (
            tick_profile IN (
                'INCOMPLETE',
                'UNIFORM_0.001',
                'UNIFORM_0.01',
                'UNIFORM_OTHER',
                'MIXED'
            )
        ),
    CONSTRAINT neg_risk_catalog_events_launch_status_check
        CHECK (
            launch_status IN (
                'READY_FOR_L2_REPLAY',
                'REVIEW_REQUIRED',
                'NOT_TRADABLE'
            )
        ),
    CONSTRAINT neg_risk_catalog_events_listing_check
        CHECK (
            (is_listed AND missing_since IS NULL)
            OR (NOT is_listed AND missing_since IS NOT NULL)
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_neg_risk_catalog_events_slug
    ON neg_risk_catalog_events_current (slug);

CREATE INDEX IF NOT EXISTS ix_neg_risk_catalog_events_rank
    ON neg_risk_catalog_events_current (
        is_listed,
        launch_status,
        volume_24h DESC,
        liquidity DESC
    );

CREATE TABLE IF NOT EXISTS neg_risk_catalog_markets_current (
    market_id text PRIMARY KEY,
    event_id text NOT NULL
        REFERENCES neg_risk_catalog_events_current(event_id),
    condition_id text NOT NULL,
    slug text NOT NULL,
    question text NOT NULL,
    yes_token_id text,
    no_token_id text,
    active boolean NOT NULL DEFAULT true,
    closed boolean NOT NULL DEFAULT false,
    archived boolean NOT NULL DEFAULT false,
    neg_risk boolean NOT NULL DEFAULT true,
    neg_risk_other boolean NOT NULL DEFAULT false,
    accepting_orders boolean NOT NULL,
    enable_order_book boolean NOT NULL,
    end_date timestamptz,
    source_updated_at timestamptz,
    volume numeric(38, 18) NOT NULL DEFAULT 0,
    volume_24h numeric(38, 18) NOT NULL DEFAULT 0,
    volume_1wk numeric(38, 18) NOT NULL DEFAULT 0,
    volume_1mo numeric(38, 18) NOT NULL DEFAULT 0,
    volume_1yr numeric(38, 18) NOT NULL DEFAULT 0,
    liquidity numeric(38, 18) NOT NULL DEFAULT 0,
    yes_price numeric(20, 10),
    no_price numeric(20, 10),
    best_bid numeric(20, 10),
    best_ask numeric(20, 10),
    spread numeric(20, 10),
    tick_size numeric(20, 10),
    minimum_order_size numeric(38, 18),
    fees_enabled boolean,
    fee_type text,
    fee_category text NOT NULL,
    fee_rate numeric(20, 10),
    fee_exponent integer,
    taker_only boolean,
    rebate_rate numeric(20, 10),
    rewards_minimum_size numeric(38, 18),
    rewards_maximum_spread numeric(20, 10),
    holding_rewards_enabled boolean NOT NULL DEFAULT false,
    metadata_complete boolean NOT NULL,
    issue_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    missing_since timestamptz,
    is_listed boolean NOT NULL DEFAULT true,
    last_seen_scan_id uuid NOT NULL
        REFERENCES neg_risk_catalog_scans(scan_id),
    CONSTRAINT neg_risk_catalog_markets_state_check
        CHECK (
            active
            AND NOT closed
            AND NOT archived
            AND neg_risk
        ),
    CONSTRAINT neg_risk_catalog_markets_values_check
        CHECK (
            volume >= 0
            AND volume_24h >= 0
            AND volume_1wk >= 0
            AND volume_1mo >= 0
            AND volume_1yr >= 0
            AND liquidity >= 0
            AND (
                yes_price IS NULL
                OR (yes_price >= 0 AND yes_price <= 1)
            )
            AND (
                no_price IS NULL
                OR (no_price >= 0 AND no_price <= 1)
            )
            AND (
                best_bid IS NULL
                OR (best_bid >= 0 AND best_bid <= 1)
            )
            AND (
                best_ask IS NULL
                OR (best_ask >= 0 AND best_ask <= 1)
            )
            AND (spread IS NULL OR spread >= 0)
            AND (tick_size IS NULL OR tick_size > 0)
            AND (
                minimum_order_size IS NULL
                OR minimum_order_size > 0
            )
            AND (fee_rate IS NULL OR fee_rate >= 0)
            AND (rebate_rate IS NULL OR rebate_rate >= 0)
            AND (
                rewards_minimum_size IS NULL
                OR rewards_minimum_size >= 0
            )
            AND (
                rewards_maximum_spread IS NULL
                OR rewards_maximum_spread >= 0
            )
        ),
    CONSTRAINT neg_risk_catalog_markets_issue_codes_check
        CHECK (jsonb_typeof(issue_codes) = 'array'),
    CONSTRAINT neg_risk_catalog_markets_listing_check
        CHECK (
            (is_listed AND missing_since IS NULL)
            OR (NOT is_listed AND missing_since IS NOT NULL)
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_neg_risk_catalog_markets_condition
    ON neg_risk_catalog_markets_current (condition_id)
    WHERE metadata_complete;

CREATE INDEX IF NOT EXISTS ix_neg_risk_catalog_markets_event
    ON neg_risk_catalog_markets_current (
        event_id,
        is_listed,
        volume_24h DESC
    );

CREATE OR REPLACE VIEW neg_risk_catalog_ranked_events AS
SELECT
    rank() OVER (
        ORDER BY
            CASE launch_status
                WHEN 'READY_FOR_L2_REPLAY' THEN 0
                WHEN 'REVIEW_REQUIRED' THEN 1
                ELSE 2
            END,
            volume_24h DESC,
            liquidity DESC,
            event_id
    ) AS global_rank,
    rank() OVER (
        PARTITION BY primary_fee_category
        ORDER BY
            CASE launch_status
                WHEN 'READY_FOR_L2_REPLAY' THEN 0
                WHEN 'REVIEW_REQUIRED' THEN 1
                ELSE 2
            END,
            volume_24h DESC,
            liquidity DESC,
            event_id
    ) AS category_rank,
    event_id,
    slug,
    title,
    primary_fee_category,
    fee_profile,
    tick_profile,
    launch_status,
    market_count,
    accepting_market_count,
    has_explicit_other,
    has_reward_terms,
    tail_market_count,
    volume,
    volume_24h,
    volume_1wk,
    liquidity,
    open_interest,
    end_date,
    source_updated_at,
    last_seen_at
FROM neg_risk_catalog_events_current
WHERE is_listed;

CREATE OR REPLACE VIEW neg_risk_catalog_category_summary AS
SELECT
    primary_fee_category,
    launch_status,
    count(*) AS event_count,
    sum(market_count) AS market_count,
    sum(volume_24h) AS volume_24h,
    sum(liquidity) AS liquidity,
    count(*) FILTER (
        WHERE tick_profile = 'MIXED'
    ) AS mixed_tick_event_count,
    count(*) FILTER (
        WHERE fee_profile = 'FEE_FREE'
    ) AS fee_free_event_count,
    count(*) FILTER (
        WHERE has_reward_terms
    ) AS reward_terms_event_count
FROM neg_risk_catalog_events_current
WHERE is_listed
GROUP BY primary_fee_category, launch_status;

COMMIT;
