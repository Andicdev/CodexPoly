# agents/data_api_helpers.py
"""
Data API helpers extracted from agents/global_trades_subgraph_ingest.py and common/polymarket_utils.py.


Важно: на первом шаге это КОПИЯ.
В исходном файле пока ничего не удаляем, чтобы не менять поведение.
После проверки можно будет:
  1) переключить импорты (воркер/ингест) на этот модуль
  2) удалить дубли из global_trades_subgraph_ingest.py
"""

import logging
import os
import time
from urllib.parse import urlparse
from datetime import datetime, timezone
from datetime import datetime, timedelta, timezone as _tz
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


import requests
from sqlalchemy import select, func, or_, update, bindparam, case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError

from common.db import get_session
from common.rpc_fills import fetch_usdc_balances_polygon_batch
from models.t_watermarks import Watermark
from models.t_all_wallets import AllWallet
from models.t_wallet_enrich_data import WalletEnrichData

log = logging.getLogger(__name__)

AnalyticsSession = get_session("analytics")

# ─────────────────────────────────────────────────────────────────────────────
# Watermark helpers (нужны для инкрементального enrich)
# ─────────────────────────────────────────────────────────────────────────────
DATA_API_WM_KEY = "wallet_data_api_enrich"


def _get_or_create_watermark_ts(key: str) -> datetime:
    now = datetime.now(_tz.utc)
    with AnalyticsSession() as s:
        ts = s.execute(select(Watermark.ts).where(Watermark.name == key)).scalar_one_or_none()
        if ts is not None:
            return ts

        ins = (
            pg_insert(Watermark)
            .values(name=key, ts=now, updated_at=now)
            .on_conflict_do_nothing(index_elements=[Watermark.name])
        )
        s.execute(ins)
        s.commit()
        return now


def _set_watermark_ts(key: str, ts: datetime, *, last_block: Optional[int] = None) -> None:
    now = datetime.now(_tz.utc)
    values = {"name": key, "ts": ts, "updated_at": now}
    if last_block is not None:
        values["last_block"] = int(last_block)

    stmt = (
        pg_insert(Watermark)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[Watermark.name],
            set_={
                "ts": ts,
                "updated_at": now,
                **({"last_block": int(last_block)} if last_block is not None else {}),
            },
        )
    )
    with AnalyticsSession() as s:
        s.execute(stmt)
        s.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Data API config
# ─────────────────────────────────────────────────────────────────────────────
DATA_API_BASE = os.getenv("DATA_API_BASE", "https://data-api.polymarket.com")
DATA_API_ACTIVITY_URL = f"{DATA_API_BASE}/activity"
DATA_API_TRADED_URL = f"{DATA_API_BASE}/traded"
DATA_API_VALUE_URL = f"{DATA_API_BASE}/value"

# те же env, что использовались в исходном файле
DATA_API_CONNECT_TIMEOUT = float(os.getenv("MP_CONNECT_TIMEOUT", "10"))
DATA_API_READ_TIMEOUT = float(os.getenv("MP_READ_TIMEOUT", "60"))
DATA_API_TIMEOUT = (DATA_API_CONNECT_TIMEOUT, DATA_API_READ_TIMEOUT)
DATA_API_MAX_RETRIES = int(os.getenv("MP_MAX_RETRIES", "3"))
DATA_API_BACKOFF = float(os.getenv("MP_BACKOFF", "0.8"))

DATA_API_ENRICH_ENABLED = os.getenv("DATA_API_ENRICH_ENABLED", "1") == "1"
DATA_API_ENRICH_LIMIT = int(os.getenv("DATA_API_ENRICH_LIMIT", "250"))
DATA_API_ENRICH_TTL_HOURS = float(os.getenv("DATA_API_ENRICH_TTL_HOURS", "18"))
DATA_API_ENRICH_WALLET_BATCH = int(os.getenv("DATA_API_ENRICH_WALLET_BATCH", "25"))
DATA_API_ENRICH_SLEEP_BETWEEN_WALLETS = float(
    os.getenv("DATA_API_ENRICH_SLEEP_BETWEEN_WALLETS", "0.2")
)
DATA_API_ENRICH_SLEEP_BETWEEN_BATCHES = float(
    os.getenv("DATA_API_ENRICH_SLEEP_BETWEEN_BATCHES", "1.5")
)

