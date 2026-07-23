# news_trade/eps_orders.py
from __future__ import annotations

from decimal import Decimal as D
from typing import Any, Mapping
from common.logger import get_logger


from common.polymarket_utils import (
    get_clob_client_for_account_name,
    get_asset_id_by_condition,
    clob_place_order_for_account,
    clob_place_orders_batch_for_account,
)

logger = get_logger(__name__)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """
    Read from SQLAlchemy model (attr) or dict-like.
    """
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def should_place_trade(row: Any, decision: str) -> tuple[bool, str]:
    """
    Returns (ok, reason_or_decision).
    """
    decision = (decision or "").strip().upper()
    if decision not in {"YES", "NO"}:
        return False, f"decision={decision}"

    account = (_get(row, "account_name") or "").strip()
    condition_id = (_get(row, "condition_id") or "").strip()
    qty_v = _get(row, "order_qty")
    price_v = _get(row, "order_price")

    if not account or not condition_id:
        return False, "missing account_name/condition_id"
    if qty_v is None or price_v is None:
        return False, "missing order_qty/order_price"

    logger.info(
        "should_place_trade account=%s condition_id=%s decision=%s qty=%r price=%r row_type=%s",
        account,
        condition_id,
        decision,
        qty_v,
        price_v,
        type(row).__name__,
    )

    return True, decision


def place_trade_for_decision(row: Any, decision: str) -> dict:
    """
    Places BUY order for YES/NO based on decision.
    row can be MonitoredNews instance OR dict from ws_eps._load_row_for_ticker().
    """
    ok, reason = should_place_trade(row, decision)
    if not ok:
        return {"success": False, "skipped": True, "reason": reason}

    decision = reason  # normalized YES/NO
    outcome = "YES" if decision == "YES" else "NO"

    account = str(_get(row, "account_name")).strip()
    condition_id = str(_get(row, "condition_id")).strip()
    qty = D(str(_get(row, "order_qty")))
    price = D(str(_get(row, "order_price")))

    logger.info(
        "place_trade_for_decision input account=%s condition_id=%s decision=%s outcome=%s qty=%s price=%s "
        "rule=%r params=%r",
        account,
        condition_id,
        decision,
        outcome,
        qty,
        price,
        _get(row, "rule_key"),
        _get(row, "params"),
    )

    # Resolve asset_id using the same account client (safer for auth/config)
    client = get_clob_client_for_account_name(account)
    asset_id = get_asset_id_by_condition(condition_id, outcome, client=client)

    logger.info(
        "place_trade_for_decision resolved_asset account=%s condition_id=%s outcome=%s asset_id=%s price=%s qty=%s",
        account,
        condition_id,
        outcome,
        asset_id,
        price,
        qty,
    )

    resp = clob_place_order_for_account(
        account_name=account,
        asset_id=str(asset_id),
        side="BUY",
        size=qty,
        limit_price=price,
    )

    logger.info(
        "place_trade_for_decision response account=%s condition_id=%s outcome=%s asset_id=%s price=%s qty=%s success=%r orderID=%r raw=%r",
        account,
        condition_id,
        outcome,
        asset_id,
        price,
        qty,
        resp.get("success"),
        resp.get("orderID"),
        resp.get("raw"),
    )

    return {
        "success": bool(resp.get("success")),
        "orderID": resp.get("orderID"),
        "account_name": account,
        "condition_id": condition_id,
        "outcome": outcome,
        "asset_id": str(asset_id),
        "side": "BUY",
        "size": float(qty),
        "price": float(price),
        "raw": resp.get("raw"),
    }

