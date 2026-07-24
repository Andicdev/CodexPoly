from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from models.t_strategy_instance import StrategyInstance, StrategyInstanceStatus
from models.t_order_meta import OrderMeta
from models.t_marketchanel_event import MarketchanelEvent


def _d(v: Any) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


@dataclass
class LadderLevel:
    price: Decimal
    size: Decimal


class TickLadderConfig:
    def __init__(
        self,
        *,
        asset_id: str,
        side: str,
        trigger_old_tick: Decimal,
        trigger_new_tick: Decimal,
        levels: List[LadderLevel],
        notify_chat: Optional[str] = None,
    ):
        self.asset_id = asset_id
        self.side = side
        self.trigger_old_tick = trigger_old_tick
        self.trigger_new_tick = trigger_new_tick
        self.levels = levels
        self.notify_chat = notify_chat


def parse_tick_ladder_config(params: dict) -> TickLadderConfig:
    p = dict(params or {})

    asset_id = str(p.get("asset_id") or p.get("assetId") or "").strip()
    if not asset_id:
        raise ValueError("tick_ladder: params.asset_id is required")

    side = str(p.get("side") or "BUY").strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("tick_ladder: params.side must be BUY or SELL")

    trigger_old_tick = _d(p.get("trigger_old_tick") or "0.01")
    trigger_new_tick = _d(p.get("trigger_new_tick") or "0.001")
    if trigger_old_tick is None or trigger_new_tick is None:
        raise ValueError("tick_ladder: trigger_old_tick/trigger_new_tick are required")

    raw_levels = p.get("levels")
    if not isinstance(raw_levels, list) or not raw_levels:
        raise ValueError("tick_ladder: params.levels must be a non-empty list")

    levels: List[LadderLevel] = []
    for i, row in enumerate(raw_levels):
        if not isinstance(row, dict):
            raise ValueError(f"tick_ladder: levels[{i}] must be an object")
        price = _d(row.get("price"))
        size = _d(row.get("size"))
        if price is None or size is None:
            raise ValueError(f"tick_ladder: levels[{i}] must contain price and size")
        if price <= 0 or price >= 1:
            raise ValueError(f"tick_ladder: levels[{i}].price must be between 0 and 1")
        if size <= 0:
            raise ValueError(f"tick_ladder: levels[{i}].size must be > 0")
        levels.append(LadderLevel(price=price, size=size))

    # сначала самая высокая цена
    levels.sort(key=lambda x: x.price, reverse=True)

    notify_chat = p.get("notify_chat")
    if notify_chat is not None:
        notify_chat = str(notify_chat).strip() or None

    return TickLadderConfig(
        asset_id=asset_id,
        side=side,
        trigger_old_tick=trigger_old_tick,
        trigger_new_tick=trigger_new_tick,
        levels=levels,
        notify_chat=notify_chat,
    )


def tick_matches(event: dict, *, old_tick: Decimal, new_tick: Decimal) -> bool:
    ev_old = _d((event or {}).get("old_tick_size"))
    ev_new = _d((event or {}).get("new_tick_size") or (event or {}).get("tick_size"))
    return ev_old == old_tick and ev_new == new_tick

def build_tick_size_change_event_key(event: dict) -> str:
    e = dict(event or {})
    asset_id = str(e.get("asset_id") or "").strip()
    old_tick = str(e.get("old_tick_size") or "").strip()
    new_tick = str(e.get("new_tick_size") or e.get("tick_size") or "").strip()
    ts = str(e.get("timestamp") or e.get("ts") or "").strip()
    return f"tick_size_change:{asset_id}:{old_tick}:{new_tick}:{ts}"

def insert_marketchanel_event(
    session,
    *,
    event_type: str,
    event_key: str,
    payload: dict,
    raw_event: dict | None = None,
    source: str = "market_channel",
    asset_id: str | None = None,
    market: str | None = None,
    condition_id: str | None = None,
    instance_id: str | None = None,
) -> bool:
    """
    Возвращает:
      True  -> событие вставлено впервые
      False -> дубль по unique(event_type, event_key)
    """
    row = MarketchanelEvent(
        source=source,
        event_type=str(event_type),
        event_key=str(event_key),
        asset_id=(str(asset_id).strip() if asset_id is not None else None),
        market=(str(market).strip() if market is not None else None),
        condition_id=(str(condition_id).strip() if condition_id is not None else None),
        instance_id=(str(instance_id).strip() if instance_id is not None else None),
        payload=dict(payload or {}),
        raw_event=dict(raw_event or payload or {}),
    )
    session.add(row)
    try:
        session.flush()
        return True
    except IntegrityError:
        session.rollback()
        return False


def has_existing_tick_ladder_orders(session, *, instance_id: str) -> bool:
    row = (
        session.query(OrderMeta.order_id)
        .filter(OrderMeta.strategy_instance_id == str(instance_id))
        .filter(OrderMeta.intent == "TICK_LADDER_ENTRY")
        .first()
    )
    return row is not None


def upsert_order_meta(
    session,
    *,
    instance_id: str,
    order_id: str,
    side: str,
    price: Decimal,
    size: Decimal,
    tag: str,
    place_note: str,
    parent_order_id: str | None = None,
    status: str = "NEW",
) -> None:
    session.merge(
        OrderMeta(
            order_id=str(order_id),
            strategy_instance_id=str(instance_id),
            intent="TICK_LADDER_ENTRY",
            tag=tag,
            status=status,
            requested_side=side,
            requested_price=price,
            requested_size=size,
            place_note=place_note,
            parent_order_id=parent_order_id,
        )
    )


def mark_instance_completed(
    session,
    *,
    inst: StrategyInstance,
    close_reason: str,
    runtime_state: Optional[dict] = None,
) -> None:
    inst.status = StrategyInstanceStatus.COMPLETED
    inst.close_reason = close_reason
    if runtime_state is not None:
        inst.runtime_state = runtime_state
    try:
        inst.updated_at = func.now()
    except Exception:
        pass


def mark_instance_failed(
    session,
    *,
    inst: StrategyInstance,
    close_reason: str,
    runtime_state: Optional[dict] = None,
) -> None:
    inst.status = StrategyInstanceStatus.FAILED
    inst.close_reason = close_reason
    if runtime_state is not None:
        inst.runtime_state = runtime_state
    try:
        inst.updated_at = func.now()
    except Exception:
        pass