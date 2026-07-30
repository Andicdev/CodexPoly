from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from neg_risk_trading.catalog import CatalogEvent, CatalogPage


_MIGRATION_PATH = (
    Path(__file__).resolve().parent
    / "migrations"
    / "002_add_catalog_scanner_tables.sql"
)

_SCHEMA_READY_SQL = """
SELECT
    to_regclass('neg_risk_catalog_scans') IS NOT NULL
        AS scans_table,
    to_regclass('neg_risk_catalog_scan_events') IS NOT NULL
        AS staged_events_table,
    to_regclass('neg_risk_catalog_scan_markets') IS NOT NULL
        AS staged_markets_table,
    to_regclass('neg_risk_catalog_events_current') IS NOT NULL
        AS events_table,
    to_regclass('neg_risk_catalog_markets_current') IS NOT NULL
        AS markets_table,
    to_regclass('neg_risk_catalog_ranked_events') IS NOT NULL
        AS ranked_view,
    to_regclass('neg_risk_catalog_category_summary') IS NOT NULL
        AS summary_view
""".strip()

_START_SCAN_SQL = """
INSERT INTO neg_risk_catalog_scans (
    scan_id,
    mode,
    status,
    started_at,
    live_orders_enabled,
    metadata
)
VALUES (
    :scan_id,
    'SHADOW',
    'RUNNING',
    :started_at,
    false,
    CAST(:metadata AS jsonb)
)
RETURNING scan_id
""".strip()

_RECOVER_RUNNING_SCANS_SQL = """
UPDATE neg_risk_catalog_scans
SET
    status = 'ERROR',
    completed_at = :started_at,
    reason_code = 'scanner_restarted'
WHERE status = 'RUNNING'
""".strip()

_DELETE_FAILED_STAGED_MARKETS_SQL = """
DELETE FROM neg_risk_catalog_scan_markets
WHERE scan_id IN (
    SELECT scan_id
    FROM neg_risk_catalog_scans
    WHERE status = 'ERROR'
)
""".strip()

_DELETE_FAILED_STAGED_EVENTS_SQL = """
DELETE FROM neg_risk_catalog_scan_events
WHERE scan_id IN (
    SELECT scan_id
    FROM neg_risk_catalog_scans
    WHERE status = 'ERROR'
)
""".strip()

_STAGE_EVENT_SQL = """
INSERT INTO neg_risk_catalog_scan_events (
    scan_id,
    event_id,
    payload
)
VALUES (
    :scan_id,
    :event_id,
    CAST(:payload AS jsonb)
)
ON CONFLICT (scan_id, event_id) DO UPDATE
SET payload = EXCLUDED.payload
""".strip()

_STAGE_MARKET_SQL = """
INSERT INTO neg_risk_catalog_scan_markets (
    scan_id,
    market_id,
    event_id,
    payload
)
VALUES (
    :scan_id,
    :market_id,
    :event_id,
    CAST(:payload AS jsonb)
)
ON CONFLICT (scan_id, market_id) DO UPDATE
SET
    event_id = EXCLUDED.event_id,
    payload = EXCLUDED.payload
""".strip()

_UPSERT_EVENT_SQL = """
INSERT INTO neg_risk_catalog_events_current (
    event_id,
    slug,
    title,
    active,
    closed,
    archived,
    neg_risk,
    augmented,
    enable_order_book,
    end_date,
    source_updated_at,
    volume,
    volume_24h,
    volume_1wk,
    volume_1mo,
    volume_1yr,
    liquidity,
    open_interest,
    tags,
    first_seen_at,
    last_seen_at,
    missing_since,
    is_listed,
    last_seen_scan_id
)
VALUES (
    :event_id,
    :slug,
    :title,
    (staged.payload ->> 'active')::boolean,
    (staged.payload ->> 'closed')::boolean,
    (staged.payload ->> 'archived')::boolean,
    true,
    :augmented,
    :enable_order_book,
    :end_date,
    :source_updated_at,
    :volume,
    :volume_24h,
    :volume_1wk,
    :volume_1mo,
    :volume_1yr,
    :liquidity,
    :open_interest,
    CAST(:tags AS jsonb),
    :observed_at,
    :observed_at,
    NULL,
    true,
    :scan_id
)
ON CONFLICT (event_id) DO UPDATE
SET
    slug = EXCLUDED.slug,
    title = EXCLUDED.title,
    active = EXCLUDED.active,
    closed = EXCLUDED.closed,
    archived = EXCLUDED.archived,
    neg_risk = true,
    augmented = EXCLUDED.augmented,
    enable_order_book = EXCLUDED.enable_order_book,
    end_date = EXCLUDED.end_date,
    source_updated_at = EXCLUDED.source_updated_at,
    volume = EXCLUDED.volume,
    volume_24h = EXCLUDED.volume_24h,
    volume_1wk = EXCLUDED.volume_1wk,
    volume_1mo = EXCLUDED.volume_1mo,
    volume_1yr = EXCLUDED.volume_1yr,
    liquidity = EXCLUDED.liquidity,
    open_interest = EXCLUDED.open_interest,
    tags = CASE
        WHEN jsonb_array_length(EXCLUDED.tags) > 0
        THEN EXCLUDED.tags
        ELSE neg_risk_catalog_events_current.tags
    END,
    last_seen_at = EXCLUDED.last_seen_at,
    missing_since = NULL,
    is_listed = true,
    last_seen_scan_id = EXCLUDED.last_seen_scan_id
""".strip()

