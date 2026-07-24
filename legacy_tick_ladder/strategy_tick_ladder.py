from __future__ import annotations

import threading
import logging
from typing import Any

from logic.strategy_engine import StrategyBase
from logic.trading_core import (
    parse_tick_ladder_config,
    tick_matches,
    build_tick_size_change_event_key,
    insert_marketchanel_event,
    has_existing_tick_ladder_orders,
    upsert_order_meta,
    mark_instance_completed,
    mark_instance_failed,
)

logger = logging.getLogger(__name__)


class Strategy_TickLadder(StrategyBase):
    KIND = "tick_ladder"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._lock = threading.RLock()

    def on_market_event(self, asset_id: str, event: dict):
        et = str((event or {}).get("event_type") or (event or {}).get("type") or "").strip().lower()
        if et != "tick_size_change":
            return

        with self._lock:
            s = self.ctx.session_factory()
            try:
                from models.t_strategy_instance import StrategyInstance

                inst = (
                    s.query(StrategyInstance)
                    .filter(StrategyInstance.id == self.instance_id)
                    .one_or_none()
                )
                if not inst:
                    return

                runtime_state = dict(inst.runtime_state or {})
                params = dict(inst.params or {})

                # Жёсткий guard: завершённый инстанс не должен срабатывать повторно
                raw_status = getattr(inst, "status", None)
                status_name = getattr(raw_status, "name", str(raw_status))
                status_name = str(status_name or "").strip().upper()

                if status_name in {"COMPLETED", "FAILED", "CANCELLED"}:
                    runtime_state["skip_reason"] = f"instance_status_{status_name.lower()}"
                    runtime_state["last_trigger_event"] = dict(event or {})

                    if status_name == "COMPLETED":
                        runtime_state["phase"] = "COMPLETED"
                    elif status_name == "FAILED":
                        runtime_state["phase"] = "FAILED"
                    elif status_name == "CANCELLED":
                        runtime_state["phase"] = "CANCELLED"

                    inst.runtime_state = runtime_state
                    s.commit()
                    return

                try:
                    cfg = parse_tick_ladder_config(params)
                except Exception as e:
                    runtime_state["config_error"] = str(e)
                    runtime_state["last_trigger_event"] = dict(event or {})
                    mark_instance_failed(
                        s,
                        inst=inst,
                        close_reason="tick_ladder_bad_config",
                        runtime_state=runtime_state,
                    )
                    s.commit()
                    logger.exception("tick_ladder bad config for instance_id=%s", self.instance_id)
                    return

                if str(asset_id) != str(cfg.asset_id):
                    return

                if not tick_matches(
                    event,
                    old_tick=cfg.trigger_old_tick,
                    new_tick=cfg.trigger_new_tick,
                ):
                    return

                event_key = f"{build_tick_size_change_event_key(event)}:{inst.id}"

                inserted = insert_marketchanel_event(
                    s,
                    event_type="tick_size_change",
                    event_key=event_key,
                    payload={
                        "asset_id": str(asset_id),
                        "market": event.get("market"),
                        "old_tick_size": event.get("old_tick_size"),
                        "new_tick_size": event.get("new_tick_size"),
                        "timestamp": event.get("timestamp"),
                    },
                    raw_event=dict(event or {}),
                    source="market_channel",
                    asset_id=str(asset_id),
                    market=(str(event.get("market")).strip() if event.get("market") is not None else None),
                    instance_id=str(inst.id),
                )
                if not inserted:
                    runtime_state["skip_reason"] = "duplicate_marketchanel_event"
                    runtime_state["last_trigger_event"] = dict(event or {})
                    inst.runtime_state = runtime_state
                    s.commit()
                    return

                if has_existing_tick_ladder_orders(s, instance_id=str(inst.id)):
                    runtime_state["skip_reason"] = "existing_tick_ladder_orders"
                    runtime_state["last_trigger_event"] = dict(event or {})
                    runtime_state["phase"] = "COMPLETED"
                    mark_instance_completed(
                        s,
                        inst=inst,
                        close_reason="tick_ladder_already_placed",
                        runtime_state=runtime_state,
                    )
                    s.commit()
                    self.ctx.send_tg(
                        cfg.notify_chat,
                        f"⏭ [{self.name}] tick_ladder skipped: orders already exist for instance={inst.name}",
                        inst_params=params,
                    )
                    return

                try:
                    placed = []
                    failed = []

                    for idx, level in enumerate(cfg.levels):
                        res = self.ctx.place_order(
                            asset_id=cfg.asset_id,
                            side=cfg.side,
                            size=level.size,
                            limit_price=level.price,
                        )

                        ok = bool((res or {}).get("success"))
                        order_id = (res or {}).get("orderID")

                        if ok and order_id:
                            upsert_order_meta(
                                s,
                                instance_id=str(inst.id),
                                order_id=str(order_id),
                                side=cfg.side,
                                price=level.price,
                                size=level.size,
                                tag=f"tick_ladder:L{idx}",
                                place_note="tick_size_change_entry",
                                status="NEW",
                            )
                            placed.append(
                                {
                                    "order_id": str(order_id),
                                    "price": str(level.price),
                                    "size": str(level.size),
                                    "tag": f"tick_ladder:L{idx}",
                                }
                            )
                        else:
                            failed.append(
                                {
                                    "price": str(level.price),
                                    "size": str(level.size),
                                    "raw": res,
                                    "tag": f"tick_ladder:L{idx}",
                                }
                            )

                    runtime_state["last_trigger_event"] = dict(event or {})
                    runtime_state["placed_orders"] = placed
                    runtime_state["failed_orders"] = failed
                    runtime_state["phase"] = "COMPLETED" if placed else "FAILED"

                except Exception as e:
                    runtime_state["last_trigger_event"] = dict(event or {})
                    runtime_state["place_exception"] = str(e)
                    runtime_state["phase"] = "FAILED"
                    mark_instance_failed(
                        s,
                        inst=inst,
                        close_reason="tick_ladder_exception",
                        runtime_state=runtime_state,
                    )
                    s.commit()
                    logger.exception("tick_ladder exception for instance_id=%s", self.instance_id)
                    self.ctx.send_tg(
                        cfg.notify_chat,
                        f"⛔ [{self.name}] tick_ladder exception: {e}",
                        inst_params=params,
                    )
                    return

                if placed:
                    mark_instance_completed(
                        s,
                        inst=inst,
                        close_reason=(
                            "tick_ladder_placed"
                            if not failed else
                            "tick_ladder_partial"
                        ),
                        runtime_state=runtime_state,
                    )
                    s.commit()

                    lines = [
                        f"🚀 [{self.name}] tick_ladder fired",
                        f"• instance: {inst.name}",
                        f"• asset_id: {cfg.asset_id}",
                        f"• trigger: {cfg.trigger_old_tick} -> {cfg.trigger_new_tick}",
                        f"• event_key: {event_key}",
                        f"• placed: {len(placed)}",
                    ]
                    for row in placed:
                        lines.append(
                            f"  - {row['tag']}: {cfg.side} {row['size']} @ {row['price']} (order_id={row['order_id']})"
                        )
                    if failed:
                        lines.append(f"• failed: {len(failed)}")

                    self.ctx.send_tg(cfg.notify_chat, "\n".join(lines), inst_params=params)
                    return

                runtime_state["phase"] = "FAILED"
                mark_instance_failed(
                    s,
                    inst=inst,
                    close_reason="tick_ladder_place_failed",
                    runtime_state=runtime_state,
                )
                s.commit()

                self.ctx.send_tg(
                    cfg.notify_chat,
                    (
                        f"⛔ [{self.name}] tick_ladder failed\n"
                        f"• instance: {inst.name}\n"
                        f"• asset_id: {cfg.asset_id}\n"
                        f"• trigger: {cfg.trigger_old_tick} -> {cfg.trigger_new_tick}\n"
                        f"• all place attempts failed"
                    ),
                    inst_params=params,
                )
            finally:
                s.close()