# Toggle Polygon RPC USDC balance refresh inside enrichment.
# Useful when Infura/Alchemy key is not available or when we want to reduce credits.
# Default: enabled (backward compatible).
DATA_API_RPC_BALANCE_REFRESH_ENABLED = (
    os.getenv("DATA_API_RPC_BALANCE_REFRESH_ENABLED", "0").strip().lower()
    in ("1", "true", "yes", "y", "on")
)

# ─────────────────────────────────────────────────────────────────────────────
# Enrich prioritization (queued wallets first)
# Buckets:
#   0) markets_traded_count IS NULL (brand new)
#   1) markets_traded_count < ENRICH_FAST_THRESHOLD
#   2) markets_traded_count >= ENRICH_FAST_THRESHOLD
# ─────────────────────────────────────────────────────────────────────────────

ENRICH_FAST_THRESHOLD = int(os.getenv("ENRICH_FAST_THRESHOLD", "50"))
def _resolve_polygon_rpc_url() -> str:
    """
    Prefer common.config (it loads .env and may provide defaults), fallback to raw env.
    Mirrors test_rpc_usdc_batch.py behavior, but also supports INFURA_POLYGON_RPC_URL.
    """
    try:
        from common import config as _config  # load_dotenv + defaults live here
        # Prefer dedicated balance RPC URL if configured (separate key/credits).
        return (
            (getattr(_config, "POLYGON_RPC_URL_BALANCE", "") or "")
            or (getattr(_config, "POLYGON_RPC_URL", "") or "")
            or (getattr(_config, "INFURA_POLYGON_RPC_URL", "") or "")
        ).strip()
    except Exception:
        # fallback (safe): direct env
        return (
            os.getenv("POLYGON_RPC_URL_BALANCE")
            or os.getenv("POLYGON_RPC_URL")
            or os.getenv("INFURA_POLYGON_RPC_URL")
            or ""
        ).strip()

POLYGON_RPC_URL = _resolve_polygon_rpc_url()
if not POLYGON_RPC_URL:
    log.warning(
        "[data-api] Polygon RPC URL is empty -> RPC USDC balance refresh will be skipped. "
        "Set POLYGON_RPC_URL_BALANCE (preferred for balances) or POLYGON_RPC_URL / INFURA_POLYGON_RPC_URL."
    )

def _normalize_evm_address(addr: str) -> str:
    """Normalize EVM address to lowercase `0x` + 40 hex chars. Returns "" if invalid."""
    a = (addr or "").strip()
    if not a:
        return ""
    a0 = a.lower()
    if a0.startswith("0x"):
        a0 = a0[2:]
    if len(a0) != 40:
        return ""
    try:
        int(a0, 16)
    except Exception:
        return ""
    return "0x" + a0

def rpc_fetch_usdc_balances_polygon_usdc(
    wallets: List[str],
    *,
    rpc_url: Optional[str] = None,
) -> Dict[str, Decimal]:
    """Fetch Polygon USDC balances via RPC in one batch.

    Returns mapping wallet(lowercase) -> Decimal balance in USDC.
    Invalid wallets are ignored.
    """
    w_norm: List[str] = []
    for w in wallets or []:
        ww = _normalize_evm_address(w)
        if ww:
            w_norm.append(ww)
    if not w_norm:
        return {}

    url = (rpc_url or "").strip() or _resolve_polygon_rpc_url()
    if not url:
        return {}

    raw_map = fetch_usdc_balances_polygon_batch(rpc_url=url, wallets=w_norm)
    if not raw_map:
        return {}

    scale = Decimal("1000000")
    out: Dict[str, Decimal] = {}
    for w in w_norm:
        raw = raw_map.get(w)
        if raw is None:
            continue
        try:
            out[w] = Decimal(int(raw)) / scale
        except Exception:
            continue
    return out