_PROMOTE_EVENTS_SQL = """
INSERT INTO neg_risk_catalog_events_current (
    event_id,
    slug,
    title,
    active,
    closed,
    archived,
    neg_risk,
    augmented,
    enable_order_book,
    end_date,
    source_updated_at,
    volume,
    volume_24h,
    volume_1wk,
    volume_1mo,
    volume_1yr,
    liquidity,
    open_interest,
    tags,
    first_seen_at,
    last_seen_at,
    missing_since,
    is_listed,
    last_seen_scan_id
)
SELECT
    staged.event_id,
    staged.payload ->> 'slug',
    staged.payload ->> 'title',
    (staged.payload ->> 'active')::boolean,
    (staged.payload ->> 'closed')::boolean,
    (staged.payload ->> 'archived')::boolean,
    true,
    (staged.payload ->> 'augmented')::boolean,
    (staged.payload ->> 'enable_order_book')::boolean,
    (staged.payload ->> 'end_date')::timestamptz,
    (staged.payload ->> 'source_updated_at')::timestamptz,
    (staged.payload ->> 'volume')::numeric,
    (staged.payload ->> 'volume_24h')::numeric,
    (staged.payload ->> 'volume_1wk')::numeric,
    (staged.payload ->> 'volume_1mo')::numeric,
    (staged.payload ->> 'volume_1yr')::numeric,
    (staged.payload ->> 'liquidity')::numeric,
    (staged.payload ->> 'open_interest')::numeric,
    staged.payload -> 'tags',
    (staged.payload ->> 'observed_at')::timestamptz,
    (staged.payload ->> 'observed_at')::timestamptz,
    NULL,
    true,
    staged.scan_id
FROM neg_risk_catalog_scan_events AS staged
WHERE staged.scan_id = :scan_id
ON CONFLICT (event_id) DO UPDATE
SET
    slug = EXCLUDED.slug,
    title = EXCLUDED.title,
    active = EXCLUDED.active,
    closed = EXCLUDED.closed,
    archived = EXCLUDED.archived,
    neg_risk = true,
    augmented = EXCLUDED.augmented,
    enable_order_book = EXCLUDED.enable_order_book,
    end_date = EXCLUDED.end_date,
    source_updated_at = EXCLUDED.source_updated_at,
    volume = EXCLUDED.volume,
    volume_24h = EXCLUDED.volume_24h,
    volume_1wk = EXCLUDED.volume_1wk,
    volume_1mo = EXCLUDED.volume_1mo,
    volume_1yr = EXCLUDED.volume_1yr,
    liquidity = EXCLUDED.liquidity,
    open_interest = EXCLUDED.open_interest,
    tags = CASE
        WHEN jsonb_array_length(EXCLUDED.tags) > 0
        THEN EXCLUDED.tags
        ELSE neg_risk_catalog_events_current.tags
    END,
    last_seen_at = EXCLUDED.last_seen_at,
    missing_since = NULL,
    is_listed = true,
    last_seen_scan_id = EXCLUDED.last_seen_scan_id
""".strip()

