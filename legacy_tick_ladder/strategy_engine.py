# FILE: logic/strategy_engine.py
from __future__ import annotations

import threading
import math
from typing import Set
import uuid
import traceback
from datetime import datetime, timezone
import time
import logging
from dataclasses import dataclass
from common.polymarket_utils import (
    clob_get_order,
    clob_place_order_for_account,
    clob_cancel_order_for_account,
    clob_get_order_for_account,
)
from typing import Callable, Dict, Optional, Any, Iterable, List, Type
from decimal import Decimal, ROUND_UP
import uuid


from sqlalchemy.orm import sessionmaker, joinedload
from sqlalchemy import select, func

from common import config
from common.db import engine
from common.logger import get_logger
from logic.market_state import MarketState


from common import config
from models.t_strategy import Strategy  # чтобы вытащить tg_chat_id
from models.t_positions_log import PositionLog
from models.t_strategy_instance_state_log import StrategyInstanceStateLog
from common.polymarket_utils import get_asset_id_by_condition  # helper: condition_id → asset_id по исходу


# ORM
from models.t_strategy import Strategy as StrategyModel, StrategyStatus
from models.t_rule import Rule as RuleModel
from models.t_strategy_instance import StrategyInstance, StrategyInstanceStatus
from models.t_strategy_instance_rule import StrategyInstanceRule
from models.t_order_meta import OrderMeta
from models.t_strategy_event import StrategyEvent
from models.t_market_orderbook import MarketOrderBook
from models.t_market_trades import MarketTrade



logger = get_logger(__name__)
log = logger.info