def rpc_refresh_usdc_balances_polygon_usdc(
    wallets: List[str],
    *,
    rpc_url: Optional[str] = None,
    write_db: bool = False,
) -> Dict[str, Decimal]:
    """Fetch Polygon USDC balances via RPC and (optionally) upsert into analytics.all_wallets.

    This is the *single* shared method used across workers/notifications.
    """
    out = rpc_fetch_usdc_balances_polygon_usdc(wallets, rpc_url=rpc_url)
    if not out or not write_db:
        return out

    try:
        tbl = getattr(AllWallet, "__table__", None)
        if tbl is None:
            return out

        now = datetime.now(timezone.utc)
        rows: List[Dict[str, Any]] = []
        # Deterministic order reduces deadlock probability across concurrent upserts.
        for w in sorted(out.keys()):
            bal = out[w]
            r: Dict[str, Any] = {"wallet": w, "usdc_balance": bal}

            # Some deployments have NOT NULL constraints on first_seen/last_seen/trades_count.
            # If we ever insert a brand new row here (wallet not present yet), populate them safely.
            if hasattr(tbl, "c") and "first_seen" in tbl.c:
                r.setdefault("first_seen", now)
            if hasattr(tbl, "c") and "last_seen" in tbl.c:
                r.setdefault("last_seen", now)
            if hasattr(tbl, "c") and "trades_count" in tbl.c:
                r.setdefault("trades_count", 0)

            if hasattr(tbl, "c") and "updated_at" in tbl.c:
                r["updated_at"] = now
            if hasattr(tbl, "c") and "created_at" in tbl.c:
                r.setdefault("created_at", now)
            rows.append(r)

        if not rows:
            return out

        stmt = pg_insert(tbl).values(rows)
        set_vals: Dict[str, Any] = {"usdc_balance": stmt.excluded.usdc_balance}
        if hasattr(tbl, "c") and "updated_at" in tbl.c:
            set_vals["updated_at"] = stmt.excluded.updated_at
        stmt = stmt.on_conflict_do_update(index_elements=[tbl.c.wallet], set_=set_vals)

        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                with AnalyticsSession() as s:
                    s.execute(stmt)
                    s.commit()
                last_err = None
                break
            except OperationalError as e:
                last_err = e
                # Treat deadlocks / serialization failures / lock timeouts as retryable.
                pgcode = None
                try:
                    orig = getattr(e, "orig", None)
                    pgcode = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
                except Exception:
                    pgcode = None
                msg = ""
                try:
                    msg = str(getattr(e, "orig", None) or e).lower()
                except Exception:
                    msg = str(e).lower()

                retryable = (pgcode in {"40P01", "40001", "55P03", "57014"}) or ("deadlock detected" in msg) or ("lock timeout" in msg)
                if retryable and attempt < 3:
                    time.sleep(0.2 * attempt)
                    continue
                raise
        if last_err is not None:
            raise last_err
    except Exception as e:
        log.warning("[rpc-balance] db upsert failed: %s", str(e)[:240])

    return out

def rpc_fetch_usdc_balance_polygon_usdc(wallet: str, *, rpc_url: Optional[str] = None) -> Optional[Decimal]:
    m = rpc_fetch_usdc_balances_polygon_usdc([wallet], rpc_url=rpc_url)
    w = _normalize_evm_address(wallet)
    return m.get(w) if w else None


def rpc_refresh_usdc_balance_polygon_usdc(
    wallet: str,
    *,
    rpc_url: Optional[str] = None,
    write_db: bool = False,
) -> Optional[Decimal]:
    m = rpc_refresh_usdc_balances_polygon_usdc([wallet], rpc_url=rpc_url, write_db=write_db)
    w = _normalize_evm_address(wallet)
    return m.get(w) if w else None


class DataApiRetryableError(RuntimeError):
    """Error that should stop the current enrichment run (429 / 503)."""

    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message or f"Data API retryable error: HTTP {status_code}")
        self.status_code = int(status_code)


_data_api_session: Optional[requests.Session] = None


def _data_api_session_get() -> requests.Session:
    global _data_api_session
    if _data_api_session is None:
        s = requests.Session()
        s.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "data_api_helpers/1.0",
            }
        )
        _data_api_session = s
    return _data_api_session


def _data_api_get_json(url: str, params: Dict[str, Any]) -> Any:
    """GET wrapper with retries. Raises DataApiRetryableError on 429/503."""
    sess = _data_api_session_get()
    last_err: Optional[Exception] = None

    for attempt in range(1, DATA_API_MAX_RETRIES + 1):
        try:
            r = sess.get(url, params=params, timeout=DATA_API_TIMEOUT)
            if r.status_code in (429, 503):
                raise DataApiRetryableError(
                    r.status_code,
                    message=f"Data API returned HTTP {r.status_code} for {url} params={params}",
                )
            r.raise_for_status()
            return r.json()
        except DataApiRetryableError as e:
            last_err = e
            time.sleep(DATA_API_BACKOFF * attempt)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            time.sleep(DATA_API_BACKOFF * attempt)
        except Exception as e:
            last_err = e
            time.sleep(DATA_API_BACKOFF * attempt)

    if last_err is not None:
        raise last_err
    raise RuntimeError("Data API request failed")