_PROMOTE_MARKETS_SQL = """
INSERT INTO neg_risk_catalog_markets_current (
    market_id,
    event_id,
    condition_id,
    slug,
    question,
    yes_token_id,
    no_token_id,
    active,
    closed,
    archived,
    neg_risk,
    neg_risk_other,
    accepting_orders,
    enable_order_book,
    end_date,
    source_updated_at,
    volume,
    volume_24h,
    volume_1wk,
    volume_1mo,
    volume_1yr,
    liquidity,
    yes_price,
    no_price,
    best_bid,
    best_ask,
    spread,
    tick_size,
    minimum_order_size,
    fees_enabled,
    fee_type,
    fee_category,
    fee_rate,
    fee_exponent,
    taker_only,
    rebate_rate,
    rewards_minimum_size,
    rewards_maximum_spread,
    holding_rewards_enabled,
    metadata_complete,
    issue_codes,
    first_seen_at,
    last_seen_at,
    missing_since,
    is_listed,
    last_seen_scan_id
)
SELECT
    staged.market_id,
    staged.event_id,
    staged.payload ->> 'condition_id',
    staged.payload ->> 'slug',
    staged.payload ->> 'question',
    staged.payload ->> 'yes_token_id',
    staged.payload ->> 'no_token_id',
    true,
    false,
    false,
    true,
    (staged.payload ->> 'neg_risk_other')::boolean,
    (staged.payload ->> 'accepting_orders')::boolean,
    (staged.payload ->> 'enable_order_book')::boolean,
    (staged.payload ->> 'end_date')::timestamptz,
    (staged.payload ->> 'source_updated_at')::timestamptz,
    (staged.payload ->> 'volume')::numeric,
    (staged.payload ->> 'volume_24h')::numeric,
    (staged.payload ->> 'volume_1wk')::numeric,
    (staged.payload ->> 'volume_1mo')::numeric,
    (staged.payload ->> 'volume_1yr')::numeric,
    (staged.payload ->> 'liquidity')::numeric,
    (staged.payload ->> 'yes_price')::numeric,
    (staged.payload ->> 'no_price')::numeric,
    (staged.payload ->> 'best_bid')::numeric,
    (staged.payload ->> 'best_ask')::numeric,
    (staged.payload ->> 'spread')::numeric,
    (staged.payload ->> 'tick_size')::numeric,
    (staged.payload ->> 'minimum_order_size')::numeric,
    (staged.payload ->> 'fees_enabled')::boolean,
    staged.payload ->> 'fee_type',
    staged.payload ->> 'fee_category',
    (staged.payload ->> 'fee_rate')::numeric,
    (staged.payload ->> 'fee_exponent')::integer,
    (staged.payload ->> 'taker_only')::boolean,
    (staged.payload ->> 'rebate_rate')::numeric,
    (staged.payload ->> 'rewards_minimum_size')::numeric,
    (staged.payload ->> 'rewards_maximum_spread')::numeric,
    (
        staged.payload ->> 'holding_rewards_enabled'
    )::boolean,
    (staged.payload ->> 'metadata_complete')::boolean,
    staged.payload -> 'issue_codes',
    (staged.payload ->> 'observed_at')::timestamptz,
    (staged.payload ->> 'observed_at')::timestamptz,
    NULL,
    true,
    staged.scan_id
FROM neg_risk_catalog_scan_markets AS staged
WHERE staged.scan_id = :scan_id
ON CONFLICT (market_id) DO UPDATE
SET
    event_id = EXCLUDED.event_id,
    condition_id = EXCLUDED.condition_id,
    slug = EXCLUDED.slug,
    question = EXCLUDED.question,
    yes_token_id = EXCLUDED.yes_token_id,
    no_token_id = EXCLUDED.no_token_id,
    active = true,
    closed = false,
    archived = false,
    neg_risk = true,
    neg_risk_other = EXCLUDED.neg_risk_other,
    accepting_orders = EXCLUDED.accepting_orders,
    enable_order_book = EXCLUDED.enable_order_book,
    end_date = EXCLUDED.end_date,
    source_updated_at = EXCLUDED.source_updated_at,
    volume = EXCLUDED.volume,
    volume_24h = EXCLUDED.volume_24h,
    volume_1wk = EXCLUDED.volume_1wk,
    volume_1mo = EXCLUDED.volume_1mo,
    volume_1yr = EXCLUDED.volume_1yr,
    liquidity = EXCLUDED.liquidity,
    yes_price = EXCLUDED.yes_price,
    no_price = EXCLUDED.no_price,
    best_bid = EXCLUDED.best_bid,
    best_ask = EXCLUDED.best_ask,
    spread = EXCLUDED.spread,
    tick_size = EXCLUDED.tick_size,
    minimum_order_size = EXCLUDED.minimum_order_size,
    fees_enabled = EXCLUDED.fees_enabled,
    fee_type = EXCLUDED.fee_type,
    fee_category = EXCLUDED.fee_category,
    fee_rate = EXCLUDED.fee_rate,
    fee_exponent = EXCLUDED.fee_exponent,
    taker_only = EXCLUDED.taker_only,
    rebate_rate = EXCLUDED.rebate_rate,
    rewards_minimum_size = EXCLUDED.rewards_minimum_size,
    rewards_maximum_spread = EXCLUDED.rewards_maximum_spread,
    holding_rewards_enabled = EXCLUDED.holding_rewards_enabled,
    metadata_complete = EXCLUDED.metadata_complete,
    issue_codes = EXCLUDED.issue_codes,
    last_seen_at = EXCLUDED.last_seen_at,
    missing_since = NULL,
    is_listed = true,
    last_seen_scan_id = EXCLUDED.last_seen_scan_id
""".strip()