# ===== Контекст исполнения стратегии =====
@dataclass
class StrategyContext:
    """Общий контекст, который стратегии получают на вызовах."""
    session_factory: sessionmaker
    market_state: MarketState
    telegram_send_fn: Callable[[str, str], None] | None
    place_order_fn: Callable[..., Any] | None
    cancel_order_fn: Callable[[str], Any] | None = None
    # новый дефолтный чат для стратегии
    default_chat_id: Optional[str] = None
    # идентификатор процесса-движка, чтобы диагностировать гонки между процессами
    engine_id: Optional[str] = None
    # instance_id — чтобы контекст мог сам понять account_name из DB
    instance_id: Optional[str] = None
    # внутренний кэш (чтобы не дергать БД на каждый ордер)
    _account_name_cached: Optional[str] = None


    # --- внутренний каскад выбора чата ---
    def _resolve_chat(self, explicit: Optional[str], inst_params: Optional[dict]) -> Optional[str]:
        from common import config  # локальный импорт, чтобы не ловить циклы
        return (
            explicit
            or (inst_params or {}).get("notify_chat")
            or self.default_chat_id
            or getattr(config, "STRATEGY_CHANNEL_ID", None)
        )

    # удобные хелперы
    def send_tg(self, chat_id: Optional[str], text: str, *, inst_params: Optional[dict] = None):
        target = self._resolve_chat(chat_id, inst_params)
        if not target:
            logger.warning("TG skipped: no chat_id (explicit/params/strategy/config are empty)")
            return
        if not self.telegram_send_fn:
            logger.warning("TG skipped: telegram_send_fn is None")
            return
        try:
            self.telegram_send_fn(target, text)
        except Exception as e:
            logger.warning("TG send failed: %s", e)

    def _get_instance_account_name(self) -> Optional[str]:
        """
        Лениво читаем account_name из strategy_instance по instance_id.
        1) Кэшируем в self._account_name_cached
        2) Если instance_id не задан — вернём None
        """
        if self._account_name_cached is not None:
            # cached even if empty string -> treat as None
            v = (self._account_name_cached or "").strip()
            return v or None

        iid = (self.instance_id or "").strip()
        if not iid:
            self._account_name_cached = ""
            return None

        s = self.session_factory()
        try:
            row = (
                s.query(StrategyInstance.account_name)
                 .filter(StrategyInstance.id == iid)
                 .one_or_none()
            )
            if not row:
                self._account_name_cached = ""
                return None
            val = (row[0] or "").strip()
            self._account_name_cached = val
            return val or None
        except Exception:
            logger.exception("StrategyContext: failed to resolve account_name for instance_id=%s", iid)
            self._account_name_cached = ""
            return None
        finally:
            try:
                s.close()
            except Exception:
                pass

    def place_order(
        self,
        *,
        asset_id: str,
        side: str,
        size: Decimal,
        limit_price: Decimal,
        account_name: Optional[str] = None,
    ) -> dict:
        """
        Удобная обёртка над прокинутой place_order_fn (clob_place_order).
        Возвращает dict вида {"success": bool, "orderID": str|None, "raw": any}.
        """
        if not self.place_order_fn:
            logger.warning(
                "StrategyContext.place_order skipped: place_order_fn is None "
                "(asset_id=%s side=%s size=%s price=%s)",
                asset_id, side, size, limit_price,
            )
            return {"success": False, "orderID": None, "raw": None}
        try:
            acc = (account_name or "").strip() or self._get_instance_account_name()
            if acc:
                return clob_place_order_for_account(
                    account_name=acc,
                    asset_id=asset_id,
                    side=side,
                    size=size,
                    limit_price=limit_price,
                )
            # fallback: старое поведение (например, для стратегий без account_name)
            return self.place_order_fn(asset_id=asset_id, side=side, size=size, limit_price=limit_price)

        except Exception as e:
            logger.warning(
                "StrategyContext.place_order failed: %s (asset_id=%s side=%s size=%s price=%s)",
                e, asset_id, side, size, limit_price,
            )
            return {"success": False, "orderID": None, "raw": None}

    def cancel_order(self, order_id: str, *, account_name: Optional[str] = None) -> dict:
        """
        Обёртка над прокинутой cancel_order_fn.
        Ожидается, что функция возвращает что-то вида {"success": bool, ...}.
        """
        if not self.cancel_order_fn:
            logger.warning("StrategyContext.cancel_order skipped: cancel_order_fn is None (order_id=%s)", order_id)
            return {"success": False, "raw": None}
        try:
            acc = (account_name or "").strip() or self._get_instance_account_name()
            if acc:
                return clob_cancel_order_for_account(account_name=acc, order_id=str(order_id))
            return self.cancel_order_fn(order_id)
        except Exception as e:
            logger.warning("StrategyContext.cancel_order failed: %s (order_id=%s)", e, order_id)
            return {"success": False, "raw": None}

    def get_order(self, order_id: str, *, account_name: Optional[str] = None) -> dict:
        """
        Получить статус/filled ордера (нормализованный формат) через polymarket_utils.clob_get_order.
        """
        try:
            acc = (account_name or "").strip() or self._get_instance_account_name()
            if acc:
                return clob_get_order_for_account(account_name=acc, order_id=str(order_id))
            return clob_get_order(order_id)
        except Exception as e:
            logger.warning("StrategyContext.get_order failed: %s (order_id=%s)", e, order_id)
            return {"success": False, "orderID": order_id, "status": None, "filled": None, "remaining": None, "avg_price": None, "raw": None}

    def best_prices(self, asset_id: str):
        return self.market_state.best_prices(asset_id)

    def mid(self, asset_id: str):
        return self.market_state.mid_price(asset_id)

    def orderbook_snapshot(self, asset_id: str):
        """
        Снимок ордербука и базовых метрик для КОНКРЕТНОГО asset_id.

        Важно:
          - В таблице market_orderbook одна строка хранит и YES, и NO.
          - Если asset_id == asset_yes → берём bids_yes / asks_yes.
          - Если asset_id == asset_no  → берём bids_no  / asks_no.

        Возвращает dict (или None, если данных нет):
          {
            "asset_id": asset_id,         # тот, что спросили
            "side": "YES" | "NO",
            "condition_id": ...,
            "bids": [...],
            "asks": [...],
            "best_bid": Decimal | None,
            "best_ask": Decimal | None,
            "mid": Decimal | None,
            "spread": Decimal | None,
            "updated_at": datetime,
          }
        """
        if not asset_id:
            return None

        s = self.session_factory()
        try:
            # Сначала считаем, что это YES-ассет (PK = asset_yes)
            ob = s.get(MarketOrderBook, asset_id)
            side = "YES"

            if ob is None:
                # Возможно, это NO-ассет — ищем по asset_no
                ob = (
                    s.query(MarketOrderBook)
                     .filter(MarketOrderBook.asset_no == asset_id)
                     .one_or_none()
                )
                if not ob:
                    return None
                side = "NO"

            if side == "YES":
                bids = ob.bids_yes or []
                asks = ob.asks_yes or []
            else:
                bids = ob.bids_no or []
                asks = ob.asks_no or []

            def _to_dec(x):
                try:
                    return Decimal(str(x))
                except Exception:
                    return None

            # best bid = max price среди бидов
            best_bid = None
            if bids:
                prices = [ _to_dec(lvl.get("price")) for lvl in bids ]
                prices = [p for p in prices if p is not None]
                if prices:
                    best_bid = max(prices)

            # best ask = min price среди асков
            best_ask = None
            if asks:
                prices = [ _to_dec(lvl.get("price")) for lvl in asks ]
                prices = [p for p in prices if p is not None]
                if prices:
                    best_ask = min(prices)

            mid = None
            spread = None
            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / Decimal("2")
                spread = best_ask - best_bid

            return {
                "asset_id": asset_id,
                "side": side,
                "condition_id": ob.condition_id,
                "bids": bids,
                "asks": asks,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": mid,
                "spread": spread,
                "updated_at": ob.updated_at,
            }
        finally:
            s.close()

    def get_latest_position_snapshot(
            self,
            *,
            condition_id: str,
            strategy_id: Optional[Any] = None,
        ) -> Optional[dict]:
        """
        Вернуть последний снапшот позиции из positions_log
        для пары (strategy_id, condition_id).

        Если strategy_id is None — берём любые записи по этому condition_id.
        Возвращаем dict по всем колонкам таблицы или None, если записей нет.
        """
        s = self.session_factory()
        try:
            q = s.query(PositionLog).filter(PositionLog.condition_id == condition_id)
            if strategy_id is not None:
                try:
                    int_id = int(strategy_id)
                except (TypeError, ValueError):
                    logger.warning(
                        "get_latest_position_snapshot: strategy_id %r is not an int, ignoring this filter",
                        strategy_id,
                    )
                else:
                    q = q.filter(PositionLog.strategy_id == int_id)


            # Берём самую свежую запись по id (он автоинкрементный)
            row = q.order_by(PositionLog.id.desc()).first()
            if not row:
                return None

            result: dict[str, Any] = {}
            for col in PositionLog.__table__.columns:
                result[col.name] = getattr(row, col.name)
            return result
        finally:
            s.close()



