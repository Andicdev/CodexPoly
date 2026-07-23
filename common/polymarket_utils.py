from common import config
from common import data_api_helpers as dah
from py_clob_client_v2 import (
    ApiCreds,
    ClobClient,
    OrderArgs,
    OrderType,
    PartialCreateOrderOptions,
    Side,
)

from types import SimpleNamespace

try:
    from py_clob_client_v2 import OpenOrderParams  # optional, depends on SDK version
except Exception:  # pragma: no cover
    OpenOrderParams = None

try:
    from py_clob_client_v2 import PostOrdersArgs  # optional, depends on SDK version
except Exception:  # pragma: no cover
    PostOrdersArgs = None

try:
    from py_clob_client_v2 import CancelOrderArgs  # optional, depends on SDK version
except Exception:  # pragma: no cover
    CancelOrderArgs = None    

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_UP, InvalidOperation
from enum import Enum
import logging
import requests
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple




import pandas as pd
from sqlalchemy import select
from common.db import Session
from sqlalchemy import func
from models.t_trading_accounts import TradingAccount
from models.t_gamma_market import GammaMarket
from models.t_interesting_markets import InterestingMarket

logger = logging.getLogger(__name__)

POLYMARKET_CLOB_HOST = "https://clob.polymarket.com"
POLYMARKET_CHAIN_ID = 137


try:
    from py_clob_client_v2 import BalanceAllowanceParams, AssetType
except Exception:  # SDK compatibility fallback
    BalanceAllowanceParams = None
    AssetType = None

PUSD_DECIMALS = Decimal("1000000")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _balance_allowance_params(asset_type: str, token_id: str | None = None) -> Any:
    asset_type_norm = str(asset_type or "").strip().upper()

    if BalanceAllowanceParams is not None and AssetType is not None:
        try:
            sdk_asset_type = getattr(AssetType, asset_type_norm)
        except Exception:
            sdk_asset_type = asset_type_norm

        kwargs = {"asset_type": sdk_asset_type}
        if token_id:
            kwargs["token_id"] = str(token_id)

        try:
            return BalanceAllowanceParams(**kwargs)
        except TypeError:
            pass

    params = {"asset_type": asset_type_norm}
    if token_id:
        params["token_id"] = str(token_id)
    return params