_DELETE_STAGED_MARKETS_SQL = """
DELETE FROM neg_risk_catalog_scan_markets
WHERE scan_id = :scan_id
""".strip()

_DELETE_STAGED_EVENTS_SQL = """
DELETE FROM neg_risk_catalog_scan_events
WHERE scan_id = :scan_id
""".strip()

_UPSERT_MARKET_SQL = """
INSERT INTO neg_risk_catalog_markets_current (
    market_id,
    event_id,
    condition_id,
    slug,
    question,
    yes_token_id,
    no_token_id,
    active,
    closed,
    archived,
    neg_risk,
    neg_risk_other,
    accepting_orders,
    enable_order_book,
    end_date,
    source_updated_at,
    volume,
    volume_24h,
    volume_1wk,
    volume_1mo,
    volume_1yr,
    liquidity,
    yes_price,
    no_price,
    best_bid,
    best_ask,
    spread,
    tick_size,
    minimum_order_size,
    fees_enabled,
    fee_type,
    fee_category,
    fee_rate,
    fee_exponent,
    taker_only,
    rebate_rate,
    rewards_minimum_size,
    rewards_maximum_spread,
    holding_rewards_enabled,
    metadata_complete,
    issue_codes,
    first_seen_at,
    last_seen_at,
    missing_since,
    is_listed,
    last_seen_scan_id
)
VALUES (
    :market_id,
    :event_id,
    :condition_id,
    :slug,
    :question,
    :yes_token_id,
    :no_token_id,
    true,
    false,
    false,
    true,
    :neg_risk_other,
    :accepting_orders,
    :enable_order_book,
    :end_date,
    :source_updated_at,
    :volume,
    :volume_24h,
    :volume_1wk,
    :volume_1mo,
    :volume_1yr,
    :liquidity,
    :yes_price,
    :no_price,
    :best_bid,
    :best_ask,
    :spread,
    :tick_size,
    :minimum_order_size,
    :fees_enabled,
    :fee_type,
    :fee_category,
    :fee_rate,
    :fee_exponent,
    :taker_only,
    :rebate_rate,
    :rewards_minimum_size,
    :rewards_maximum_spread,
    :holding_rewards_enabled,
    :metadata_complete,
    CAST(:issue_codes AS jsonb),
    :observed_at,
    :observed_at,
    NULL,
    true,
    :scan_id
)
ON CONFLICT (market_id) DO UPDATE
SET
    event_id = EXCLUDED.event_id,
    condition_id = EXCLUDED.condition_id,
    slug = EXCLUDED.slug,
    question = EXCLUDED.question,
    yes_token_id = EXCLUDED.yes_token_id,
    no_token_id = EXCLUDED.no_token_id,
    active = true,
    closed = false,
    archived = false,
    neg_risk = true,
    neg_risk_other = EXCLUDED.neg_risk_other,
    accepting_orders = EXCLUDED.accepting_orders,
    enable_order_book = EXCLUDED.enable_order_book,
    end_date = EXCLUDED.end_date,
    source_updated_at = EXCLUDED.source_updated_at,
    volume = EXCLUDED.volume,
    volume_24h = EXCLUDED.volume_24h,
    volume_1wk = EXCLUDED.volume_1wk,
    volume_1mo = EXCLUDED.volume_1mo,
    volume_1yr = EXCLUDED.volume_1yr,
    liquidity = EXCLUDED.liquidity,
    yes_price = EXCLUDED.yes_price,
    no_price = EXCLUDED.no_price,
    best_bid = EXCLUDED.best_bid,
    best_ask = EXCLUDED.best_ask,
    spread = EXCLUDED.spread,
    tick_size = EXCLUDED.tick_size,
    minimum_order_size = EXCLUDED.minimum_order_size,
    fees_enabled = EXCLUDED.fees_enabled,
    fee_type = EXCLUDED.fee_type,
    fee_category = EXCLUDED.fee_category,
    fee_rate = EXCLUDED.fee_rate,
    fee_exponent = EXCLUDED.fee_exponent,
    taker_only = EXCLUDED.taker_only,
    rebate_rate = EXCLUDED.rebate_rate,
    rewards_minimum_size = EXCLUDED.rewards_minimum_size,
    rewards_maximum_spread = EXCLUDED.rewards_maximum_spread,
    holding_rewards_enabled = EXCLUDED.holding_rewards_enabled,
    metadata_complete = EXCLUDED.metadata_complete,
    issue_codes = EXCLUDED.issue_codes,
    last_seen_at = EXCLUDED.last_seen_at,
    missing_since = NULL,
    is_listed = true,
    last_seen_scan_id = EXCLUDED.last_seen_scan_id
""".strip()