def _ts_from_activity_event(ev: Optional[Dict[str, Any]]) -> Optional[datetime]:
    if not ev:
        return None
    ts = ev.get("timestamp") or ev.get("createdAt") or ev.get("created_at")
    if not ts:
        return None
    # может прийти как int/float (unix) или как ISO строка
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=_tz.utc)
        if isinstance(ts, str):
            s = ts.strip()
            # нормализуем Z
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
    except Exception:
        return None
    return None


def _data_api_fetch_activity_edge(wallet: str, direction: str) -> Optional[Dict[str, Any]]:
    w = (wallet or "").strip().lower()
    if not w:
        return None
    params = {
        "user": w,
        "limit": 1,
        "offset": 0,
        "sortBy": "TIMESTAMP",
        "sortDirection": direction,  # "ASC" or "DESC"
    }
    data = _data_api_get_json(DATA_API_ACTIVITY_URL, params=params)
    if isinstance(data, list) and data:
        return data[0]
    return None


def _data_api_fetch_traded_count(wallet: str) -> Optional[int]:
    w = (wallet or "").strip().lower()
    if not w:
        return None
    params = {"user": w}
    data = _data_api_get_json(DATA_API_TRADED_URL, params=params)
    # ожидаем число или dict с count
    try:
        if isinstance(data, (int, float)):
            return int(data)
        if isinstance(data, dict):
            # официально: {"user": "...", "traded": 123}
            # https://docs.polymarket.com/api-reference/misc/get-total-markets-a-user-has-traded
            for k in ("traded", "count", "markets", "marketsTraded", "markets_traded"):

                if k in data:
                    return int(data[k] or 0)
    except Exception:
        return None
    return None

def data_api_get_traded_count(wallet: str) -> Optional[int]:
    """Lightweight helper: fetch total markets traded for a wallet via Data API (/traded).

    Important: does NOT write anything to the database (safe for UI/notifications).
    """
    w = (wallet or "").strip().lower()
    if not w:
        return None
    try:
        return _data_api_fetch_traded_count(w)
    except DataApiRetryableError as e:
        # 429/503: treat as "no data" for UI purposes, caller may fallback to cached DB values.
        log.debug("[data-api] traded_count retryable error wallet=%s: %s", w, str(e)[:200])
        return None
    except Exception as e:
        log.debug("[data-api] traded_count error wallet=%s: %s", w, str(e)[:200])
        return None


def _data_api_fetch_positions_value(wallet: str) -> Optional[Decimal]:
    w = (wallet or "").strip().lower()
    if not w:
        return None
    params = {"user": w}
    data = _data_api_get_json(DATA_API_VALUE_URL, params=params)
    # ожидаем dict {"value": "..."} или сразу число/строку
    try:
        if isinstance(data, dict):
            v = data.get("value")
            if v is None:
                return None
            return Decimal(str(v))
        if isinstance(data, (int, float, str)):
            return Decimal(str(data))
    except Exception:
        return None
    return None


def _mark_wallet_enrich_error(wallet: str, err: str) -> None:
    w = (wallet or "").strip().lower()
    if not w:
        return
    now = datetime.now(_tz.utc)
    stmt = (
        pg_insert(AllWallet)
        .values(
            wallet=w,
            # required NOT NULL columns for a brand new wallet row
            first_seen=now,
            last_seen=now,
            trades_count=0,
            enrich_status="error",
            enrich_error=(err or "")[:500],
            enriched_at=now,
        )
        .on_conflict_do_update(
            index_elements=[AllWallet.wallet],
            set_={
                "enrich_status": "error",
                "enrich_error": (err or "")[:500],
                "enriched_at": now,
            },
        )
    )
    with AnalyticsSession() as s:
        s.execute(stmt)
        s.commit()