# ===== Базовый класс стратегии =====
class StrategyBase:
    """Интерфейс (скелет) конкретной стратегии."""
    KIND: str = "BASE"

    def __init__(self, *, db_id: str, name: str, params: dict | None, ctx: StrategyContext, instance_id: str | None = None):
        self.db_id = db_id       # strategy.id (UUID строкой)
        self.name = name
        self.params = params or {}
        self.ctx = ctx
        self.instance_id = instance_id  # ← id конкретного инстанса стратегии
        self._lock = threading.RLock()
        self._running = False

    # ====== lifecycle ======
    def on_start(self):
        """Вызов сразу после загрузки/активации (однократно)."""
        self._running = True
        log(
            "▶️ Strategy started: %s strategy_id=%s instance_id=%s",
            self.name,
            self.db_id,
            self.instance_id,
        )

    def on_stop(self):
        """Вызов при остановке/удалении/disable."""
        self._running = False
        log(
            "⏹ Strategy stopped: %s strategy_id=%s instance_id=%s",
            self.name,
            self.db_id,
            self.instance_id,
        )

    # ====== события ======
    def on_market_event(self, asset_id: str, event: dict):
        """WS-событие по рынку/ассету, который стратегия слушает."""
        # скелет — без логики
        pass

    def on_timer(self, now_ts: float):
        """Периодический тик (например, раз в N секунд)."""
        pass

    def on_rule_fired(self, rule: RuleModel, observed_price: Decimal | None, order_id: Optional[str] = None):
        """Срабатывание атомарного правила, привязанного к стратегии (если нужно)."""
        pass

    def on_user_trade(self, event: dict):
        """Переопределяется конкретной стратегией (если нужно)."""
        pass

# ===== Пример пустых реализаций (регистрация через реестр) =====
class Strategy_TrendExecutor(StrategyBase):
    KIND = "TREND_EXECUTOR"
    # пока пусто — будет заполнено логикой далее


class Strategy_LevelBreakout(StrategyBase):
    KIND = "LEVEL_BREAKOUT"
    # пока пусто — будет заполнено логикой далее

class Strategy_SimpleNotifyOnFill(StrategyBase):

    """
    Тестовая стратегия:
      - запоминает order_id из события on_rule_fired (когда правило поставило ордер);
      - при первом trade из userchanel с тем же order_id шлёт уведомление и очищает ожидание.
    """
    KIND = "SIMPLE_NOTIFY_ON_FILL"

    def __init__(self, **kw):
        super().__init__(**kw)
        self._expected_orders: set[str] = set()


    def on_rule_fired(self, rule: RuleModel, observed_price: Decimal | None, order_id: Optional[str] = None):
        if not order_id:
            # нет order_id — просто информируем (опционально)
            self.ctx.send_tg(self.params.get("notify_chat"),
                             f"📌 [{self.name}] Rule {rule.id} fired @ {observed_price}. (order_id unknown)")
            return
        with self._lock:
            self._expected_orders.add(str(order_id))
        self.ctx.send_tg(self.params.get("notify_chat"),
                         f"📌 [{self.name}] Rule {rule.id} fired @ {observed_price}. Order placed: {order_id}")

    def on_user_trade(self, event: dict):
        """
        Событие уже маршрутизировано по OrderMeta, значит относится к нашему инстансу.
        Сообщаем о fill и завершаем инстанс (демо-логика).
        """
        oid = (event or {}).get("order_id")
        if not oid:
            return
        logger.debug("on_user_trade ENTRY: %s", {k: event.get(k) for k in ("order_id","side","price","size","executed_at","timestamp","ts")})

        side = (event.get("side") or "").upper() or None
        # принимаем разные варианты полей из userchanel / API
        price = event.get("price") or event.get("avg_price")
        size  = event.get("size") or event.get("filled_size") or event.get("qty")
        executed_at = event.get("executed_at") or event.get("timestamp") or event.get("ts")

        self.ctx.send_tg(
            self.params.get("notify_chat"),
            f"✅ [{self.name}] FILL {oid}: {side} {size} @ {price}\n"
            f"🕒 {executed_at}",
            inst_params=self.params  # даст каскад: params → strategy.tg_chat_id → config
        )
        # демо: сразу завершаем инстанс
        # демо-логика: считаем задачу инстанса выполненной после первого fill
        if self.instance_id:
            s = self.ctx.session_factory()
            try:
                inst = s.query(StrategyInstance).filter(StrategyInstance.id == self.instance_id).first()
                if not inst:
                    return
                # используем серверный enum через модель
                current = getattr(inst, "status", None)
                target = getattr(StrategyInstanceStatus, "COMPLETED", None)
                if target is None:
                    # на случай, если миграция не применена — падать не будем, используем DONE
                    target = getattr(StrategyInstanceStatus, "DONE", None)
                if target and current != target:
                    inst.status = target
                    s.commit()
            finally:
                s.close()


# ===== Реестр =====
class StrategyRegistry:
    _by_kind: Dict[str, Type[StrategyBase]] = {}

    @classmethod
    def register(cls, klass: Type[StrategyBase]):
        kind = getattr(klass, "KIND", None)
        if not kind:
            raise ValueError("Strategy class must define KIND")
        cls._by_kind[kind] = klass

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        db_id: str,
        name: str,
        params: dict,
        ctx: StrategyContext,
        instance_id: str | None = None,
    ) -> StrategyBase:
        if kind not in cls._by_kind:
            raise ValueError(f"Unknown strategy kind: {kind}")
        return cls._by_kind[kind](db_id=db_id, name=name, params=params, ctx=ctx, instance_id=instance_id)


# 🔗 Импортируем реализацию SkyBuyer из отдельного файла.
# ВАЖНО: этот импорт должен быть ПОСЛЕ определения StrategyBase и StrategyRegistry,
# но ДО регистрации стратегий.
from logic.strategy_skybuyer import Strategy_SkyBuyer
from logic.strategy_quietbuyer import Strategy_QuietBuyer, Strategy_QuiteBuyer
from logic.strategy_notifier import Strategy_Notifier
from logic.strategy_buyer import Strategy_Buyer
from logic.strategy_tick_ladder import Strategy_TickLadder
from logic.strategy_sport_tick_ladder import Strategy_SportTickLadder
from logic.strategy_sport_best_bid_trigger import Strategy_SportBestBidTrigger