_TOUCH_SCAN_SQL = """
UPDATE neg_risk_catalog_scans
SET
    page_count = page_count + 1,
    gamma_market_count =
        gamma_market_count + :gamma_market_count,
    neg_risk_market_count =
        neg_risk_market_count + :neg_risk_market_count,
    issue_count = issue_count + :issue_count,
    skipped_market_count =
        skipped_market_count + :skipped_market_count
WHERE scan_id = :scan_id
  AND status = 'RUNNING'
""".strip()

_MARK_MISSING_MARKETS_SQL = """
UPDATE neg_risk_catalog_markets_current
SET
    is_listed = false,
    missing_since = :completed_at
WHERE is_listed
  AND last_seen_scan_id <> :scan_id
""".strip()

_MARK_MISSING_EVENTS_SQL = """
UPDATE neg_risk_catalog_events_current
SET
    is_listed = false,
    missing_since = :completed_at
WHERE is_listed
  AND last_seen_scan_id <> :scan_id
""".strip()

_FINALIZE_EVENTS_SQL = """
WITH stats AS (
    SELECT
        event_id,
        count(*)::integer AS market_count,
        count(*) FILTER (
            WHERE accepting_orders
        )::integer AS accepting_market_count,
        bool_and(metadata_complete) AS metadata_complete,
        bool_and(accepting_orders) AS all_accepting_orders,
        bool_and(enable_order_book) AS all_books_enabled,
        count(DISTINCT fee_category) AS fee_category_count,
        min(fee_category) AS single_fee_category,
        bool_and(
            fee_rate IS NOT NULL
            AND fee_exponent IS NOT NULL
            AND taker_only IS NOT NULL
            AND rebate_rate IS NOT NULL
        ) AS fee_metadata_complete,
        bool_and(fee_rate = 0) AS all_fee_free,
        count(
            DISTINCT (
                coalesce(fee_type, ''),
                fee_rate,
                fee_exponent,
                taker_only,
                rebate_rate
            )
        ) AS fee_schedule_count,
        bool_and(tick_size IS NOT NULL) AS tick_metadata_complete,
        count(DISTINCT tick_size) AS tick_count,
        min(tick_size) AS single_tick_size,
        bool_or(neg_risk_other) AS has_explicit_other,
        bool_or(
            rewards_minimum_size IS NOT NULL
            AND rewards_minimum_size > 0
            AND rewards_maximum_spread IS NOT NULL
            AND rewards_maximum_spread > 0
        ) AS has_reward_terms,
        count(*) FILTER (
            WHERE yes_price IS NOT NULL
              AND yes_price <= 0.01
        )::integer AS tail_market_count
    FROM neg_risk_catalog_markets_current
    WHERE is_listed
      AND last_seen_scan_id = :scan_id
    GROUP BY event_id
)
UPDATE neg_risk_catalog_events_current AS event
SET
    market_count = stats.market_count,
    accepting_market_count = stats.accepting_market_count,
    metadata_complete = stats.metadata_complete,
    all_accepting_orders = stats.all_accepting_orders,
    all_books_enabled = stats.all_books_enabled,
    primary_fee_category = CASE
        WHEN stats.fee_category_count = 1
        THEN stats.single_fee_category
        ELSE 'mixed'
    END,
    fee_profile = CASE
        WHEN NOT stats.fee_metadata_complete THEN 'INCOMPLETE'
        WHEN stats.all_fee_free THEN 'FEE_FREE'
        WHEN stats.fee_schedule_count = 1 THEN 'UNIFORM'
        ELSE 'MIXED'
    END,
    tick_profile = CASE
        WHEN NOT stats.tick_metadata_complete THEN 'INCOMPLETE'
        WHEN stats.tick_count > 1 THEN 'MIXED'
        WHEN stats.single_tick_size = 0.001 THEN 'UNIFORM_0.001'
        WHEN stats.single_tick_size = 0.01 THEN 'UNIFORM_0.01'
        ELSE 'UNIFORM_OTHER'
    END,
    has_explicit_other = stats.has_explicit_other,
    has_reward_terms = stats.has_reward_terms,
    tail_market_count = stats.tail_market_count,
    launch_status = CASE
        WHEN stats.market_count < 2
          OR NOT event.active
          OR event.closed
          OR event.archived
          OR NOT stats.all_accepting_orders
          OR NOT stats.all_books_enabled
          OR NOT event.enable_order_book
        THEN 'NOT_TRADABLE'
        WHEN event.augmented
          OR NOT stats.metadata_complete
          OR NOT stats.fee_metadata_complete
          OR NOT stats.tick_metadata_complete
          OR (
              SELECT skipped_market_count > 0
              FROM neg_risk_catalog_scans
              WHERE scan_id = :scan_id
          )
        THEN 'REVIEW_REQUIRED'
        ELSE 'READY_FOR_L2_REPLAY'
    END
FROM stats
WHERE event.event_id = stats.event_id
  AND event.last_seen_scan_id = :scan_id
""".strip()