def get_balance_allowance_for_account(
    *,
    account_name: str,
    asset_type: str = "COLLATERAL",
    token_id: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    client = get_clob_client_for_account_name(account_name)
    params = _balance_allowance_params(asset_type=asset_type, token_id=token_id)

    if refresh:
        for method_name in ("update_balance_allowance", "updateBalanceAllowance"):
            fn = getattr(client, method_name, None)
            if callable(fn):
                try:
                    fn(params)
                except TypeError:
                    if isinstance(params, dict):
                        fn(**params)
                break

    get_fn = None
    for method_name in ("get_balance_allowance", "getBalanceAllowance"):
        fn = getattr(client, method_name, None)
        if callable(fn):
            get_fn = fn
            break

    if get_fn is None:
        raise RuntimeError("ClobClient has no get_balance_allowance/getBalanceAllowance method")

    try:
        raw = get_fn(params)
    except TypeError:
        if isinstance(params, dict):
            raw = get_fn(**params)
        else:
            raise

    if not isinstance(raw, dict):
        raise RuntimeError(f"Unexpected balance_allowance response: {raw!r}")

    balance_raw = _to_decimal(raw.get("balance"))
    allowance_raw = _to_decimal(raw.get("allowance"))

    balance = (balance_raw / PUSD_DECIMALS) if balance_raw is not None else None
    allowance = (allowance_raw / PUSD_DECIMALS) if allowance_raw is not None else None

    return {
        "success": True,
        "asset_type": str(asset_type).upper(),
        "token_id": token_id,
        "balance_raw": balance_raw,
        "allowance_raw": allowance_raw,
        "balance": balance,
        "allowance": allowance,
        "raw": raw,
    }


def get_free_collateral_for_account(account_name: str, *, refresh: bool = False) -> Decimal:
    ba = get_balance_allowance_for_account(
        account_name=account_name,
        asset_type="COLLATERAL",
        refresh=refresh,
    )
    balance = ba.get("balance")
    allowance = ba.get("allowance")

    if balance is None:
        raise RuntimeError(f"No collateral balance for account={account_name}: {ba.get('raw')!r}")

    if allowance is not None and allowance < balance:
        return allowance
    return balance


def _make_api_creds(raw: Any) -> Any:
    """
    V2 SDK обычно возвращает ApiCreds.
    На случай dict-ответа нормализуем в ApiCreds.
    """
    if isinstance(raw, ApiCreds):
        return raw

    if isinstance(raw, dict):
        api_key = raw.get("api_key") or raw.get("apiKey") or raw.get("key")
        api_secret = raw.get("api_secret") or raw.get("secret")
        api_passphrase = raw.get("api_passphrase") or raw.get("passphrase")
        if api_key and api_secret and api_passphrase:
            return ApiCreds(
                api_key=api_key,
                api_secret=api_secret,
                api_passphrase=api_passphrase,
            )

    return raw


def _create_or_derive_api_creds(client: ClobClient) -> Any:
    """
    Совместимость с разными версиями SDK:
    - V2 README: create_or_derive_api_key()
    - часть старых примеров: create_or_derive_api_creds()
    """
    if hasattr(client, "create_or_derive_api_key") and callable(client.create_or_derive_api_key):
        return _make_api_creds(client.create_or_derive_api_key())

    if hasattr(client, "create_or_derive_api_creds") and callable(client.create_or_derive_api_creds):
        return _make_api_creds(client.create_or_derive_api_creds())

    raise RuntimeError("ClobClient has no create_or_derive_api_key/create_or_derive_api_creds")


def _new_clob_client(
    *,
    key: str,
    creds: Any = None,
    signature_type: int | None = None,
    funder: str | None = None,
) -> ClobClient:
    """
    Создаёт CLOB V2 client.

    В py_clob_client_v2 README используется chain_id=137.
    В части V2-доков для TS встречается chain=137, поэтому тут есть fallback.
    """
    kwargs = {
        "host": POLYMARKET_CLOB_HOST,
        "chain_id": POLYMARKET_CHAIN_ID,
        "key": key,
    }
    if creds is not None:
        kwargs["creds"] = creds
    if signature_type is not None:
        kwargs["signature_type"] = int(signature_type)
    if funder:
        kwargs["funder"] = funder

    try:
        return ClobClient(**kwargs)
    except TypeError:
        kwargs["chain"] = kwargs.pop("chain_id")
        return ClobClient(**kwargs)


def _build_authenticated_clob_client(
    *,
    key: str,
    signature_type: int | None = None,
    funder: str | None = None,
) -> ClobClient:
    tmp = _new_clob_client(
        key=key,
        signature_type=signature_type,
        funder=funder,
    )
    creds = _create_or_derive_api_creds(tmp)
    return _new_clob_client(
        key=key,
        creds=creds,
        signature_type=signature_type,
        funder=funder,
    )


# Polymarket клиент по env/default аккаунту.
# Для live-торговли в стратегиях лучше использовать account-specific client через trading_accounts.
#
# ВАЖНО: не создаём authenticated CLOB client на import-time.
# Иначе любой воркер, который случайно импортирует polymarket_utils, сразу делает
# /auth/api-key и может получить Cloudflare 403, даже если CLOB в этом воркере не нужен.
_clob_client: ClobClient | None = None


def get_default_clob_client() -> ClobClient:
    global _clob_client
    if _clob_client is None:
        _clob_client = _build_authenticated_clob_client(
            key=config.PK,
            signature_type=1,
            funder=config.POLYMARKET_ADDRESS1,
        )
    return _clob_client

# -------------------- Trading accounts -> ClobClient --------------------
_ACCOUNT_CLIENT_CACHE: dict[tuple[str, int, str], ClobClient] = {}

def _get_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError("Missing dependency: cryptography. Install: pip install cryptography") from e

    master_key = (config.ACCOUNTS_MASTER_KEY or "").strip()
    if not master_key:
        raise RuntimeError("ACCOUNTS_MASTER_KEY is not set (required to decrypt trading_accounts.pk_enc)")
    return Fernet(master_key.encode("utf-8"))

def _decrypt_pk(pk_enc: bytes) -> str:
    f = _get_fernet()
    pk = f.decrypt(pk_enc).decode("utf-8")
    return pk


def _pick_first_text(obj, fields: list[str]) -> Optional[str]:
    for f in fields:
        try:
            v = getattr(obj, f, None)
        except Exception:
            v = None
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None

def resolve_question_for_condition(s, condition_id: str) -> Optional[str]:
    """
    Пытаемся достать человекочитаемый вопрос по condition_id из локальных таблиц:
      1) analytics.interesting_markets.question
      2) gamma_markets (question/title/name/slug и т.п.)
    """
    cid = (condition_id or "").strip()
    if not cid:
        return None

    # 1) InterestingMarket
    try:
        im = (
            s.query(InterestingMarket)
            .filter(InterestingMarket.condition_id.isnot(None))
            .filter(func.lower(InterestingMarket.condition_id) == cid.lower())
            .order_by(InterestingMarket.id.desc())
            .first()
        )
        if im:
            q = _pick_first_text(im, ["question", "title", "slug"])
            if q:
                return q
    except Exception:
        pass

    # 2) GammaMarket
    try:
        gm = (
            s.query(GammaMarket)
            .filter(GammaMarket.clob_condition.isnot(None))
            .filter(func.lower(GammaMarket.clob_condition) == cid.lower())
            .order_by(GammaMarket.id.desc() if hasattr(GammaMarket, "id") else GammaMarket.market_id.desc())
            .first()
        )
        if gm:
            q = _pick_first_text(gm, ["question", "title", "name", "slug"])
            if q:
                return q
    except Exception:
        pass

    return None

def get_trading_account_by_name(account_name: str) -> TradingAccount:
    name = (account_name or "").strip()
    if not name:
        raise ValueError("account_name is empty")

    with Session() as s:
        acc = s.execute(select(TradingAccount).where(TradingAccount.name == name)).scalar_one_or_none()
        if not acc:
            raise ValueError(f"TradingAccount not found by name='{name}'")
        if not acc.is_active:
            raise ValueError(f"TradingAccount '{name}' is disabled (is_active=false)")
        if not acc.pk_enc:
            raise ValueError(f"TradingAccount '{name}' has empty pk_enc")
        if not acc.wallet_address:
            raise ValueError(f"TradingAccount '{name}' has empty wallet_address")
        return acc

def get_clob_client_for_account_name(account_name: str, *, use_cache: bool = True) -> ClobClient:
    name = (account_name or "").strip()
    if not name:
        raise ValueError("account_name is empty")

    # cache key includes signature_type and funder to avoid silent mismatches if DB row changes
    # (signature_type is critical for Safe/proxy wallets)
    acc = get_trading_account_by_name(name)
    pk_plain = _decrypt_pk(acc.pk_enc)
    sig_type = int(acc.signature_type or 1)
    funder = acc.wallet_address
    cache_key = (name, sig_type, funder.lower())
    if use_cache and cache_key in _ACCOUNT_CLIENT_CACHE:
        return _ACCOUNT_CLIENT_CACHE[cache_key]

    # Debug: verify PK corresponds to funder wallet_address
    try:
        from eth_account import Account
        derived = Account.from_key(pk_plain).address
        logger.info(
            "trading_account resolved: name=%s funder=%s derived_from_pk=%s sig_type=%s",
            acc.name,
            acc.wallet_address,
            derived,
            sig_type,
        )
    except Exception as e:
        logger.warning("could not derive address from pk for account=%s: %s", acc.name, e)

    client = _build_authenticated_clob_client(
        key=pk_plain,
        signature_type=sig_type,
        funder=funder,
    )

    if use_cache:
        _ACCOUNT_CLIENT_CACHE[cache_key] = client
    return client


def fetch_question(condition_id, client: ClobClient = None):
    try:
        used_client = client or get_default_clob_client()
        market_info = used_client.get_market(condition_id=condition_id)
        #print(market_info)
        return market_info.get("question")
    except Exception as e:
        print(f"⚠️ Ошибка при получении market для {condition_id}: {e}")
        return None
    

class _OutcomeLike(Enum):
    YES = "YES"
    NO = "NO"
    UP = "UP"
    DOWN = "DOWN"

def get_asset_id_by_condition(condition_id: str, outcome: str, client: ClobClient = None) -> str:
    """
    Простой и явный резолв: берём `token_id` из `get_market().tokens` по нужному outcome.
    Поддерживаем синонимы UP→YES, DOWN→NO.
    """
    used_client = client or get_default_clob_client()
    oc = outcome.strip().lower()
    if oc == "up": oc = "yes"
    if oc == "down": oc = "no"

    market = used_client.get_market(condition_id=condition_id)
    if not market:
        raise ValueError(f"get_market returned empty for condition_id={condition_id}")

    tokens = market.get("tokens") or []
    for t in tokens:
        t_out = (t.get("outcome") or "").strip().lower()
        if t_out == "up":   t_out = "yes"
        if t_out == "down": t_out = "no"
        if t_out == oc:
            aid = t.get("token_id") or t.get("asset_id") or t.get("id")
            if aid:
                return str(aid)

    raise ValueError(
        f"Cannot resolve asset_id: condition_id={condition_id}, outcome={outcome}, "
        f"available_outcomes={[ (i.get('outcome'), i.get('token_id')) for i in tokens ]}"
    )    


def get_market_tick_size_by_asset_id(
    asset_id: str,
    client: ClobClient = None,
) -> Decimal | None:
    used_client = client or get_default_clob_client()
    aid = str(asset_id or "").strip()
    if not aid:
        return None

    raw_tick = None

    try:
        if hasattr(used_client, "get_tick_size") and callable(getattr(used_client, "get_tick_size")):
            raw_tick = used_client.get_tick_size(aid)
        elif hasattr(used_client, "getTickSize") and callable(getattr(used_client, "getTickSize")):
            raw_tick = used_client.getTickSize(aid)
    except Exception:
        raw_tick = None

    if raw_tick in (None, "", 0, "0"):
        try:
            book = used_client.get_order_book(aid)
            if isinstance(book, dict):
                raw_tick = (
                    book.get("tick_size")
                    or book.get("tickSize")
                    or book.get("minimum_tick_size")
                    or book.get("minimumTickSize")
                )
            else:
                raw_tick = (
                    getattr(book, "tick_size", None)
                    or getattr(book, "tickSize", None)
                    or getattr(book, "minimum_tick_size", None)
                    or getattr(book, "minimumTickSize", None)
                )
        except Exception:
            raw_tick = None

    if raw_tick in (None, "", 0, "0"):
        return None

    try:
        tick = Decimal(str(raw_tick))
        return tick if tick > 0 else None
    except Exception:
        return None


def get_midpoint_by_asset_id(
    asset_id: str,
    *,
    timeout: float = 10.0,
) -> Decimal | None:
    """
    Возвращает midpoint по token/asset_id через CLOB REST /midpoint.

    midpoint = average(best_bid, best_ask)

    Если midpoint отсутствует или не парсится — возвращает None.
    """
    aid = str(asset_id or "").strip()
    if not aid:
        return None

    url = "https://clob.polymarket.com/midpoint"
    params = {"token_id": aid}

    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() or {}

        raw_mid = (
            data.get("mid")
            or data.get("midpoint")
            or data.get("price")
        )
        if raw_mid in (None, "", "null"):
            return None

        return Decimal(str(raw_mid))
    except (InvalidOperation, ValueError, TypeError):
        logger.warning("get_midpoint_by_asset_id: bad midpoint payload asset_id=%s", aid)
        return None
    except Exception:
        logger.exception("get_midpoint_by_asset_id failed asset_id=%s", aid)
        return None


def get_midpoints_by_asset_ids(
    asset_ids: List[str],
    *,
    timeout: float = 15.0,
) -> Dict[str, Decimal | None]:
    """
    Batch midpoint fetch через CLOB REST /midpoints.

    Возвращает dict:
      {
        "<asset_id>": Decimal("0.53") | None,
        ...
      }
    """
    cleaned: List[str] = []
    for x in asset_ids or []:
        aid = str(x or "").strip()
        if aid:
            cleaned.append(aid)

    if not cleaned:
        return {}

    url = "https://clob.polymarket.com/midpoints"
    payload = [{"token_id": aid} for aid in cleaned]

    out: Dict[str, Decimal | None] = {aid: None for aid in cleaned}

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() or {}

        if isinstance(data, dict):
            for aid in cleaned:
                item = data.get(aid)

                raw_mid = None
                if isinstance(item, dict):
                    raw_mid = item.get("mid") or item.get("midpoint") or item.get("price")
                else:
                    raw_mid = item

                if raw_mid in (None, "", "null"):
                    out[aid] = None
                    continue

                try:
                    out[aid] = Decimal(str(raw_mid))
                except Exception:
                    out[aid] = None

        return out
    except Exception:
        logger.exception("get_midpoints_by_asset_ids failed asset_ids_count=%s", len(cleaned))
        return out

def adjust_limit_price_for_tick_size(
    limit_price: Decimal,
    tick_size: Decimal | None,
    side: str = "BUY",
) -> Decimal:
    """
    Корректирует limit_price под tick size.

    BUY:
      - округляем вниз, чтобы не отправить цену выше заданной.
      - 0.999 при tick=0.01 -> 0.99
      - 0.999 при tick=0.001 -> 0.999

    SELL:
      - округляем вверх, но clamp-им максимумом 1 - tick.
    """
    price = Decimal(str(limit_price))
    tick = Decimal(str(tick_size)) if tick_size is not None else None

    if tick is None or tick <= 0:
        if price > Decimal("0.99"):
            return Decimal("0.99")
        return price

    side_norm = str(side or "").strip().upper()

    if side_norm == "SELL":
        adjusted = (price / tick).to_integral_value(rounding=ROUND_UP) * tick
    else:
        adjusted = (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick

    min_price = tick
    max_price = Decimal("1") - tick

    if adjusted < min_price:
        adjusted = min_price
    if adjusted > max_price:
        adjusted = max_price

    return adjusted

def get_market_neg_risk_by_asset_id(
    asset_id: str,
    client: ClobClient = None,
) -> bool | None:
    used_client = client or get_default_clob_client()
    aid = str(asset_id or "").strip()
    if not aid:
        return None

    raw_neg_risk = None

    try:
        if hasattr(used_client, "get_neg_risk") and callable(getattr(used_client, "get_neg_risk")):
            raw_neg_risk = used_client.get_neg_risk(aid)
        elif hasattr(used_client, "getNegRisk") and callable(getattr(used_client, "getNegRisk")):
            raw_neg_risk = used_client.getNegRisk(aid)
    except Exception:
        raw_neg_risk = None

    if raw_neg_risk is None:
        try:
            book = used_client.get_order_book(aid)
            if isinstance(book, dict):
                raw_neg_risk = book.get("neg_risk")
                if raw_neg_risk is None:
                    raw_neg_risk = book.get("negRisk")
            else:
                raw_neg_risk = getattr(book, "neg_risk", None)
                if raw_neg_risk is None:
                    raw_neg_risk = getattr(book, "negRisk", None)
        except Exception:
            raw_neg_risk = None

    if raw_neg_risk is None:
        return None

    if isinstance(raw_neg_risk, str):
        return raw_neg_risk.strip().lower() in {"1", "true", "yes", "y"}
    return bool(raw_neg_risk)


def _side_to_v2(side: str):
    s = (side or "").upper()
    if s == "BUY":
        return Side.BUY
    if s == "SELL":
        return Side.SELL
    raise ValueError(f"Unsupported side={side!r}")


def _make_partial_create_order_options(
    *,
    tick_size: Decimal | str | None,
    neg_risk: bool | None = None,
):
    """
    V2 order options.
    В Python README явно указан tick_size; в docs для order options также нужен negRisk.
    Поэтому сначала пробуем передать оба значения, затем fallback на tick_size-only.
    """
    kwargs: dict[str, Any] = {}
    if tick_size is not None:
        kwargs["tick_size"] = str(tick_size)
    if neg_risk is not None:
        kwargs["neg_risk"] = bool(neg_risk)

    try:
        return PartialCreateOrderOptions(**kwargs)
    except TypeError:
        kwargs.pop("neg_risk", None)
        return PartialCreateOrderOptions(**kwargs)


def _make_post_orders_arg(*, order: Any, order_type: Any) -> Any:
    """
    post_orders в разных версиях SDK может принимать:
    - объект PostOrdersArgs(order=..., orderType=...)
    - plain dict {"order": ..., "orderType": ...}
    """
    if PostOrdersArgs is not None:
        try:
            return PostOrdersArgs(order=order, orderType=order_type)
        except TypeError:
            try:
                return PostOrdersArgs(order=order, order_type=order_type)
            except TypeError:
                pass

    return {"order": order, "orderType": order_type}


def _normalize_order_resp(resp: Any) -> dict:
    if isinstance(resp, dict):
        oid = resp.get("orderID") or resp.get("orderId") or resp.get("id") or resp.get("order_id")
        ok = bool(resp.get("success", bool(oid)))
        return {"success": ok, "orderID": oid, "raw": resp}
    return {"success": False, "orderID": None, "raw": resp}

def _normalize_batch_order_resp_item(item: Any) -> dict:
    """
    Нормализует один элемент ответа из post_orders().
    """
    if isinstance(item, dict):
        oid = item.get("orderID") or item.get("orderId") or item.get("id") or item.get("order_id")
        ok = bool(item.get("success", bool(oid)))
        return {"success": ok, "orderID": oid, "raw": item}
    return {"success": False, "orderID": None, "raw": item}


def _normalize_batch_orders_resp(resp: Any) -> dict:
    """
    Нормализует batch-ответ в единый вид:
    {
      "success": bool,
      "items": [{"success": bool, "orderID": ..., "raw": ...}, ...],
      "raw": resp,
    }
    """
    if isinstance(resp, list):
        items = []
        for i, x in enumerate(resp):
            row = _normalize_batch_order_resp_item(x)
            row["index"] = i
            items.append(row)
        return {
            "success": any(x["success"] for x in items),
            "items": items,
            "raw": resp,
        }

    if isinstance(resp, dict):
        raw_items = (
            resp.get("orders")
            or resp.get("items")
            or resp.get("results")
            or resp.get("data")
        )

        if isinstance(raw_items, list):
            items = []
            for i, x in enumerate(raw_items):
                row = _normalize_batch_order_resp_item(x)
                row["index"] = i
                items.append(row)
            return {
                "success": any(x["success"] for x in items),
                "items": items,
                "raw": resp,
            }

        single = _normalize_batch_order_resp_item(resp)
        return {
            "success": single["success"],
            "items": [single],
            "raw": resp,
        }

    return {"success": False, "items": [], "raw": resp}


def clob_supports_batch_orders(client: ClobClient = None) -> bool:
    used_client = client or get_default_clob_client()
    return (
        hasattr(used_client, "post_orders") and callable(getattr(used_client, "post_orders"))
    ) or (
        hasattr(used_client, "postOrders") and callable(getattr(used_client, "postOrders"))
    )


def _clob_place_orders_batch_with_client(
    *,
    client: ClobClient,
    orders: List[Dict[str, Any]],
) -> dict:
    """
    Batch submit нескольких already-described limit orders через CLOB V2.

    orders: [
      {
        "asset_id": "...",
        "side": "BUY" | "SELL",
        "size": Decimal(...),
        "limit_price": Decimal(...),
        "order_type": OrderType.GTC,    # optional, default GTC
        "tick_size": Decimal(...),      # optional
        "neg_risk": bool,               # optional
      },
      ...
    ]
    """
    try:
        payload: List[Any] = []

        for row in orders:
            asset_id = str(row["asset_id"])
            side = (row["side"] or "").upper()
            size = Decimal(str(row["size"]))
            limit_price = Decimal(str(row["limit_price"]))
            order_type = row.get("order_type", OrderType.GTC)
            tick_size = row.get("tick_size")
            neg_risk = row.get("neg_risk")

            if tick_size is None:
                tick_size = get_market_tick_size_by_asset_id(asset_id, client=client)
            if neg_risk is None:
                neg_risk = get_market_neg_risk_by_asset_id(asset_id, client=client)

            effective_price = adjust_limit_price_for_tick_size(
                limit_price,
                tick_size,
                side=side,
            )

            args = OrderArgs(
                price=float(effective_price),
                size=float(size),
                side=_side_to_v2(side),
                token_id=asset_id,
            )
            options = _make_partial_create_order_options(
                tick_size=tick_size,
                neg_risk=neg_risk,
            )

            if not (hasattr(client, "create_order") and callable(getattr(client, "create_order"))):
                raise RuntimeError("ClobClient has no create_order method")

            try:
                signed = client.create_order(args, options)
            except TypeError:
                signed = client.create_order(order_args=args, options=options)

            payload.append(_make_post_orders_arg(order=signed, order_type=order_type))

        if hasattr(client, "post_orders") and callable(getattr(client, "post_orders")):
            resp = client.post_orders(payload)
        elif hasattr(client, "postOrders") and callable(getattr(client, "postOrders")):
            resp = client.postOrders(payload)
        else:
            raise RuntimeError("ClobClient has no post_orders / postOrders method")

        return _normalize_batch_orders_resp(resp)

    except Exception as e:
        logger.exception("clob_place_orders_batch failed")
        return {"success": False, "items": [], "raw": f"{type(e).__name__}: {e}"}


def clob_place_orders_batch(orders: List[Dict[str, Any]]) -> dict:
    """
    Legacy: uses global env-based clob_client.
    """
    return _clob_place_orders_batch_with_client(
        client=get_default_clob_client(),
        orders=orders,
    )


def clob_place_orders_batch_for_account(
    *,
    account_name: str,
    orders: List[Dict[str, Any]],
) -> dict:
    """
    Batch submit через account-specific client из trading_accounts.
    """
    client = get_clob_client_for_account_name(account_name)
    try:
        return _clob_place_orders_batch_with_client(
            client=client,
            orders=orders,
        )
    except Exception as e:
        logger.exception("clob_place_orders_batch_for_account failed account=%s", account_name)
        return {"success": False, "items": [], "raw": f"{type(e).__name__}: {e}"}

def _clob_place_order_with_client(
    *,
    client: ClobClient,
    asset_id: str,
    side: str,
    size: Decimal,
    limit_price: Decimal,
) -> dict:
    """
    Разместить лимитный GTC-ордер через Polymarket CLOB V2.
    Возвращает {"success": bool, "orderID": str|None, "raw": dict}.
    """
    try:
        aid = str(asset_id)
        tick_size = get_market_tick_size_by_asset_id(aid, client=client)
        neg_risk = get_market_neg_risk_by_asset_id(aid, client=client)
        effective_price = adjust_limit_price_for_tick_size(
            Decimal(str(limit_price)),
            tick_size,
            side=side,
        )

        args = OrderArgs(
            price=float(effective_price),
            size=float(Decimal(str(size))),
            side=_side_to_v2(side),
            token_id=aid,
        )
        options = _make_partial_create_order_options(
            tick_size=tick_size,
            neg_risk=neg_risk,
        )

        if not (
            hasattr(client, "create_and_post_order")
            and callable(getattr(client, "create_and_post_order"))
        ):
            raise RuntimeError("ClobClient has no create_and_post_order method")

        try:
            resp = client.create_and_post_order(
                order_args=args,
                options=options,
                order_type=OrderType.GTC,
            )
        except TypeError:
            # На случай positional-only сигнатуры.
            resp = client.create_and_post_order(args, options, OrderType.GTC)

        return _normalize_order_resp(resp)
    except Exception as e:
        logger.exception("clob_place_order failed")
        return {"success": False, "orderID": None, "raw": f"{type(e).__name__}: {e}"}


def clob_place_order(*, asset_id: str, side: str, size: Decimal, limit_price: Decimal) -> dict:
    """
    Legacy: places order using global env-based clob_client.
    """
    return _clob_place_order_with_client(
        client=get_default_clob_client(),
        asset_id=asset_id,
        side=side,
        size=size,
        limit_price=limit_price,
    )

def clob_place_order_for_account(
    *,
    account_name: str,
    asset_id: str,
    side: str,
    size: Decimal,
    limit_price: Decimal,
) -> dict:
    """
    То же что clob_place_order, но использует CLOB client, созданный из trading_accounts (по name).
    """
    client = get_clob_client_for_account_name(account_name)
    try:
        return _clob_place_order_with_client(
            client=client,
            asset_id=asset_id,
            side=side,
            size=size,
            limit_price=limit_price,
        )
    except Exception as e:
        logger.exception("clob_place_order_for_account failed account=%s", account_name)
        return {"success": False, "orderID": None, "raw": f"{type(e).__name__}: {e}"}

def _make_cancel_order_payload(order_id: str) -> Any:
    """
    py_clob_client_v2.cancel_order() в некоторых версиях ждёт объект
    с атрибутом orderID, а не plain string.
    """
    oid = str(order_id or "").strip()

    if CancelOrderArgs is not None:
        for kwargs in (
            {"orderID": oid},
            {"order_id": oid},
            {"id": oid},
        ):
            try:
                return CancelOrderArgs(**kwargs)
            except TypeError:
                pass

    return SimpleNamespace(orderID=oid)


def clob_cancel_order(order_id: str) -> dict:
    """
    Отменить одиночный ордер по его ID через Polymarket CLOB V2.

    Возвращает:
        {"success": bool, "raw": any}
    """
    try:
        oid = (order_id or "").strip()
        if not oid:
            return {"success": False, "raw": "empty order_id"}

        client = get_default_clob_client()
        cancel_fn = None
        for name in ("cancel_order", "cancelOrder", "cancel"):
            fn = getattr(client, name, None)
            if callable(fn):
                cancel_fn = fn
                break

        if not cancel_fn:
            raise RuntimeError("ClobClient has no cancel_order / cancelOrder / cancel method")

        payload = _make_cancel_order_payload(oid)

        try:
            resp = cancel_fn(payload)
        except TypeError:
            # fallback для старых SDK, где cancel мог принимать строку
            resp = cancel_fn(oid)
        if isinstance(resp, dict):
            ok = bool(resp.get("success", True))
            return {"success": ok, "raw": resp}
        return {"success": True, "raw": resp}
    except Exception as e:
        logger.exception("clob_cancel_order failed for order_id=%s", order_id)
        return {"success": False, "raw": f"{type(e).__name__}: {e}"}

def clob_cancel_order_for_account(*, account_name: str, order_id: str) -> dict:
    """
    Cancel order using account-specific client from trading_accounts.
    """
    try:
        client = get_clob_client_for_account_name(account_name)
        oid = (order_id or "").strip()
        if not oid:
            return {"success": False, "raw": "empty order_id"}

        cancel_fn = None
        for name in ("cancel_order", "cancelOrder", "cancel"):
            fn = getattr(client, name, None)
            if callable(fn):
                cancel_fn = fn
                break

        if not cancel_fn:
            raise RuntimeError("ClobClient has no cancel_order / cancelOrder / cancel method")

        payload = _make_cancel_order_payload(oid)

        try:
            resp = cancel_fn(payload)
        except TypeError:
            # fallback для старых SDK, где cancel мог принимать строку
            resp = cancel_fn(oid)
        if isinstance(resp, dict):
            ok = bool(resp.get("success", True))
            return {"success": ok, "raw": resp}
        return {"success": True, "raw": resp}
    except Exception as e:
        logger.exception("clob_cancel_order_for_account failed account=%s order_id=%s", account_name, order_id)
        return {"success": False, "raw": f"{type(e).__name__}: {e}"}


def clob_get_order(order_id: str, client: ClobClient = None) -> dict:
    """
    Получить состояние ордера по ID через CLOB (py_clob_client), без fallback'ов.


    Возвращает нормализованную структуру:
      {
        "success": bool,
        "orderID": str,
        "status": str|None,          # OPEN / PARTIALLY_FILLED / FILLED / CANCELED / EXPIRED / ...
        "filled": Decimal|None,      # cumulative filled size
        "remaining": Decimal|None,
        "avg_price": Decimal|None,
        "raw": dict|str
      }
    """
    oid = (order_id or "").strip()
    if not oid:
        return {"success": False, "orderID": None, "status": None, "filled": None, "remaining": None, "avg_price": None, "raw": "empty order_id"}

    used_client = client or get_default_clob_client()

    def _d(x):
        try:
            if x is None:
                return None
            return Decimal(str(x))
        except Exception:
            return None

    def _norm(raw: Any) -> dict:
        if not isinstance(raw, dict):
            return {"success": False, "orderID": oid, "status": None, "filled": None, "remaining": None, "avg_price": None, "raw": raw}

        # некоторые версии/обёртки возвращают {"order": {...}}
        raw_order = raw.get("order") if isinstance(raw.get("order"), dict) else raw

        status = raw_order.get("status") or raw_order.get("state") or raw_order.get("orderStatus") or raw_order.get("order_status")
        # SDK get_order() в текущем проекте возвращает:
        # original_size, size_matched, price, associate_trades, ...
        filled = _d(raw_order.get("size_matched"))
        original = _d(raw_order.get("original_size"))
        remaining = (original - filled) if (original is not None and filled is not None) else None
        avg_price = _d(raw_order.get("avg_price"))

        return {
            "success": True,
            "orderID": raw_order.get("orderID") or raw_order.get("orderId") or raw_order.get("id") or raw_order.get("order_id") or oid,
            "status": str(status).upper() if status is not None else None,
            "filled": filled,
            "remaining": remaining,
            "avg_price": avg_price,
            "raw": raw,
        }

    try:
        if not (hasattr(used_client, "get_order") and callable(getattr(used_client, "get_order"))):
            raise RuntimeError("ClobClient has no get_order() method in this py_clob_client version")
        raw = used_client.get_order(oid)
        if raw is None:
            return {
                "success": False,
                "orderID": oid,
                "status": None,
                "filled": None,
                "remaining": None,
                "avg_price": None,
                "raw": None,
                "error": "SDK returned None (order not found / not accessible / wrong id format)",
            }
        return _norm(raw)
    except Exception as e:
        logger.exception("clob_get_order failed oid=%s", oid)
        return {"success": False, "orderID": oid, "status": None, "filled": None, "remaining": None, "avg_price": None, "raw": f"{type(e).__name__}: {e}"}

def clob_get_order_for_account(*, account_name: str, order_id: str) -> dict:
    """
    Get order using account-specific client from trading_accounts.
    """
    try:
        client = get_clob_client_for_account_name(account_name)
        return clob_get_order(order_id, client=client)
    except Exception as e:
        logger.exception("clob_get_order_for_account failed account=%s order_id=%s", account_name, order_id)
        oid = (order_id or "").strip() or None
        return {"success": False, "orderID": oid, "status": None, "filled": None, "remaining": None, "avg_price": None, "raw": f"{type(e).__name__}: {e}"}

def clob_get_active_orders(
    client: ClobClient = None,
    *,
    market: str | None = None,
    asset_id: str | None = None,
    order_id: str | None = None,
) -> dict:
    """
    Получить активные/open ордера через CLOB V2 SDK.

    Сохраняет старую сигнатуру проекта, но внутри пробует несколько вариантов SDK API:
    - get_open_orders / getOpenOrders
    - get_orders(OpenOrderParams(...))
    - get_orders(dict)
    """
    used_client = client or get_default_clob_client()

    def _extract_order_ids(raw: Any) -> list[str]:
        order_ids: list[str] = []
        rows = raw
        if isinstance(raw, dict):
            rows = raw.get("orders") or raw.get("data") or raw.get("results") or raw.get("items") or raw
        if isinstance(rows, list):
            for o in rows:
                if isinstance(o, dict):
                    oid = o.get("id") or o.get("orderID") or o.get("orderId") or o.get("order_id")
                    if oid:
                        order_ids.append(str(oid))
        elif isinstance(rows, dict):
            oid = rows.get("id") or rows.get("orderID") or rows.get("orderId") or rows.get("order_id")
            if oid:
                order_ids.append(str(oid))
        return order_ids

    try:
        raw = None

        if hasattr(used_client, "get_open_orders") and callable(getattr(used_client, "get_open_orders")):
            try:
                raw = used_client.get_open_orders()
            except TypeError:
                raw = used_client.get_open_orders(market=market, asset_id=asset_id, id=order_id)
        elif hasattr(used_client, "getOpenOrders") and callable(getattr(used_client, "getOpenOrders")):
            raw = used_client.getOpenOrders()
        elif hasattr(used_client, "get_orders") and callable(getattr(used_client, "get_orders")):
            if OpenOrderParams is not None:
                try:
                    params = OpenOrderParams(
                        market=market,
                        asset_id=asset_id,
                        id=order_id,
                    )
                    raw = used_client.get_orders(params)
                except TypeError:
                    raw = used_client.get_orders({
                        "market": market,
                        "asset_id": asset_id,
                        "id": order_id,
                    })
            else:
                raw = used_client.get_orders({
                    "market": market,
                    "asset_id": asset_id,
                    "id": order_id,
                })
        elif hasattr(used_client, "getOrders") and callable(getattr(used_client, "getOrders")):
            raw = used_client.getOrders({
                "market": market,
                "asset_id": asset_id,
                "id": order_id,
            })
        else:
            raise RuntimeError("ClobClient has no get_open_orders/get_orders method")

        return {"success": True, "raw": raw, "order_ids": _extract_order_ids(raw)}

    except Exception as e:
        logger.exception("clob_get_active_orders failed")
        return {"success": False, "raw": None, "error": f"{type(e).__name__}: {e}"}


def get_markets_by_end_date_range(start_date: str, end_date: str, limit: int = 1000) -> List[Dict]:
    """
    Получает рынки с end_date в заданном диапазоне (в формате ISO: 'YYYY-MM-DD').

    :param start_date: Минимальная дата окончания (включительно), например '2025-06-01'
    :param end_date: Максимальная дата окончания (включительно), например '2025-06-30'
    :param limit: Максимальное количество результатов за один запрос
    :return: Список рынков, удовлетворяющих условию
    """
    url = "https://gamma-api.polymarket.com/markets"
    offset = 0
    all_markets = []

    while True:
        params = {
            "end_date_min": f"{start_date}T00:00:00Z",
            "end_date_max": f"{end_date}T23:59:59Z",
            "limit": limit,
            "offset": offset
        }

        response = requests.get(url, params=params)
        response.raise_for_status()
        markets = response.json()

        if not markets:
            break

        all_markets.extend(markets)
        offset += limit

    return all_markets

def is_market_closed(condition_id: str) -> bool:
    """
    Проверяет, закрыт ли рынок по его condition_id.

    :param condition_id: Строковый идентификатор condition_id
    :return: True если рынок закрыт, False если нет или неизвестно
    """
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "condition_ids": condition_id
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        markets = response.json()

        if not markets:
            print(f"⚠️ Рынок с condition_id {condition_id} не найден.")
            return False

        market = markets[0]
        return market.get("closed", False)

    except Exception as e:
        print(f"⚠️ Ошибка при проверке состояния рынка {condition_id}: {e}")
        return False

def is_orderbook_enabled(condition_id: str) -> bool:
    """
    Проверяет, доступен ли рынок для торговли через order book (CLOB).

    :param condition_id: Строковый идентификатор condition_id
    :return: True если enableOrderBook == True, иначе False
    """
    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "condition_ids": condition_id
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        markets = response.json()

        if not markets:
            print(f"⚠️ Рынок с condition_id {condition_id} не найден.")
            return False

        market = markets[0]
        return market.get("enableOrderBook", False)

    except Exception as e:
        print(f"⚠️ Ошибка при проверке enableOrderBook для {condition_id}: {e}")
        return False
    
def filter_interesting_markets(markets: List[dict]) -> List[dict]:
    """
    Фильтрует рынки по вхождению ключевых шаблонов в вопросе.
    """
    keywords = [
        "Bitcoin Up or Down",
        "Ethereum Up or Down",
        "Solana Up or Down",
        "XRP Up or Down"
    ]

    result = []
    for m in markets:
        question = m.get("question", "")
        if any(kw in question for kw in keywords):
            result.append(m)
    return result

# -------------------- User info (profile) helpers --------------------
def fetch_user_activity(user: str, *, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Тянем последние события активности пользователя из Data API.
    Возвращает список событий (как есть от API).
    """
    # thin wrapper – реализация в одном месте
    return dah.fetch_user_activity(user, limit=limit)

def fetch_user_profile(user: str) -> Dict[str, Optional[str]]:
    """
    Достаём базовые метаданные пользователя ровно из ответа /activity:
    ожидаем поля на верхнем уровне события: name, pseudonym, bio, profileImage.
    Если в нескольких событиях поля пустые, берём первое непустое значение.
    """
    # thin wrapper – реализация в одном месте
    return dah.fetch_user_profile(user)


# --------------- Positions (Data-API) ---------------
def _data_api_get(path: str, params: Dict[str, Any], timeout: float = 15.0):
    """
    Back-compat helper. Реальная HTTP-логика и ретраи — в data_api_helpers.
    """
    url = f"{dah.DATA_API_BASE}/{path.lstrip('/')}"
    return dah._data_api_get_json(url, params=params)

def fetch_user_positions(user: str, *, market: str | None = None, limit: int = 200) -> List[Dict[str, Any]]:
    """
    Тянет текущие позиции пользователя (Data-API /positions).
    Можно ограничить конкретным рынком через market=condition_id.
    Возвращает список словарей позиций.
    """
    # thin wrapper – реализация в одном месте
    return dah.fetch_user_positions(user, market=market, limit=limit)

def fetch_user_positions_for_event(
    user: str,
    *,
    event_id: int,
    limit: int = 500,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Тянет текущие позиции пользователя сразу по всему event через Data-API /positions?eventId=...
    """
    return dah.fetch_user_positions_by_event(
        user=user,
        event_id=event_id,
        limit=limit,
        offset=offset,
    )

_POS_CACHE: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}
_POS_TTL_SEC = 30

def get_user_position_on_outcome(user: str, condition_id: str, outcome_index: int) -> Dict[str, Any] | None:
    """
    Удобный резолвер «позиции по токену»: ищем запись по condition_id + outcomeIndex.
    Возвращает dict с ключами: size, avgPrice, curPrice, cashPnl, outcome, outcomeIndex (или None).
    С лёгким TTL-кэшем (~30с) для снижения нагрузки на API.
    """
    # thin wrapper – реализация (включая TTL-кэш) в одном месте
    return dah.get_user_position_on_outcome(user=user, condition_id=condition_id, outcome_index=outcome_index)



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

    Возвращаем "сырые" dict'ы Data-API (или None), чтобы вызывающий код мог сам
    выбрать какие поля отображать (size, avgPrice, curPrice, cashPnl и т.д.).
    """
    # thin wrapper – реализация в одном месте
    return dah.get_yes_no_positions_for_condition_data_api(user=user, condition_id=condition_id)

def get_market_event_info(condition_id: str) -> Dict[str, Any] | None:
    """
    По condition_id достаёт краткую информацию о событии/рынке через Gamma /markets.
    Возвращает:
      {
        "condition_id": ...,
        "question": ...,
        "market_slug": ...,
        "event_id": ...,
        "event_title": ...,
        "event_slug": ...,
      }
    """
    cid = (condition_id or "").strip()
    if not cid:
        return None

    url = f"{config.POLYMARKET_GAMMA_API_BASE.rstrip('/')}/markets"
    params = {"condition_ids": cid}

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        markets = response.json()
        if not isinstance(markets, list) or not markets:
            return None

        m = markets[0] or {}

        nested_event = None
        if isinstance(m.get("event"), dict):
            nested_event = m.get("event")
        elif isinstance(m.get("events"), list) and m.get("events"):
            first_ev = m.get("events")[0]
            if isinstance(first_ev, dict):
                nested_event = first_ev

        event_id = (
            m.get("eventId")
            or m.get("event_id")
            or m.get("parentEvent")
            or m.get("parent_event")
            or (nested_event or {}).get("id")
        )

        event_title = (
            m.get("eventTitle")
            or m.get("event_title")
            or m.get("seriesName")
            or m.get("series_name")
            or (nested_event or {}).get("title")
            or (nested_event or {}).get("name")
        )

        event_slug = (
            m.get("eventSlug")
            or m.get("event_slug")
            or (nested_event or {}).get("slug")
        )

        return {
            "condition_id": cid,
            "question": m.get("question"),
            "market_slug": m.get("market_slug") or m.get("slug"),
            "event_id": event_id,
            "event_title": event_title,
            "event_slug": event_slug,
        }
    except Exception:
        logger.exception("get_market_event_info failed for condition_id=%s", cid)
        return None