def _upsert_wallet_enrich_data_data_api(wallet: str) -> Tuple[str, Optional[str], Dict[str, Any]]:
    """
    Enrich a single wallet via Polymarket Data API and upsert into:
      - analytics.wallet_enrich_data
      - analytics.all_wallets (status + a few aggregates)

    Returns: (status, error_text, snapshot_dict)
      status: 'ok' | 'partial' | 'error'
    """
    w = (wallet or "").strip().lower()
    if not w:
        return ("error", "wallet is empty", {"wallet": wallet})

    now = datetime.now(_tz.utc)
    errors: List[str] = []

    # /activity (first + last)
    first_ev: Optional[Dict[str, Any]] = None
    last_ev: Optional[Dict[str, Any]] = None
    try:
        first_ev = _data_api_fetch_activity_edge(w, "ASC")
    except DataApiRetryableError:
        raise
    except Exception as e:
        errors.append(f"activity_first: {type(e).__name__}: {str(e)[:200]}")

    try:
        last_ev = _data_api_fetch_activity_edge(w, "DESC")
    except DataApiRetryableError:
        raise
    except Exception as e:
        errors.append(f"activity_last: {type(e).__name__}: {str(e)[:200]}")

    first_activity_ts = _ts_from_activity_event(first_ev)
    last_activity_ts = _ts_from_activity_event(last_ev)

    name = (first_ev or {}).get("name") or (last_ev or {}).get("name")
    bio = (first_ev or {}).get("bio") or (last_ev or {}).get("bio")
    profile_image = (first_ev or {}).get("profileImage") or (last_ev or {}).get("profileImage")

    # /traded
    markets_traded_count: Optional[int] = None
    try:
        markets_traded_count = _data_api_fetch_traded_count(w)
    except DataApiRetryableError:
        raise
    except Exception as e:
        errors.append(f"traded: {type(e).__name__}: {str(e)[:200]}")

    # /value
    positions_total_value_usdc: Optional[Decimal] = None
    try:
        positions_total_value_usdc = _data_api_fetch_positions_value(w)
    except DataApiRetryableError:
        raise
    except Exception as e:
        errors.append(f"value: {type(e).__name__}: {str(e)[:200]}")

    status = "ok"
    err_text: Optional[str] = None
    if errors:
        status = "partial"
        err_text = "; ".join(errors)[:500]

    snap = {
        "wallet": w,
        "name": name,
        "bio": bio,
        "profile_image": profile_image,
        "first_activity_ts": first_activity_ts,
        "last_activity_ts": last_activity_ts,
        "markets_traded_count": markets_traded_count,
        "positions_total_value_usdc": positions_total_value_usdc,
        "status": status,
        "error": err_text,
        "updated_at": now,
    }

    # upsert wallet_enrich_data
    stmt_enrich = (
        pg_insert(WalletEnrichData)
        .values(
            wallet=w,
            name=name,
            bio=bio,
            profile_image=profile_image,
            first_activity_ts=first_activity_ts,
            last_activity_ts=last_activity_ts,
            markets_traded_count=markets_traded_count,
            positions_total_value_usdc=positions_total_value_usdc,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[WalletEnrichData.wallet],
            set_={
                "name": name,
                "bio": bio,
                "profile_image": profile_image,
                "first_activity_ts": first_activity_ts,
                "last_activity_ts": last_activity_ts,
                # не затираем существующие значения, если data-api часть не пришла
                "markets_traded_count": func.coalesce(
                    pg_insert(WalletEnrichData).excluded.markets_traded_count,
                    WalletEnrichData.markets_traded_count,
                ),
                "positions_total_value_usdc": func.coalesce(
                    pg_insert(WalletEnrichData).excluded.positions_total_value_usdc,
                    WalletEnrichData.positions_total_value_usdc,
                ),
                "updated_at": now,
            },
        )
    )

    # update all_wallets lightweight status + aggregates
    next_enrich_after = now + timedelta(hours=float(DATA_API_ENRICH_TTL_HOURS))
    stmt_all = (
        pg_insert(AllWallet)
        .values(
            wallet=w,
            # required NOT NULL columns for safety (in case wallet row doesn't exist yet)
            first_seen=now,
            last_seen=now,
            trades_count=0,
            enriched_at=now,
            enrich_status=status,
            enrich_error=err_text,
            next_enrich_after=next_enrich_after,
            positions_updated_at=now,
            markets_traded_count=markets_traded_count,
            portfolio_value_usdc=positions_total_value_usdc,
        )
        .on_conflict_do_update(
            index_elements=[AllWallet.wallet],
            set_={
                # status/ttl fields must be updated, otherwise rows can get stuck in 'processing'
                "enriched_at": now,
                "enrich_status": status,
                "enrich_error": err_text,
                "next_enrich_after": next_enrich_after,
                "positions_updated_at": now,
                # не затираем существующие значения, если data-api часть не пришла
                "markets_traded_count": func.coalesce(
                    pg_insert(AllWallet).excluded.markets_traded_count,
                    AllWallet.markets_traded_count,
                ),
                "portfolio_value_usdc": func.coalesce(
                    pg_insert(AllWallet).excluded.portfolio_value_usdc,
                    AllWallet.portfolio_value_usdc,
                ),
            },
        )
    )

    with AnalyticsSession() as s:
        s.execute(stmt_enrich)
        s.execute(stmt_all)
        s.commit()

    return (status, err_text, snap)


