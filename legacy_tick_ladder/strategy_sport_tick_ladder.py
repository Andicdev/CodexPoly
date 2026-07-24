from __future__ import annotations

import logging
import os
import threading
from decimal import Decimal, ROUND_DOWN
from typing import Any

from logic.strategy_engine import StrategyBase
from logic.trading_core import (
    tick_matches,
    build_tick_size_change_event_key,
    insert_marketchanel_event,
    upsert_order_meta,
    mark_instance_completed,
    mark_instance_failed,
)
from common.polymarket_utils import get_market_tick_size_by_asset_id

from common.sport_condition_ordering import (
    DEFAULT_BUDGET_ROUND_USD,
    DEFAULT_FREE_BALANCE_USAGE_PCT,
    DEFAULT_MIN_BUDGET_USD,
    floor_usd_to_budget,
    get_free_collateral_for_account,
    place_sport_orders_for_asset,
    parse_bool,
)

logger = logging.getLogger(__name__)


class Strategy_SportTickLadder(StrategyBase):
    """
    Отдельный sport-contour tick ladder.

    Отличие от обычного tick_ladder:
    - не использует fixed levels как торговый план;
    - при 0.01 -> 0.001 отменяет предыдущие open-orders по asset/account;
    - ставит новые ордера через ту же sport-condition order logic:
      budget -> chunks -> size=budget/price -> CLOB order.
    """

    KIND = "sport_tick_ladder"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._lock = threading.RLock()

    @staticmethod
    def _first_level(params: dict[str, Any]) -> dict[str, Any]:
        levels = params.get("levels") or []
        if isinstance(levels, list) and levels and isinstance(levels[0], dict):
            return dict(levels[0])
        return {}

    @classmethod
    def _param(cls, params: dict[str, Any], key: str, default: Any = None) -> Any:
        """
        create_tick_ladder_instance_for_condition точно сохраняет стандартные поля.
        Дополнительные sport-поля мы кладём и top-level, и в levels[0].
        Если helper где-то не перенесёт top-level, пробуем достать из levels[0].
        """
        if key in params and params.get(key) not in (None, ""):
            return params.get(key)
        first = cls._first_level(params)
        if key in first and first.get(key) not in (None, ""):
            return first.get(key)
        return default

    @staticmethod
    def _is_price_aligned_to_tick(price: Decimal, tick: Decimal) -> bool:
        if tick <= 0:
            return False
        try:
            units = price / tick
            return units == units.to_integral_value()
        except Exception:
            return False

    @classmethod
    def _parse_price(cls, value: Any) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            d = Decimal(str(value))
        except Exception:
            return None
        if d < 0 or d > 1:
            return None
        return d

    @classmethod
    def _extract_price_from_row(cls, row: Any) -> Decimal | None:
        if isinstance(row, dict):
            for key in (
                "price",
                "p",
                "px",
                "bid",
                "ask",
                "best_bid",
                "bestBid",
                "best_ask",
                "bestAsk",
                "best_bid_price",
                "bestBidPrice",
                "best_ask_price",
                "bestAskPrice",
            ):
                d = cls._parse_price(row.get(key))
                if d is not None:
                    return d
        if isinstance(row, (list, tuple)) and row:
            return cls._parse_price(row[0])
        return cls._parse_price(row)

    @classmethod
    def _iter_price_evidence_candidates(cls, event: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract candidate bid/ask/orderbook prices from a market event.

        This intentionally looks only at price-like fields and book/level rows,
        so sizes and amounts do not accidentally become tick evidence.
        """
        if not isinstance(event, dict):
            return []

        out: list[dict[str, Any]] = []

        def add(value: Any, source: str) -> None:
            d = cls._parse_price(value)
            if d is not None:
                out.append({"price": d, "source": source})

        def add_row(row: Any, source: str) -> None:
            d = cls._extract_price_from_row(row)
            if d is not None:
                out.append({"price": d, "source": source})

        direct_keys = (
            "price",
            "p",
            "px",
            "bid",
            "ask",
            "best_bid",
            "bestBid",
            "best_ask",
            "bestAsk",
            "best_bid_price",
            "bestBidPrice",
            "best_ask_price",
            "bestAskPrice",
        )
        for key in direct_keys:
            if key in event:
                add(event.get(key), f"event.{key}")

        containers: list[tuple[str, Any]] = [("event", event)]
        for container_key in ("book", "orderbook", "order_book", "payload", "data"):
            container = event.get(container_key)
            if isinstance(container, dict):
                containers.append((f"event.{container_key}", container))

        for prefix, container in containers:
            if not isinstance(container, dict):
                continue

            for side_key in ("bids", "asks", "buy", "sell", "BUY", "SELL"):
                rows = container.get(side_key)
                if isinstance(rows, dict):
                    rows = rows.get("orders") or rows.get("items") or rows.get("levels") or list(rows.values())
                if isinstance(rows, list):
                    for idx, row in enumerate(rows):
                        add_row(row, f"{prefix}.{side_key}[{idx}]")

            # Polymarket price_change-like payloads may contain changed levels/orders.
            for rows_key in ("changes", "orders", "levels", "items"):
                rows = container.get(rows_key)
                if isinstance(rows, list):
                    for idx, row in enumerate(rows):
                        add_row(row, f"{prefix}.{rows_key}[{idx}]")

        return out

    @classmethod
    def _find_fine_tick_price_evidence(
        cls,
        event: dict[str, Any],
        *,
        old_tick: Decimal,
        new_tick: Decimal,
    ) -> dict[str, Any] | None:
        """
        Returns evidence that market prices already use the finer tick.

        Example for 0.01 -> 0.001:
          0.31   is aligned to 0.01  => no evidence
          0.311  is not aligned to 0.01 but aligned to 0.001 => evidence
        """
        if old_tick <= 0 or new_tick <= 0:
            return None

        for item in cls._iter_price_evidence_candidates(event):
            price = item.get("price")
            if not isinstance(price, Decimal):
                continue
            if cls._is_price_aligned_to_tick(price, old_tick):
                continue
            if not cls._is_price_aligned_to_tick(price, new_tick):
                continue
            return {
                "price": str(price),
                "source": item.get("source"),
                "old_tick": str(old_tick),
                "new_tick": str(new_tick),
                "reason": "price_aligned_to_new_tick_not_old_tick",
            }

        return None

    def on_market_event(self, asset_id: str, event: dict):
        event = dict(event or {})
        et = str(event.get("event_type") or event.get("type") or "").strip().lower()

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

                raw_status = getattr(inst, "status", None)
                status_name = getattr(raw_status, "name", str(raw_status))
                status_name = str(status_name or "").strip().upper()

                if status_name in {"COMPLETED", "FAILED", "CANCELLED"}:
                    runtime_state["skip_reason"] = f"instance_status_{status_name.lower()}"
                    runtime_state["last_trigger_event"] = dict(event or {})
                    runtime_state["phase"] = status_name
                    inst.runtime_state = runtime_state
                    s.commit()
                    return

                cfg_asset_id = str(self._param(params, "asset_id", "") or "").strip()
                condition_id = str(self._param(params, "condition_id", "") or "").strip()
                account_name = str(self._param(params, "account_name", "") or "").strip()
                side = str(self._param(params, "side", "BUY") or "BUY").strip().upper()
                order_price = self._dec(
                    self._param(params, "sport_order_price", None),
                    default=self._dec(self._param(params, "order_price", None), Decimal("0.999")),
                )
                trigger_old_tick = self._dec(
                    self._param(params, "trigger_old_tick", "0.01"),
                    Decimal("0.01"),
                ) or Decimal("0.01")
                trigger_new_tick = self._dec(
                    self._param(params, "trigger_new_tick", "0.001"),
                    Decimal("0.001"),
                ) or Decimal("0.001")
                notify_chat = self._param(params, "notify_chat", None) or os.getenv("SPORT_TICK_LADDER_NOTIFY_CHAT")

                if not cfg_asset_id or not condition_id or not account_name or order_price is None:
                    runtime_state["config_error"] = {
                        "asset_id": cfg_asset_id,
                        "condition_id": condition_id,
                        "account_name": account_name,
                        "order_price": str(order_price) if order_price is not None else None,
                    }
                    runtime_state["last_trigger_event"] = dict(event or {})
                    mark_instance_failed(
                        s,
                        inst=inst,
                        close_reason="sport_tick_ladder_bad_config",
                        runtime_state=runtime_state,
                    )
                    s.commit()
                    return

                if str(asset_id) != str(cfg_asset_id):
                    runtime_state["skip_reason"] = "asset_id_mismatch"
                    runtime_state["event_asset_id"] = str(asset_id)
                    runtime_state["cfg_asset_id"] = str(cfg_asset_id)
                    runtime_state["last_trigger_event"] = dict(event or {})
                    inst.runtime_state = runtime_state
                    s.commit()
                    return

                trigger_event = dict(event or {})
                trigger_source = "tick_size_change"
                tick_evidence: dict[str, Any] | None = None
                confirmed_tick_size: Decimal | None = None

                if et == "tick_size_change":
                    if not tick_matches(
                        trigger_event,
                        old_tick=trigger_old_tick,
                        new_tick=trigger_new_tick,
                    ):
                        runtime_state["skip_reason"] = "tick_size_mismatch"
                        runtime_state["expected_old_tick"] = str(trigger_old_tick)
                        runtime_state["expected_new_tick"] = str(trigger_new_tick)
                        runtime_state["event_old_tick"] = str((trigger_event or {}).get("old_tick_size"))
                        runtime_state["event_new_tick"] = str((trigger_event or {}).get("new_tick_size") or (trigger_event or {}).get("tick_size"))
                        runtime_state["last_trigger_event"] = dict(trigger_event or {})
                        inst.runtime_state = runtime_state
                        s.commit()
                        return
                else:
                    # Fallback path: if a normal price/orderbook event already contains prices
                    # that require the new finer tick, confirm the real CLOB tick and treat this
                    # as equivalent to a missed tick_size_change event. No timer/polling here.
                    enable_price_tick_evidence = parse_bool(
                        self._param(params, "enable_price_tick_evidence", True),
                        True,
                    )
                    if not enable_price_tick_evidence:
                        return

                    tick_evidence = self._find_fine_tick_price_evidence(
                        trigger_event,
                        old_tick=trigger_old_tick,
                        new_tick=trigger_new_tick,
                    )
                    if not tick_evidence:
                        return

                    confirm_tick_size_via_api = parse_bool(
                        self._param(params, "confirm_tick_size_via_api", True),
                        True,
                    )
                    if confirm_tick_size_via_api:
                        confirmed_tick_size = get_market_tick_size_by_asset_id(cfg_asset_id)
                        if confirmed_tick_size != trigger_new_tick:
                            runtime_state["skip_reason"] = "price_tick_evidence_not_confirmed"
                            runtime_state["expected_new_tick"] = str(trigger_new_tick)
                            runtime_state["confirmed_tick_size"] = str(confirmed_tick_size) if confirmed_tick_size is not None else None
                            runtime_state["tick_evidence"] = tick_evidence
                            runtime_state["last_market_event"] = dict(event or {})
                            inst.runtime_state = runtime_state
                            s.commit()
                            logger.info(
                                "sport_tick_ladder price evidence ignored: instance_id=%s asset_id=%s "
                                "evidence=%s confirmed_tick_size=%s expected_new_tick=%s",
                                self.instance_id,
                                cfg_asset_id,
                                tick_evidence,
                                confirmed_tick_size,
                                trigger_new_tick,
                            )
                            return

                    trigger_source = "price_tick_evidence"
                    original_event_type = et or "market_event"
                    trigger_event = dict(trigger_event or {})
                    trigger_event.update(
                        {
                            "event_type": "tick_size_change",
                            "type": "tick_size_change",
                            "old_tick_size": str(trigger_old_tick),
                            "new_tick_size": str(trigger_new_tick),
                            "tick_size": str(trigger_new_tick),
                            "trigger_source": trigger_source,
                            "original_event_type": original_event_type,
                            "tick_evidence": tick_evidence,
                            "confirmed_tick_size": (str(confirmed_tick_size) if confirmed_tick_size is not None else None),
                        }
                    )

                event = trigger_event
                event_key = f"{build_tick_size_change_event_key(event)}:{inst.id}:sport:{trigger_source}"
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
                        "strategy_kind": self.KIND,
                        "trigger_source": trigger_source,
                        "tick_evidence": tick_evidence,
                        "confirmed_tick_size": (str(confirmed_tick_size) if confirmed_tick_size is not None else None),
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

                try:
                    refresh_balance = parse_bool(self._param(params, "refresh_balance", True), True)
                    free_balance = get_free_collateral_for_account(account_name, refresh=refresh_balance)

                    budget_round_usd = self._dec(
                        self._param(params, "budget_round_usd", DEFAULT_BUDGET_ROUND_USD),
                        DEFAULT_BUDGET_ROUND_USD,
                    ) or DEFAULT_BUDGET_ROUND_USD
                    free_balance_usage_pct = self._dec(
                        self._param(params, "free_balance_usage_pct", DEFAULT_FREE_BALANCE_USAGE_PCT),
                        DEFAULT_FREE_BALANCE_USAGE_PCT,
                    ) or DEFAULT_FREE_BALANCE_USAGE_PCT
                    min_budget_usd = self._dec(
                        self._param(params, "min_budget_usd", DEFAULT_MIN_BUDGET_USD),
                        DEFAULT_MIN_BUDGET_USD,
                    ) or DEFAULT_MIN_BUDGET_USD

                    fixed_budget = self._dec(self._param(params, "order_budget_usd", None), None)
                    if fixed_budget is not None:
                        budget_to_use = fixed_budget.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                        budget_source = "configured"
                    else:
                        budget_to_use = floor_usd_to_budget(
                            free_balance * free_balance_usage_pct,
                            budget_round_usd=budget_round_usd,
                        )
                        budget_source = "free_balance"

                    max_amount_per_order_usd = self._param(params, "max_amount_per_order_usd", None)
                    cancel_previous_orders = parse_bool(
                        self._param(params, "cancel_previous_orders", True),
                        True,
                    )
                    dry_run = parse_bool(self._param(params, "dry_run", False), False)

                    if not dry_run and self.ctx.place_order_fn is None:
                        runtime_state["skip_reason"] = "trade_functions_not_available"
                        runtime_state["last_trigger_event"] = dict(event or {})
                        runtime_state["phase"] = "WAITING_TRADE_LEADER"
                        inst.runtime_state = runtime_state
                        s.commit()
                        logger.warning(
                            "sport_tick_ladder skipped: trade functions are not available "
                            "instance_id=%s account=%s asset_id=%s",
                            self.instance_id,
                            account_name,
                            cfg_asset_id,
                        )
                        return

                    neg_risk = self._param(params, "neg_risk", None)

                    result = place_sport_orders_for_asset(
                        account_name=account_name,
                        condition_id=condition_id,
                        asset_id=cfg_asset_id,
                        side=side,
                        requested_order_price=order_price,
                        budget_to_use=budget_to_use,
                        max_amount_per_order_usd=max_amount_per_order_usd,
                        tick_size=event.get("new_tick_size") or trigger_new_tick,
                        neg_risk=neg_risk,
                        dry_run=dry_run,
                        source="sport_tick_ladder",
                        cancel_all_existing_orders=cancel_previous_orders,
                        existing_order_action="cancel_worse_and_replace",
                        min_budget_usd=min_budget_usd,
                    )

                    placed_orders = result.get("placed_orders") or []
                    failed_orders = result.get("failed_orders") or []

                    for idx, row in enumerate(placed_orders):
                        order_id = row.get("orderID")
                        if not order_id:
                            continue
                        upsert_order_meta(
                            s,
                            instance_id=str(inst.id),
                            order_id=str(order_id),
                            side=side,
                            price=Decimal(str(result.get("effective_order_price"))),
                            size=Decimal(str(row.get("size"))),
                            tag=f"sport_tick_ladder:L{idx + 1}",
                            place_note="sport_tick_size_change_reprice",
                            status="NEW",
                        )

                    runtime_state["last_trigger_event"] = dict(event or {})
                    runtime_state["trigger_source"] = trigger_source
                    runtime_state["tick_evidence"] = tick_evidence
                    runtime_state["confirmed_tick_size"] = str(confirmed_tick_size) if confirmed_tick_size is not None else None
                    runtime_state["free_balance"] = str(free_balance)
                    runtime_state["budget_source"] = budget_source
                    runtime_state["budget_to_use"] = str(budget_to_use)
                    runtime_state["sport_order_result"] = result
                    runtime_state["phase"] = "COMPLETED" if placed_orders else "FAILED"

                except Exception as e:
                    runtime_state["last_trigger_event"] = dict(event or {})
                    runtime_state["place_exception"] = str(e)
                    runtime_state["phase"] = "FAILED"
                    mark_instance_failed(
                        s,
                        inst=inst,
                        close_reason="sport_tick_ladder_exception",
                        runtime_state=runtime_state,
                    )
                    s.commit()
                    logger.exception("sport_tick_ladder exception for instance_id=%s", self.instance_id)
                    if notify_chat:
                        self.ctx.send_tg(
                            notify_chat,
                            f"⛔ [{self.name}] sport_tick_ladder exception: {e}",
                            inst_params=params,
                        )
                    return

                if placed_orders:
                    mark_instance_completed(
                        s,
                        inst=inst,
                        close_reason="sport_tick_ladder_placed" if not failed_orders else "sport_tick_ladder_partial",
                        runtime_state=runtime_state,
                    )
                    s.commit()

                    result = runtime_state.get("sport_order_result") or {}
                    lines = [
                        f"🏟 [{self.name}] sport_tick_ladder fired",
                        f"• instance: {inst.name}",
                        f"• account: {account_name}",
                        f"• condition_id: {condition_id}",
                        f"• asset_id: {cfg_asset_id}",
                        f"• trigger: {trigger_old_tick} -> {trigger_new_tick} ({trigger_source})",
                        f"• requested price: {order_price}",
                        f"• effective price: {result.get('effective_order_price')}",
                        f"• budget: {runtime_state.get('budget_to_use')} ({runtime_state.get('budget_source')})",
                        f"• cancelled previous: {len(result.get('cancelled_order_ids') or [])}",
                        f"• placed: {len(placed_orders)}",
                    ]
                    for idx, row in enumerate(placed_orders, start=1):
                        lines.append(
                            f"  - L{idx}: {side} {row.get('size')} @ {result.get('effective_order_price')} "
                            f"(order_id={row.get('orderID')})"
                        )
                    if failed_orders:
                        lines.append(f"• failed: {len(failed_orders)}")

                    if notify_chat:
                        self.ctx.send_tg(notify_chat, "\n".join(lines), inst_params=params)
                    return

                mark_instance_failed(
                    s,
                    inst=inst,
                    close_reason="sport_tick_ladder_place_failed",
                    runtime_state=runtime_state,
                )
                s.commit()

                if notify_chat:
                    self.ctx.send_tg(
                        notify_chat,
                        (
                            f"⛔ [{self.name}] sport_tick_ladder failed\n"
                            f"• instance: {inst.name}\n"
                            f"• account: {account_name}\n"
                            f"• condition_id: {condition_id}\n"
                            f"• asset_id: {cfg_asset_id}\n"
                            f"• trigger: {trigger_old_tick} -> {trigger_new_tick}\n"
                            f"• reason: {(runtime_state.get('sport_order_result') or {}).get('reason')}"
                        ),
                        inst_params=params,
                    )
            finally:
                s.close()