def build_batch_order_for_decision(row: Any, decision: str) -> dict:
    """
    Готовит один batch-order item из monitored row + YES/NO decision,
    но не отправляет его.
    Возвращает:
      {
        "success": True/False,
        "skipped": bool,
        "reason": "...",
        "account_name": "...",
        "condition_id": "...",
        "outcome": "YES"/"NO",
        "asset_id": "...",
        "order": {
            "asset_id": "...",
            "side": "BUY",
            "size": Decimal(...),
            "limit_price": Decimal(...),
        }
      }
    """
    ok, reason = should_place_trade(row, decision)
    if not ok:
        return {"success": False, "skipped": True, "reason": reason}

    decision = reason
    outcome = "YES" if decision == "YES" else "NO"

    account = str(_get(row, "account_name")).strip()
    condition_id = str(_get(row, "condition_id")).strip()
    qty = D(str(_get(row, "order_qty")))
    price = D(str(_get(row, "order_price")))

    logger.info(
        "build_batch_order_for_decision input account=%s condition_id=%s decision=%s outcome=%s qty=%s price=%s "
        "rule=%r params=%r",
        account,
        condition_id,
        decision,
        outcome,
        qty,
        price,
        _get(row, "rule_key"),
        _get(row, "params"),
    )

    client = get_clob_client_for_account_name(account)
    asset_id = get_asset_id_by_condition(condition_id, outcome, client=client)

    logger.info(
        "build_batch_order_for_decision resolved_asset account=%s condition_id=%s outcome=%s asset_id=%s price=%s qty=%s",
        account,
        condition_id,
        outcome,
        asset_id,
        price,
        qty,
    )

    return {
        "success": True,
        "skipped": False,
        "account_name": account,
        "condition_id": condition_id,
        "outcome": outcome,
        "asset_id": str(asset_id),
        "side": "BUY",
        "size": float(qty),
        "price": float(price),
        "order": {
            "asset_id": str(asset_id),
            "side": "BUY",
            "size": qty,
            "limit_price": price,
        },
    }

def place_trades_batch_for_account(prepared: list[dict]) -> dict:
    """
    Отправляет пачку уже подготовленных order items через post_orders batch.
    Все prepared-элементы должны относиться к одному account_name.
    """
    rows = [x for x in (prepared or []) if x and x.get("success") and not x.get("skipped")]
    if not rows:
        return {"success": False, "skipped": True, "reason": "empty_prepared_batch", "items": []}

    accounts = {str(x.get("account_name") or "").strip() for x in rows}
    if len(accounts) != 1:
        return {
            "success": False,
            "skipped": True,
            "reason": f"mixed_accounts_in_batch={sorted(accounts)}",
            "items": rows,
        }

    account = next(iter(accounts))
    orders = [x["order"] for x in rows]

    logger.info(
        "place_trades_batch_for_account account=%s batch_size=%s condition_ids=%s",
        account,
        len(orders),
        [x.get("condition_id") for x in rows],
    )

    resp = clob_place_orders_batch_for_account(
        account_name=account,
        orders=orders,
    )

    items = list(resp.get("items") or [])
    results = []
    for idx, prepared_item in enumerate(rows):
        item_resp = items[idx] if idx < len(items) else {}
        results.append(
            {
                "success": bool(item_resp.get("success")),
                "orderID": item_resp.get("orderID"),
                "account_name": prepared_item.get("account_name"),
                "condition_id": prepared_item.get("condition_id"),
                "outcome": prepared_item.get("outcome"),
                "asset_id": prepared_item.get("asset_id"),
                "side": prepared_item.get("side"),
                "size": prepared_item.get("size"),
                "price": prepared_item.get("price"),
                "raw": item_resp.get("raw"),
            }
        )

    logger.info(
        "place_trades_batch_for_account response account=%s success=%r results=%r raw=%r",
        account,
        resp.get("success"),
        results,
        resp.get("raw"),
    )

    return {
        "success": bool(resp.get("success")),
        "account_name": account,
        "results": results,
        "raw": resp.get("raw"),
    }

def place_trade_from_eps_out(row: Any, out: dict) -> dict:
    """
    Reads decision from eps out-dict and places trade if possible.
    """
    r = (out or {}).get("result") or {}
    decision = (r.get("decision") or "").strip().upper()
    return place_trade_for_decision(row, decision)