_COMPLETE_SCAN_SQL = """
UPDATE neg_risk_catalog_scans
SET
    status = 'COMPLETE',
    completed_at = :completed_at,
    duration_ms = :duration_ms,
    event_count = (
        SELECT count(*)
        FROM neg_risk_catalog_events_current
        WHERE is_listed
          AND last_seen_scan_id = :scan_id
    ),
    ready_event_count = (
        SELECT count(*)
        FROM neg_risk_catalog_events_current
        WHERE is_listed
          AND last_seen_scan_id = :scan_id
          AND launch_status = 'READY_FOR_L2_REPLAY'
    )
WHERE scan_id = :scan_id
  AND status = 'RUNNING'
""".strip()

_FAIL_SCAN_SQL = """
UPDATE neg_risk_catalog_scans
SET
    status = 'ERROR',
    completed_at = :completed_at,
    duration_ms = :duration_ms,
    reason_code = :reason_code
WHERE scan_id = :scan_id
  AND status = 'RUNNING'
""".strip()


class CatalogRepositoryError(RuntimeError):
    """A value-safe catalog persistence failure."""


class SqlAlchemyCatalogRepository:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        session_factory: Callable[[], Any] | None = None,
        text_factory: Callable[[str], Any] | None = None,
    ):
        self._database_url = str(database_url or "").strip() or None
        self._session_factory = session_factory
        self._text_factory = text_factory
        self._engine: Any | None = None

    def migrate(self) -> None:
        session_factory, text_factory = self._dependencies()
        try:
            sql = _MIGRATION_PATH.read_text(encoding="utf-8")
            with session_factory() as session:
                session.execute(text_factory(sql))
                session.commit()
        except Exception as exc:
            raise CatalogRepositoryError(
                "Failed to migrate neg-risk catalog schema: "
                f"{type(exc).__name__}"
            ) from None

    def ensure_ready(self) -> None:
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                row = session.execute(
                    text_factory(_SCHEMA_READY_SQL)
                ).mappings().one()
                session.rollback()
        except Exception as exc:
            raise CatalogRepositoryError(
                "Failed to verify neg-risk catalog schema: "
                f"{type(exc).__name__}"
            ) from None
        missing = [
            str(name)
            for name, present in row.items()
            if present is not True
        ]
        if missing:
            raise CatalogRepositoryError(
                "Neg-risk catalog schema is incomplete: "
                + ",".join(sorted(missing))
            )

    def start_scan(
        self,
        *,
        started_at: datetime,
        metadata: Mapping[str, object],
        scan_id: UUID | None = None,
    ) -> UUID:
        identifier = scan_id or uuid4()
        params = {
            "scan_id": str(identifier),
            "started_at": started_at,
            "metadata": _json(metadata),
        }
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                session.execute(
                    text_factory(_RECOVER_RUNNING_SCANS_SQL),
                    {"started_at": started_at},
                )
                session.execute(
                    text_factory(
                        _DELETE_FAILED_STAGED_MARKETS_SQL
                    )
                )
                session.execute(
                    text_factory(
                        _DELETE_FAILED_STAGED_EVENTS_SQL
                    )
                )
                row = session.execute(
                    text_factory(_START_SCAN_SQL),
                    params,
                ).mappings().one()
                session.commit()
        except Exception as exc:
            raise CatalogRepositoryError(
                "Failed to start neg-risk catalog scan: "
                f"{type(exc).__name__}"
            ) from None
        return UUID(str(row["scan_id"]))

    def record_page(
        self,
        *,
        scan_id: UUID,
        page: CatalogPage,
        observed_at: datetime,
    ) -> None:
        event_params = [
            _staged_event_params(
                event,
                scan_id=scan_id,
                observed_at=observed_at,
            )
            for event in page.events
        ]
        market_params = [
            _staged_market_params(
                market,
                scan_id=scan_id,
                observed_at=observed_at,
            )
            for market in page.markets
        ]
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                if event_params:
                    session.execute(
                        text_factory(_STAGE_EVENT_SQL),
                        event_params,
                    )
                if market_params:
                    session.execute(
                        text_factory(_STAGE_MARKET_SQL),
                        market_params,
                    )
                session.execute(
                    text_factory(_TOUCH_SCAN_SQL),
                    {
                        "scan_id": str(scan_id),
                        "gamma_market_count": (
                            page.gamma_market_count
                        ),
                        "neg_risk_market_count": (
                            page.neg_risk_market_count
                        ),
                        "issue_count": page.issue_count,
                        "skipped_market_count": (
                            page.skipped_market_count
                        ),
                    },
                )
                session.commit()
        except Exception as exc:
            raise CatalogRepositoryError(
                "Failed to persist neg-risk catalog page: "
                f"{type(exc).__name__}"
            ) from None

    def complete_scan(
        self,
        *,
        scan_id: UUID,
        completed_at: datetime,
        duration_ms: int,
    ) -> None:
        params = {
            "scan_id": str(scan_id),
            "completed_at": completed_at,
            "duration_ms": int(duration_ms),
        }
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                session.execute(
                    text_factory(_PROMOTE_EVENTS_SQL),
                    params,
                )
                session.execute(
                    text_factory(_PROMOTE_MARKETS_SQL),
                    params,
                )
                session.execute(
                    text_factory(_MARK_MISSING_MARKETS_SQL),
                    params,
                )
                session.execute(
                    text_factory(_MARK_MISSING_EVENTS_SQL),
                    params,
                )
                session.execute(
                    text_factory(_FINALIZE_EVENTS_SQL),
                    params,
                )
                session.execute(
                    text_factory(_COMPLETE_SCAN_SQL),
                    params,
                )
                session.execute(
                    text_factory(_DELETE_STAGED_MARKETS_SQL),
                    params,
                )
                session.execute(
                    text_factory(_DELETE_STAGED_EVENTS_SQL),
                    params,
                )
                session.commit()
        except Exception as exc:
            raise CatalogRepositoryError(
                "Failed to complete neg-risk catalog scan: "
                f"{type(exc).__name__}"
            ) from None

    def fail_scan(
        self,
        *,
        scan_id: UUID,
        completed_at: datetime,
        duration_ms: int,
        reason_code: str,
    ) -> None:
        session_factory, text_factory = self._dependencies()
        try:
            with session_factory() as session:
                session.execute(
                    text_factory(_FAIL_SCAN_SQL),
                    {
                        "scan_id": str(scan_id),
                        "completed_at": completed_at,
                        "duration_ms": int(duration_ms),
                        "reason_code": _reason(reason_code),
                    },
                )
                session.execute(
                    text_factory(_DELETE_STAGED_MARKETS_SQL),
                    {"scan_id": str(scan_id)},
                )
                session.execute(
                    text_factory(_DELETE_STAGED_EVENTS_SQL),
                    {"scan_id": str(scan_id)},
                )
                session.commit()
        except Exception as exc:
            raise CatalogRepositoryError(
                "Failed to mark neg-risk catalog scan failed: "
                f"{type(exc).__name__}"
            ) from None

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def _dependencies(
        self,
    ) -> tuple[Callable[[], Any], Callable[[str], Any]]:
        session_factory = self._session_factory
        text_factory = self._text_factory
        if session_factory is None:
            if not self._database_url:
                raise CatalogRepositoryError(
                    "Neg-risk catalog database is not configured"
                )
            try:
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
            except ImportError:
                raise CatalogRepositoryError(
                    "Neg-risk catalog persistence requires SQLAlchemy"
                ) from None
            try:
                normalized_url = _normalize_database_url(
                    self._database_url
                )
                connect_args: dict[str, object] = {}
                if normalized_url.startswith(
                    (
                        "postgresql://",
                        "postgresql+psycopg2://",
                    )
                ):
                    connect_args["application_name"] = (
                        "codexpoly_neg_risk_catalog"
                    )
                self._engine = create_engine(
                    normalized_url,
                    pool_size=1,
                    max_overflow=0,
                    pool_timeout=5,
                    pool_pre_ping=True,
                    pool_recycle=300,
                    pool_reset_on_return="rollback",
                    hide_parameters=True,
                    connect_args=connect_args,
                )
                session_factory = sessionmaker(
                    bind=self._engine,
                    expire_on_commit=False,
                )
            except Exception as exc:
                raise CatalogRepositoryError(
                    "Failed to initialize neg-risk catalog "
                    f"persistence: {type(exc).__name__}"
                ) from None
            self._session_factory = session_factory
        if text_factory is None:
            try:
                from sqlalchemy import text
            except ImportError:
                raise CatalogRepositoryError(
                    "Neg-risk catalog persistence requires SQLAlchemy"
                ) from None
            text_factory = text
            self._text_factory = text_factory
        return session_factory, text_factory