def enrich_wallets_data_api_incremental(limit: int = DATA_API_ENRICH_LIMIT) -> int:
    """
    Incremental wallet enrichment (RPC-only / queued-driven).

    New selection logic:
      - only wallets with all_wallets.enrich_status == 'queued'
      - prioritize:
          (0) markets_traded_count IS NULL
          (1) markets_traded_count < ENRICH_FAST_THRESHOLD
          (2) markets_traded_count >= ENRICH_FAST_THRESHOLD
        then by last_seen DESC

    Before Data API calls:
      - refresh absolute USDC balances via Polygon RPC in one batch for the selected wallets

    Watermark/TTL:
      - no longer used for selection here (kept helpers in file for compatibility)
    """
    if not DATA_API_ENRICH_ENABLED:
        return 0

    limit = int(limit or DATA_API_ENRICH_LIMIT)

    # (A) pick queued wallets with prioritization + lock them (best-effort)
    wallets: List[str] = []
    bucket_counts = {"null": 0, "lt": 0, "ge": 0}
    bucket_examples = {"null": [], "lt": [], "ge": []}
    with AnalyticsSession() as s:
        q = (
            select(AllWallet.wallet, AllWallet.markets_traded_count)
            .where(AllWallet.enrich_status == "queued")
            .order_by(
                case(
                    (AllWallet.markets_traded_count.is_(None), 0),
                    (AllWallet.markets_traded_count < int(ENRICH_FAST_THRESHOLD), 1),
                    else_=2,
                ),
                AllWallet.last_seen.desc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list(s.execute(q).all())


        # Build wallets + small diagnostics by bucket
        for w, mtc in rows:
            ww = (w or "").strip().lower()
            if not ww:
                continue
            wallets.append(ww)
            if mtc is None:
                bucket_counts["null"] += 1
                if len(bucket_examples["null"]) < 5:
                    bucket_examples["null"].append(ww)
            else:
                try:
                    mtc_i = int(mtc)
                except Exception:
                    mtc_i = 0
                if mtc_i < int(ENRICH_FAST_THRESHOLD):
                    bucket_counts["lt"] += 1
                    if len(bucket_examples["lt"]) < 5:
                        bucket_examples["lt"].append(ww)
                else:
                    bucket_counts["ge"] += 1
                    if len(bucket_examples["ge"]) < 5:
                        bucket_examples["ge"].append(ww)

        if not wallets:
            log.info("[data-api] nothing to enrich (no queued wallets)")
            return 0
        
        log.info(
            "[data-api] selected buckets: null=%s, <thr=%s, >=thr=%s (thr=%s) examples: null=%s lt=%s ge=%s",
            bucket_counts["null"],
            bucket_counts["lt"],
            bucket_counts["ge"],
            int(ENRICH_FAST_THRESHOLD),
            bucket_examples["null"],
            bucket_examples["lt"],
            bucket_examples["ge"],
        )

        # mark selected wallets as processing (avoid duplicates if multiple workers)
        s.execute(
            update(AllWallet)
            .where(AllWallet.wallet.in_(wallets))
            .values(enrich_status="processing", enrich_error=None)
            .execution_options(synchronize_session=False)
        )
        s.commit()

    total = len(wallets)
    log.info(
        "[data-api] queued enrich: wallets=%s (limit=%s, fast_threshold=%s)",
        total,
        limit,
        ENRICH_FAST_THRESHOLD,
    )

    # (B) RPC balance refresh (batch) — disabled.
    # We always fetch balances live via RPC only when needed for notifications/UI.
    # Persisting balances into DB is currently not maintained for integrity and may violate NOT NULL constraints.
    log.info("[data-api] rpc balance refresh: disabled (no DB writes)")

    ok = 0
    partial = 0
    failed = 0
    processed = 0
    batch_processed = 0
    batch_idx = 0

    for idx, w in enumerate(wallets):
        try:
            status, _err_text, _snap = _upsert_wallet_enrich_data_data_api(w)
            if status == "ok":
                ok += 1
            elif status == "partial":
                partial += 1
            else:
                failed += 1
            processed += 1
            batch_processed += 1
        except DataApiRetryableError as e:
            log.warning(
                "[data-api] stop on retryable error (HTTP %s) at wallet=%s: %s",
                getattr(e, "status_code", "?"),
                w,
                str(e)[:240],
            )
            # re-queue remaining wallets that were marked processing in this run
            remaining = wallets[idx:]
            if remaining:
                try:
                    with AnalyticsSession() as s:
                        s.execute(
                            update(AllWallet)
                            .where(AllWallet.wallet.in_(remaining))
                            .values(enrich_status="queued")
                            .execution_options(synchronize_session=False)
                        )
                        s.commit()
                except Exception:
                    pass
            break
        except Exception as e:
            failed += 1
            processed += 1
            batch_processed += 1

            _mark_wallet_enrich_error(w, f"{type(e).__name__}: {str(e)[:240]}")

        if DATA_API_ENRICH_SLEEP_BETWEEN_WALLETS and DATA_API_ENRICH_SLEEP_BETWEEN_WALLETS > 0:
            time.sleep(float(DATA_API_ENRICH_SLEEP_BETWEEN_WALLETS))

        if DATA_API_ENRICH_WALLET_BATCH > 0 and batch_processed >= int(DATA_API_ENRICH_WALLET_BATCH):
            batch_idx += 1
            log.info(
                "[data-api] batch #%s: processed=%s/%s ok=%s partial=%s failed=%s",
                batch_idx,
                processed,
                total,
                ok,
                partial,
                failed,
            )
            batch_processed = 0
            if DATA_API_ENRICH_SLEEP_BETWEEN_BATCHES and DATA_API_ENRICH_SLEEP_BETWEEN_BATCHES > 0:
                time.sleep(float(DATA_API_ENRICH_SLEEP_BETWEEN_BATCHES))

    log.info(
        "[data-api] done: processed=%s/%s ok=%s partial=%s failed=%s",
        processed,
        total,
        ok,
        partial,
        failed,
    )
    return processed



# ─────────────────────────────────────────────────────────────────────────────
# Data API helpers moved from common/polymarket_utils.py (COPY ONLY)
# (polymarket_utils.py пока не трогаем)
# ─────────────────────────────────────────────────────────────────────────────

# -------------------- User info (profile) helpers --------------------
def fetch_user_activity(user: str, *, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Тянем последние события активности пользователя из Data API (/activity).
    Возвращает список событий (как есть от API).
    """
    u = (user or "").strip().lower()
    if not u:
        return []

    params = {
        "user": u,
        "limit": max(1, min(int(limit), 500)),
        "offset": 0,
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC",
    }
    try:
        data = _data_api_get_json(DATA_API_ACTIVITY_URL, params=params)
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("activity fetch failed for user=%s: %s", u, e)
        return []


def fetch_user_profile(user: str) -> Dict[str, Optional[str]]:
    """
    Достаём базовые метаданные пользователя из ответа /activity:
    ожидаем поля на верхнем уровне события: name, pseudonym, bio, profileImage.
    Если в нескольких событиях поля пустые, берём первое непустое значение.
    """
    name: Optional[str] = None
    pseudonym: Optional[str] = None
    bio: Optional[str] = None
    profile_image: Optional[str] = None

    events = fetch_user_activity(user, limit=5)
    for ev in events:
        if not name and isinstance(ev.get("name"), str):
            name = ev["name"]
        if not pseudonym and isinstance(ev.get("pseudonym"), str):
            pseudonym = ev["pseudonym"]
        if bio is None and isinstance(ev.get("bio"), str):
            bio = ev["bio"]
        if not profile_image and isinstance(ev.get("profileImage"), str):
            profile_image = ev["profileImage"]
        if name and (pseudonym is not None) and (bio is not None) and profile_image:
            break

    return {
        "name": name,
        "pseudonym": pseudonym,
        "bio": bio,
        "profileImage": profile_image,
    }

# --------------- Positions (Data-API) ---------------
DATA_API_POSITIONS_URL = f"{DATA_API_BASE}/positions"


def fetch_user_positions(
    user: str,
    *,
    market: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Тянет текущие позиции пользователя (Data-API /positions).
    Можно ограничить конкретным рынком через market=condition_id.
    Возвращает список словарей позиций.
    """
    u = (user or "").strip().lower()
    if not u:
        return []
    try:
        params: Dict[str, Any] = {
            "user": u,
            "limit": max(1, min(int(limit), 500)),
            "offset": 0,
        }
        if market:
            params["market"] = (market or "").strip().lower()
        data = _data_api_get_json(DATA_API_POSITIONS_URL, params=params) or []
        if isinstance(data, dict) and "positions" in data:
            # на некоторых развёртках /positions возвращает объект
            data = data.get("positions") or []
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("positions fetch failed for user=%s market=%s: %s", u, market, e)
        return []


def fetch_user_positions_by_event(
    user: str,
    *,
    event_id: int,
    limit: int = 500,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Тянет текущие позиции пользователя по всему событию (Data-API /positions?eventId=...).
    Polymarket docs: eventId поддерживается и взаимоисключаем с market.
    """
    u = (user or "").strip().lower()
    if not u:
        return []

    try:
        eid = int(event_id)
    except Exception:
        return []

    params = {
        "user": u,
        "eventId": eid,
        "limit": max(1, min(int(limit), 500)),
        "offset": max(0, int(offset)),
    }

    try:
        data = _data_api_get_json(DATA_API_POSITIONS_URL, params=params) or []
        if isinstance(data, dict) and "positions" in data:
            data = data.get("positions") or []
        return data if isinstance(data, list) else []
    except Exception as e:
        log.warning("positions fetch failed for user=%s event_id=%s: %s", u, eid, e)
        return []

_POS_CACHE: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}
_POS_TTL_SEC = 30


def get_user_position_on_outcome(
    user: str,
    condition_id: str,
    outcome_index: int,
) -> Optional[Dict[str, Any]]:
    """
    Удобный резолвер «позиции по токену»: ищем запись по condition_id + outcomeIndex.
    Возвращает dict с ключами: size, avgPrice, curPrice, cashPnl, outcome, outcomeIndex (или None).
    С лёгким TTL-кэшем (~30с) для снижения нагрузки на API.
    """
    u = (user or "").lower().strip()
    m = (condition_id or "").lower().strip()
    try:
        oi = int(outcome_index)
    except Exception:
        oi = 0

    if not u or not m:
        return None

    # TTL cache
    cache_key = (u, m)
    now = time.time()
    ts_data = _POS_CACHE.get(cache_key)
    if ts_data and (now - ts_data[0] <= _POS_TTL_SEC):
        positions = ts_data[1]
    else:
        positions = fetch_user_positions(u, market=m, limit=100)
        _POS_CACHE[cache_key] = (now, positions)

    for p in positions:
        try:
            if (p.get("conditionId") or "").lower() == m and int(p.get("outcomeIndex", -999)) == oi:
                return {
                    "size": float(p.get("size") or 0.0),
                    "avgPrice": float(p.get("avgPrice") or 0.0),
                    "curPrice": float(p.get("curPrice") or 0.0),
                    "cashPnl": float(p.get("cashPnl") or 0.0),
                    "outcome": p.get("outcome"),
                    "outcomeIndex": oi,
                }
        except Exception:
            continue
    return None


def get_yes_no_positions_for_condition_data_api(
    user: str,
    condition_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Возвращает два словаря (YES, NO) по текущим позициям пользователя в конкретном рынке,
    полученные из Polymarket Data-API /positions.

    Используем outcomeIndex=0/1 как стандарт для бинарных рынков и опираемся на уже
    существующий TTL-кеш в get_user_position_on_outcome(), чтобы не дергать Data-API
    лишний раз в рамках одного цикла алертов.
    """
    yes = get_user_position_on_outcome(user=user, condition_id=condition_id, outcome_index=0)
    no = get_user_position_on_outcome(user=user, condition_id=condition_id, outcome_index=1)
    return yes, no