# зарегистрируем заготовки
StrategyRegistry.register(Strategy_TrendExecutor)
StrategyRegistry.register(Strategy_LevelBreakout)
StrategyRegistry.register(Strategy_SkyBuyer)
StrategyRegistry.register(Strategy_QuietBuyer)
StrategyRegistry.register(Strategy_QuiteBuyer)
StrategyRegistry.register(Strategy_Notifier)
StrategyRegistry.register(Strategy_Buyer)
StrategyRegistry.register(Strategy_SimpleNotifyOnFill)
StrategyRegistry.register(Strategy_TickLadder)
StrategyRegistry.register(Strategy_SportTickLadder)
StrategyRegistry.register(Strategy_SportBestBidTrigger)


# ===== Рантайм-объект стратегии =====
@dataclass
class StrategyInstanceRuntime:
    instance: StrategyInstance
    strategy: StrategyModel
    impl: StrategyBase

# ===== Сам движок =====
class StrategyEngine:
    """
    Управляет жизненным циклом стратегий:
    - грузит активные стратегии из БД
    - строит карту: asset_id -> [strategy_ids]
    - маршрутизирует рыночные события (из WS) в стратегии
    - периодически вызывает on_timer
    - даёт доступ к reload() (например, по LISTEN/NOTIFY)
    """
    def __init__(self,
                 *,
                 engine=engine,
                 market_state: MarketState,
                 telegram_send_fn: Callable[[str, str], None] | None = None,
                 place_order_fn: Callable[..., Any] | None = None,
                 cancel_order_fn: Callable[[str], Any] | None = None,
                 timer_interval_s: int = 2,
                 allowed_kinds: Iterable[str] | None = None):
        self.engine = engine
        self.Session = sessionmaker(bind=engine, expire_on_commit=False)
        self.state = market_state
        # ВНИМАНИЕ: общий контекст больше не нужен — будем создавать per-instance контекст с default_chat_id
        self._telegram_send_fn = telegram_send_fn
        self._place_order_fn = place_order_fn
        self._cancel_order_fn = cancel_order_fn
        self._allowed_kinds = {str(k).strip().lower() for k in (allowed_kinds or []) if str(k).strip()}
        self._inst_by_id: Dict[str, StrategyInstanceRuntime] = {}
        self._rule_to_instance: Dict[str, str] = {}   # rule_id -> instance_id
        self._lock = threading.RLock()
        # negative-cache: инстансы, которые этот движок заведомо не должен грузить
        # (например, kind не входит в allowed_kinds). Убирает DB-дергание и лог-спам.
        self._disallowed_instance_ids: Set[str] = set()
        self._timer_interval_s = max(1, int(timer_interval_s))
        self._timer_thread: Optional[threading.Thread] = None
        self._timer_stop = threading.Event()
        # уникальный идентификатор процесса-движка (для логов и диагностики гонок)
        self.engine_id = str(uuid.uuid4())
        # канал для ошибок (как в ingest). если не задан — просто молча не шлём
        self._error_chat_id = getattr(config, "ERRORS_CHANNEL_ID", None) or getattr(config, "STRATEGY_ERRORS_CHANNEL_ID", None)
        self._err_last_sent: Dict[str, float] = {}
        logger.info("StrategyEngine created with engine_id=%s", self.engine_id)

    def set_trade_fns(
        self,
        *,
        place_order_fn: Callable[..., Any] | None,
        cancel_order_fn: Callable[[str], Any] | None = None,
    ) -> None:
        """
        Динамически включить/выключить торговые функции.
        Важно: обновляем не только self._place_order_fn, но и уже созданные ctx у runtime-инстансов.
        """
        with self._lock:
            self._place_order_fn = place_order_fn
            self._cancel_order_fn = cancel_order_fn
            for rt in self._inst_by_id.values():
                try:
                    rt.impl.ctx.place_order_fn = place_order_fn
                    rt.impl.ctx.cancel_order_fn = cancel_order_fn
                except Exception:
                    pass
        logger.info(
            "StrategyEngine trade fns updated: place_order_fn=%s cancel_order_fn=%s",
            "SET" if place_order_fn else "None",
            "SET" if cancel_order_fn else "None",
        )

    # --- circuit breaker helpers ---
    def _now_ts(self) -> float:
        return time.time()

    def _pause_seconds_for_failure(self, fail_count: int) -> int:
        """
        Backoff:
          1 -> 300s (5m)
          2 -> 1800s (30m)
          3 -> 7200s (2h)
          4+ -> 86400s (24h)
        """
        if fail_count <= 1:
            return 300
        if fail_count == 2:
            return 1800
        if fail_count == 3:
            return 7200
        return 86400

    def _is_paused_now(self, inst: StrategyInstance, now_ts: float) -> bool:
        if getattr(inst, "status", None) != StrategyInstanceStatus.PAUSED:
            return False
        ts = (inst.timer_state or {})
        pu = ts.get("paused_until")
        try:
            pu_f = float(pu) if pu is not None else 0.0
        except Exception:
            pu_f = 0.0
        return now_ts < pu_f

    def _resume_if_due(self, instance_id: str, now_ts: float) -> None:
        """
        Если инстанс PAUSED и paused_until <= now, переводим обратно в RUNNING.
        """
        with self.Session() as s:
            inst = s.query(StrategyInstance).filter(StrategyInstance.id == str(instance_id)).one_or_none()
            if not inst:
                return
            if getattr(inst, "status", None) != StrategyInstanceStatus.PAUSED:
                return
            ts = dict(inst.timer_state or {})
            pu = ts.get("paused_until")
            try:
                pu_f = float(pu) if pu is not None else 0.0
            except Exception:
                pu_f = 0.0
            if pu_f and now_ts >= pu_f:
                inst.status = StrategyInstanceStatus.RUNNING
                # отметим, что было авто-возобновление
                ts["paused_reason"] = None
                ts["paused_until"] = None
                ts["resumed_at"] = now_ts
                inst.timer_state = ts
                try:
                    inst.updated_at = datetime.now(timezone.utc)
                except Exception:
                    pass
                s.commit()

    def _trip_circuit_breaker(self, instance_id: str, where: str, exc: Exception) -> None:
        """
        1) увеличиваем fail_count
        2) ставим PAUSED + paused_until
        3) шлём TG (через _notify_error)
        """
        now_ts = self._now_ts()
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        tb_lines = tb.strip().splitlines()
        short_tb = "\n".join(tb_lines[-8:]) if tb_lines else f"{type(exc).__name__}: {exc}"

        with self.Session() as s:
            inst = s.query(StrategyInstance).filter(StrategyInstance.id == str(instance_id)).one_or_none()
            if not inst:
                return
            ts = dict(inst.timer_state or {})
            fail_count = int(ts.get("fail_count") or 0) + 1
            ts["fail_count"] = fail_count
            pause_s = self._pause_seconds_for_failure(fail_count)
            ts["paused_until"] = now_ts + float(pause_s)
            ts["paused_at"] = now_ts
            ts["paused_reason"] = f"{where}: {type(exc).__name__}: {exc}"
            ts["last_error"] = short_tb
            inst.timer_state = ts
            inst.status = StrategyInstanceStatus.PAUSED
            # в UI/репортах полезно видеть причину
            try:
                inst.close_reason = ts["paused_reason"]
            except Exception:
                pass
            try:
                inst.updated_at = datetime.now(timezone.utc)
            except Exception:
                pass
            s.commit()

        # TG notify с антиспамом (ключ на инстанс)
        self._notify_error(f"circuit:{instance_id}", f"{where} -> PAUSED ({pause_s}s)", exc)

    def _notify_error(self, key: str, title: str, exc: Exception) -> None:
        """
        Шлём короткое уведомление об ошибке в TG, с анти-спамом (1/60s на key).
        """
        if not self._error_chat_id or not self._telegram_send_fn:
            return
        now = time.time()
        last = self._err_last_sent.get(key, 0.0)
        if now - last < 60.0:
            return
        self._err_last_sent[key] = now

        # короткий traceback (последние ~8 строк)
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        tb_lines = tb.strip().splitlines()
        short_tb = "\n".join(tb_lines[-8:]) if tb_lines else f"{type(exc).__name__}: {exc}"

        msg = "\n".join([
            "⚠️ Strategy error",
            f"• engine_id: {self.engine_id}",
            f"• where: {title}",
            f"• error: {type(exc).__name__}: {exc}",
            "—",
            short_tb,
        ])
        try:
            self._telegram_send_fn(str(self._error_chat_id), msg)
        except Exception:
            logger.exception("TG error notify failed")

    # --- публичные методы ---
    def load_active_strategies(self, strategy_ids: Optional[Iterable[str]] = None):
        """Грузим ENABLED стратегии и их RUNNING инстансы. Маппим rule_id -> instance_id."""
 
        with self._lock, self.Session() as s:
            # старый набор runtime-инстансов, чтобы понять, кто был уже запущен
            old_map: Dict[str, StrategyInstanceRuntime] = dict(self._inst_by_id)

            # enabled strategies
            q = s.query(StrategyModel).filter(StrategyModel.status == StrategyStatus.ENABLED)
            if strategy_ids:
                q = q.filter(StrategyModel.id.in_(list(strategy_ids)))
            # ВАЖНО: ключи делаем str(UUID), чтобы совпадало с TEXT strategy_id в инстансе
            strategies = {str(m.id): m for m in q.all()}

            # running instances
            insts: List[StrategyInstance] = (
                s.query(StrategyInstance)
                 .filter(StrategyInstance.status.in_([StrategyInstanceStatus.PENDING, StrategyInstanceStatus.RUNNING]))
                 .all()
            )
            # map rule -> instance
            links = s.query(StrategyInstanceRule).all()
            raw_rule_to_inst: Dict[str, str] = {
                str(ln.rule_id): str(ln.strategy_instance_id)
                for ln in links
            }

            new_map: Dict[str, StrategyInstanceRuntime] = {}
            skipped_total = skipped_no_strategy = skipped_disabled = skipped_status = skipped_unknown_kind = skipped_kind_not_allowed = 0
            for ins in insts:
                st = strategies.get(str(ins.strategy_id))  # ins.strategy_id хранится как TEXT(UUID)
                if not st:
                    skipped_no_strategy += 1; skipped_total += 1
                    continue
                if getattr(st, "status", None) != StrategyStatus.ENABLED:
                    skipped_disabled += 1; skipped_total += 1
                    continue
                if ins.status not in (StrategyInstanceStatus.PENDING, StrategyInstanceStatus.RUNNING):
                    skipped_status += 1; skipped_total += 1
                    continue


                # фильтр по kind (для разделения ролей marketchanel: notify-only / trade)
                if self._allowed_kinds and str(getattr(st, "kind", "") or "").strip().lower() not in self._allowed_kinds:
                    skipped_kind_not_allowed += 1; skipped_total += 1
                    continue

                # создаём контекст с дефолтным чатом стратегии
                ctx = StrategyContext(
                    session_factory=self.Session,
                    market_state=self.state,
                    telegram_send_fn=self._telegram_send_fn,
                    place_order_fn=self._place_order_fn,
                    cancel_order_fn=self._cancel_order_fn,
                    default_chat_id=getattr(st, "tg_chat_id", None),
                    engine_id=self.engine_id,
                    instance_id=str(ins.id),
                )
                try:
                    impl = StrategyRegistry.create(
                        kind=st.kind,
                        db_id=str(st.id),
                        name=st.name,
                        params=ins.params or {},
                        ctx=ctx,
                        instance_id=str(ins.id),  # ← пробрасываем id инстанса в стратегию
                    )
                except ValueError as e:
                    skipped_unknown_kind += 1
                    skipped_total += 1
                    logger.error(
                        "Skip strategy instance %s: unknown kind=%s (%s)",
                        ins.id, st.kind, e
                    )
                    continue

                new_map[str(ins.id)] = StrategyInstanceRuntime(
                    instance=ins,
                    strategy=st,
                    impl=impl
                )

            # только для активных инстансов строим карту rule_id -> instance_id
            active_rule_to_inst: Dict[str, str] = {
                rid: iid
                for rid, iid in raw_rule_to_inst.items()
                if iid in new_map
            }

            # stop removed instances (те, которых больше нет в new_map)
            for iid, rt in list(old_map.items()):
                if iid not in new_map:
                    try:
                        rt.impl.on_stop()
                    except Exception:
                        logger.exception("Stop failed for instance %s", iid)

            # обновляем runtime-карты
            self._inst_by_id = new_map
            self._rule_to_instance = active_rule_to_inst
            # важное: если сделали полный reload(), то сбрасываем negative-cache.
            # (на случай если кто-то руками поменял allowed_kinds и перезапустил процесс,
            # или инстансы были пересозданы)
            self._disallowed_instance_ids.clear()

            # on_start вызываем только для НОВЫХ инстансов
            for iid, rt in self._inst_by_id.items():
                if iid not in old_map:
                    try:
                        rt.impl.on_start()
                    except Exception:
                        logger.exception("Start failed for instance %s", rt.instance.id)

            log(
                "🧩 Strategy instances loaded: %d (active rule links: %d) | skipped: total=%d no_strategy=%d disabled=%d bad_status=%d kind_not_allowed=%d unknown_kind=%d",
                len(self._inst_by_id), len(self._rule_to_instance),
                skipped_total, skipped_no_strategy, skipped_disabled, skipped_status, skipped_kind_not_allowed, skipped_unknown_kind
            )

    def reload(self):
        """Полный ребилд (например, после NOTIFY)."""
        self.load_active_strategies()

    def active_asset_ids(self) -> set[str]:
        """Экземпляры больше не управляют подпиской — оставлено пустым."""
        return set()

    @staticmethod
    def _instance_watches_asset(params: dict, asset_id: str) -> bool:
        """
        True, если strategy_instance явно смотрит этот asset_id.

        Поддерживает оба формата:
          - params.asset_id / assetId / asset;
          - params.assets = [{"asset_id": ...}, ...] для sport_best_bid_trigger.

        Если у стратегии вообще нет asset-фильтра, возвращаем True для backward
        compatibility со старыми стратегиями.
        """
        aid = str(asset_id or "").strip()
        if not aid:
            return False

        explicit_assets: set[str] = set()

        for key in ("asset_id", "assetId", "asset"):
            value = str((params or {}).get(key) or "").strip()
            if value:
                explicit_assets.add(value)

        assets = (params or {}).get("assets") or []
        if isinstance(assets, list):
            for row in assets:
                if not isinstance(row, dict):
                    continue
                value = str(
                    row.get("asset_id")
                    or row.get("assetId")
                    or row.get("asset")
                    or ""
                ).strip()
                if value:
                    explicit_assets.add(value)

        if not explicit_assets:
            return True

        return aid in explicit_assets

    def on_market_event(self, asset_id: str, event: dict):
        """
        Маршрутизация WS market-event в активные strategy instances.

        Старые стратегии этот хук обычно игнорируют.
        Новый контур может реагировать на price_change/book/tick_size_change по
        конкретному asset_id. Для sport_best_bid_trigger важно учитывать
        params["assets"] массив, а не только top-level params.asset_id.
        """
        with self._lock:
            rts = list(self._inst_by_id.values())

        for rt in rts:
            try:
                inst_params = dict(rt.instance.params or {})
                if not self._instance_watches_asset(inst_params, str(asset_id)):
                    continue
                rt.impl.on_market_event(asset_id, event)
            except Exception:
                logger.exception(
                    "on_market_event failed for instance %s asset_id=%s",
                    rt.instance.id,
                    asset_id,
                )

    def on_rule_fired(self, rule_id: str, observed_price: Decimal | None, order_id: str | None = None):
        """Маршрутизация события срабатывания правила в конкретный ИНСТАНС по rule_id."""
        with self._lock:
            instance_id = self._rule_to_instance.get(rule_id)
            rt = self._inst_by_id.get(instance_id) if instance_id else None
        if not rt:
            return
        with self.Session() as s:
            rule = s.query(RuleModel).get(rule_id)
        if not rule:
            return
        try:
            rt.impl.on_rule_fired(rule, observed_price, order_id)
        except Exception:
            logger.exception("on_rule_fired failed for instance %s", instance_id)


    def start_timer(self):
        if self._timer_thread and self._timer_thread.is_alive():
            return
        self._timer_stop.clear()
        t = threading.Thread(target=self._timer_loop, name="strategy-timer", daemon=True)
        t.start()
        self._timer_thread = t

    def stop_timer(self):
        self._timer_stop.set()
        if self._timer_thread:
            self._timer_thread.join(timeout=2.0)

    # --- приватка ---
    def _rebuild_asset_map_unlocked(self):
        # больше не используем карту подписки (WS подписывает marketchanel по правилам)
        self._asset_map = {}

    def _timer_loop(self):
        while not self._timer_stop.is_set():
            now = time.time()
            # сначала подтянем необработанные события из БД (надёжный путь)
            try:
                self.poll_events_once(max_rows=100)
            except Exception as e:
                logger.exception("poll_events_once failed")
                self._notify_error("poll_events_once", "poll_events_once()", e)

            with self._lock:
                rts = list(self._inst_by_id.values())
            for rt in rts:
                try:
                    # circuit breaker: если paused — пропускаем, либо авто-резюмим
                    inst = rt.instance
                    if getattr(inst, "status", None) == StrategyInstanceStatus.PAUSED:
                        # сначала попробуем авто-резюмить, если срок вышел
                        self._resume_if_due(str(inst.id), now)
                        # синхронизируем runtime-инстанс (минимально)
                        # если всё ещё paused и срок не вышел — пропускаем тик
                        with self.Session() as s2:
                            fresh = s2.query(StrategyInstance).filter(StrategyInstance.id == str(inst.id)).one_or_none()
                        if fresh:
                            rt.instance = fresh
                            inst = fresh
                        if self._is_paused_now(inst, now):
                            continue

                    rt.impl.on_timer(now)
                except Exception as e:
                    logger.exception("on_timer failed for instance %s", rt.instance.id)
                    # 1) ставим на паузу, чтобы не плодить ордера/ошибки
                    try:
                        self._trip_circuit_breaker(str(rt.instance.id), f"on_timer(instance={rt.instance.id})", e)
                    except Exception:
                        logger.exception("circuit breaker failed for instance %s", rt.instance.id)
                        # fallback уведомление
                        self._notify_error(f"on_timer:{rt.instance.id}", f"on_timer(instance={rt.instance.id})", e)

            self._timer_stop.wait(self._timer_interval_s)

    def _ensure_instance_loaded(self, instance_id: str) -> bool:
        """Ленивая догрузка одного инстанса без полного reload().

        Нужна, чтобы новые инстансы начинали исполняться без рестарта marketchanel.
        Возвращает True, если инстанс оказался (или стал) загружен в runtime.
        """
        iid = str(instance_id)
        with self._lock:
            # если уже знаем, что этот инстанс нельзя грузить — даже не лезем в БД
            if iid in self._disallowed_instance_ids:
                return False
            if iid in self._inst_by_id:
                return True

        with self.Session() as s:
            ins: StrategyInstance | None = (
                s.query(StrategyInstance)
                 .filter(StrategyInstance.id == iid)
                 .one_or_none()
            )
            if not ins:
                return False
            if ins.status not in (StrategyInstanceStatus.PENDING, StrategyInstanceStatus.RUNNING):
                return False

            st: StrategyModel | None = (
                s.query(StrategyModel)
                 .filter(StrategyModel.id == str(ins.strategy_id))
                 .one_or_none()
            )
            if not st or getattr(st, "status", None) != StrategyStatus.ENABLED:
                return False

            # ✅ ВАЖНО: соблюдаем allowed_kinds и в lazy-load пути тоже
            if self._allowed_kinds:
                k = str(getattr(st, "kind", "") or "").strip().lower()
                if k not in self._allowed_kinds:
                    # one-shot лог + negative-cache
                    with self._lock:
                        first_time = iid not in self._disallowed_instance_ids
                        self._disallowed_instance_ids.add(iid)
                    if first_time:
                        logger.info(
                            "Skip lazy-load instance %s: kind=%s not in allowed_kinds=%s",
                            iid, k, sorted(self._allowed_kinds)
                        )                    
                    return False

            ctx = StrategyContext(
                session_factory=self.Session,
                market_state=self.state,
                telegram_send_fn=self._telegram_send_fn,
                place_order_fn=self._place_order_fn,
                cancel_order_fn=self._cancel_order_fn,
                default_chat_id=getattr(st, "tg_chat_id", None),
                engine_id=self.engine_id,
                instance_id=str(ins.id),
            )

            try:
                impl = StrategyRegistry.create(
                    kind=st.kind,
                    db_id=str(st.id),
                    name=st.name,
                    params=ins.params or {},
                    ctx=ctx,
                    instance_id=str(ins.id),
                )
            except Exception:
                logger.exception("Skip strategy instance %s: unknown kind=%s", iid, getattr(st, "kind", None))
                return False

            rt = StrategyInstanceRuntime(instance=ins, strategy=st, impl=impl)

            # map rule_id -> instance_id только для этого инстанса
            links = (
                s.query(StrategyInstanceRule)
                 .filter(StrategyInstanceRule.strategy_instance_id == iid)
                 .all()
            )

        with self._lock:
            # двойная проверка на гонку
            if iid in self._inst_by_id:
                return True
            self._inst_by_id[iid] = rt
            for ln in links:
                self._rule_to_instance[str(ln.rule_id)] = iid

        try:
            rt.impl.on_start()
        except Exception:
            logger.exception("on_start failed for newly loaded instance %s", iid)

        return True

    # === Hybrid-путь: считывание событий из strategy_event ===
    def poll_events_once(self, max_rows: int = 200):
        """
        Забираем непрочитанные события из strategy_event (handled_at IS NULL).

        * Для FILL/USER_TRADE — роутим в StrategyInstanceRuntime.impl.on_user_trade(payload)
        * Для служебных событий (WAKE и т.п.) — просто отмечаем handled_at

        ВАЖНО: если инстанс ещё не загружен в runtime, пытаемся догрузить его точечно,
        чтобы новый инстанс стартовал без рестарта marketchanel.
        """
        with self.Session() as s:
            rows = (
                s.query(StrategyEvent)
                 .filter(StrategyEvent.handled_at.is_(None))
                 .order_by(StrategyEvent.created_at.asc())
                 .limit(max_rows)
                 .all()
            )
            if not rows:
                return
            for ev in rows:
                inst_id = str(ev.instance_id)
                with self._lock:
                    rt = self._inst_by_id.get(inst_id)
                if not rt:
                    try:
                        self._ensure_instance_loaded(inst_id)
                    except Exception:
                        logger.exception("ensure_instance_loaded failed for %s", inst_id)
                    with self._lock:
                        rt = self._inst_by_id.get(inst_id)
                if not rt:
                    # инстанс сейчас не активен — оставим событие, чтобы добралось при следующей загрузке
                    continue
                # 1) атомарно помечаем событие обработанным (если кто-то уже забрал — ничего не делаем)
                updated = (
                    s.query(StrategyEvent)
                     .filter(StrategyEvent.id == ev.id, StrategyEvent.handled_at.is_(None))
                     .update({StrategyEvent.handled_at: func.now()}, synchronize_session=False)
                )
                if updated == 0:
                    s.rollback()
                    continue
                s.commit()

                # 2) вызываем стратегию только для "трейдовых" событий
                et = (ev.event_type or "").upper()
                if et in ("FILL", "USER_TRADE", "TRADE"):
                    payload = dict(ev.payload or {})
                    try:
                        rt.impl.on_user_trade(payload)
                    except Exception as e:
                        logger.exception("on_user_trade (via strategy_event) failed for instance %s", inst_id)                    
                        # circuit breaker и тут тоже (чтобы не спамить/не делать повторные действия)
                        try:
                            self._trip_circuit_breaker(str(inst_id), f"on_user_trade(instance={inst_id}) via strategy_event", e)
                        except Exception:
                            logger.exception("circuit breaker failed for instance %s", inst_id)
                            self._notify_error(
                                f"on_user_trade:{inst_id}",
                                f"on_user_trade(instance={inst_id}) via strategy_event",
                                e,
                            )

    def on_user_trade(self, event: dict):
        """Роутинг трейда пользователя (из userchanel) по order_id → нужный instance."""
        ev = event or {}

        def _iter_oid_candidates(e: dict) -> list[str]:
            out: list[str] = []
            for k in ("order_id","orderID","orderId","taker_order_id","maker_order_id","takerOrderId","makerOrderId"):
                v = e.get(k)
                if v:
                    out.append(str(v))
            mo = e.get("maker_orders") or e.get("makerOrders")
            if isinstance(mo, list):
                for it in mo:
                    if isinstance(it, dict):
                        v = it.get("order_id") or it.get("orderID") or it.get("orderId")
                        if v:
                            out.append(str(v))
            # unique preserve order
            seen = set()
            uniq: list[str] = []
            for x in out:
                if x not in seen:
                    seen.add(x)
                    uniq.append(x)
            return uniq

        oids = _iter_oid_candidates(ev)
        if not oids:
            return

        logger.debug(
            "on_user_trade ENTRY: %s",
            {k: ev.get(k) for k in ("order_id","taker_order_id","maker_order_id","side","price","size","executed_at","timestamp","ts")}
        )

        meta = None
        matched_oid = None
        with self.Session() as s:
            for oid in oids:
                m = s.query(OrderMeta).get(str(oid))
                if m:
                    meta = m
                    matched_oid = oid
                    break
        if not meta:
            logger.debug("on_user_trade: no OrderMeta for any oid candidates=%s", oids[:5])
            return
        
        with self._lock:
            rt = self._inst_by_id.get(str(meta.strategy_instance_id))  # ключи в _inst_by_id — строки

        if not rt:
            logger.debug(
                "on_user_trade: instance runtime not found for meta.strategy_instance_id=%s (order_id=%s)",
                meta.strategy_instance_id, matched_oid or oids[0]
            )
            return
        logger.info("🔔 user_trade routed: order_id=%s -> instance_id=%s (%s)",
                    matched_oid or oids[0], meta.strategy_instance_id, rt.strategy.name)


        # ✅ Если для этого order_id уже есть strategy_event (handled или нет) —
        # уведомление ПО ВСЕЙ ЛОГИКЕ идёт через poller. Прямой путь глушим.
        try:
            with self.Session() as s:
                exists_any = (
                    s.query(StrategyEvent.id)
                     .filter(
                         StrategyEvent.order_id == str(matched_oid or oids[0]),
                         StrategyEvent.event_type == "FILL",
                     ).first()
                )
            if exists_any:
                logger.debug(
                    "on_user_trade: direct path suppressed — strategy_event exists (order_id=%s)",
                    matched_oid or oids[0]
                )
                return
            # Пробросим event как есть (стратегия сама может вытащить нужный oid/поля)
            rt.impl.on_user_trade(ev)
        except Exception as e:
            logger.exception("on_user_trade failed for instance %s", meta.strategy_instance_id)
            self._notify_error(f"on_user_trade:{meta.strategy_instance_id}", f"on_user_trade(instance={meta.strategy_instance_id}) direct", e)
            try:
                self._trip_circuit_breaker(str(meta.strategy_instance_id), f"on_user_trade(instance={meta.strategy_instance_id}) direct", e)
            except Exception:
                logger.exception("circuit breaker failed for instance %s", meta.strategy_instance_id)
                self._notify_error(
                    f"on_user_trade:{meta.strategy_instance_id}",
                    f"on_user_trade(instance={meta.strategy_instance_id}) direct",
                    e,
                )