def _staged_event_params(
    event: CatalogEvent,
    *,
    scan_id: UUID,
    observed_at: datetime,
) -> dict[str, object]:
    return {
        "scan_id": str(scan_id),
        "event_id": event.event_id,
        "payload": _json(
            {
                "observed_at": _iso(observed_at),
                "slug": event.slug,
                "title": event.title,
                "active": event.active,
                "closed": event.closed,
                "archived": event.archived,
                "augmented": event.augmented,
                "enable_order_book": event.enable_order_book,
                "end_date": _iso(event.end_date),
                "source_updated_at": _iso(
                    event.source_updated_at
                ),
                "volume": str(event.volume),
                "volume_24h": str(event.volume_24h),
                "volume_1wk": str(event.volume_1wk),
                "volume_1mo": str(event.volume_1mo),
                "volume_1yr": str(event.volume_1yr),
                "liquidity": str(event.liquidity),
                "open_interest": str(event.open_interest),
                "tags": event.tags,
            }
        ),
    }


def _staged_market_params(
    market: Any,
    *,
    scan_id: UUID,
    observed_at: datetime,
) -> dict[str, object]:
    return {
        "scan_id": str(scan_id),
        "market_id": market.market_id,
        "event_id": market.event_id,
        "payload": _json(
            {
                "observed_at": _iso(observed_at),
                "condition_id": market.condition_id,
                "slug": market.slug,
                "question": market.question,
                "yes_token_id": market.yes_token_id,
                "no_token_id": market.no_token_id,
                "neg_risk_other": market.neg_risk_other,
                "accepting_orders": market.accepting_orders,
                "enable_order_book": market.enable_order_book,
                "end_date": _iso(market.end_date),
                "source_updated_at": _iso(
                    market.source_updated_at
                ),
                "volume": str(market.volume),
                "volume_24h": str(market.volume_24h),
                "volume_1wk": str(market.volume_1wk),
                "volume_1mo": str(market.volume_1mo),
                "volume_1yr": str(market.volume_1yr),
                "liquidity": str(market.liquidity),
                "yes_price": _decimal_text(market.yes_price),
                "no_price": _decimal_text(market.no_price),
                "best_bid": _decimal_text(market.best_bid),
                "best_ask": _decimal_text(market.best_ask),
                "spread": _decimal_text(market.spread),
                "tick_size": _decimal_text(market.tick_size),
                "minimum_order_size": _decimal_text(
                    market.minimum_order_size
                ),
                "fees_enabled": market.fees_enabled,
                "fee_type": market.fee_type,
                "fee_category": market.fee_category,
                "fee_rate": _decimal_text(market.fee_rate),
                "fee_exponent": market.fee_exponent,
                "taker_only": market.taker_only,
                "rebate_rate": _decimal_text(
                    market.rebate_rate
                ),
                "rewards_minimum_size": _decimal_text(
                    market.rewards_minimum_size
                ),
                "rewards_maximum_spread": _decimal_text(
                    market.rewards_maximum_spread
                ),
                "holding_rewards_enabled": (
                    market.holding_rewards_enabled
                ),
                "metadata_complete": market.metadata_complete,
                "issue_codes": market.issue_codes,
            }
        ),
    }


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decimal_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _reason(value: object) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError("reason_code is required")
    return result[:160]


def _normalize_database_url(value: str) -> str:
    url = str(value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
