# FILE: agents/marketchanel.py
import json
import signal
import sys
import atexit
import threading
import select
import os
import logging
import time
from decimal import Decimal
from hashlib import sha256

from common.db import engine
from logic.ws.client import WebSocketOrderBook
from logic.market_state import MarketState
from logic.rules_engine import RulesEngine
from logic.strategy_engine import StrategyEngine
from common.db import Session
from logic.trading_core import build_tick_size_change_event_key, insert_marketchanel_event

from logic.notifications import send_telegram_to
from logic.market_data_service import MarketDataService
from common.polymarket_utils import clob_place_order, clob_cancel_order


from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from logic.listen_admin import list_enabled_assets
from common.logger import get_logger 
logger = get_logger(__name__)

# logic.ws.client logs every public WS event (price_change asset=None, PONG, etc.).
# For strategy debugging this is too noisy, so default to WARNING.
# Set MARKET_WS_CLIENT_LOG_LEVEL=INFO if you need raw WS event diagnostics again.
_ws_client_log_level = (os.getenv("MARKET_WS_CLIENT_LOG_LEVEL") or "WARNING").strip().upper()
logging.getLogger("logic.ws.client").setLevel(getattr(logging, _ws_client_log_level, logging.WARNING))

"""
Запуск публичного market-канала Polymarket WebSocket.
- Подписка по `asset_ids`.
- Храним L2-книгу в памяти и ленту последних сделок (10 шт.).
- Печать книги/ленты — ТОЛЬКО по событиям из сокета (с троттлингом), без таймера.
"""



MARKET_WSS = "wss://ws-subscriptions-clob.polymarket.com"
Session = sessionmaker(bind=engine, expire_on_commit=False)
market_data = MarketDataService(session_factory=Session)
# Правила создаются только trade-лидером, но переменная должна существовать на уровне модуля,
# т.к. on_event_market_factory читает её из global scope.
rules = None

# Настройки вывода
DEPTH_PRINT = 4
PRINT_ON_EVENT_MIN_INTERVAL = 1.0  # сек — троттлинг печати по событиям
TAPE_MAX = 10
RELOAD_RULES_INTERVAL = 10   # сек — как часто переподгружать правила
SHOW_ORDERBOOK = False  # ← отключаем печать стакана/ленты в лог

CUSTOM_FEATURE_ENABLED = (os.getenv("CUSTOM_FEATURE_ENABLED") or "false").strip().lower() == "true"
TICK_SIZE_CHANGE_CHAT_ID = (os.getenv("TICK_SIZE_CHANGE_CHAT_ID") or "").strip()
MARKET_RESOLVED_CHAT_ID = (os.getenv("MARKET_RESOLVED_CHAT_ID") or TICK_SIZE_CHANGE_CHAT_ID or "").strip()
DESIRED_ASSETS_RECONCILE_SEC = float(os.getenv("DESIRED_ASSETS_RECONCILE_SEC") or "10")

# (опционально) Если хочешь стартовать ТОЛЬКО по правилам — выключи fallback
ALLOW_FALLBACK_ASSET = (os.getenv("ALLOW_FALLBACK_ASSET") or "false").strip().lower() in {"1", "true", "yes", "y", "on"}
FALLBACK_ASSETS = ["56831000532202254811410354120402056896323359630546371545035370679912675847818"]


# === Роли и безопасность (multi-marketchanel) ===
# RUN_ROLE:
#   - "notify": только нотификации (без трейда)
#   - "trade": трейд + нотификации (но только один процесс может быть лидером по advisory lock)
RUN_ROLE = (os.getenv("RUN_ROLE") or "notify").strip().lower()

# Разрешённые kind стратегий для данного процесса (Способ A)
# Пример:
#   notify: ALLOWED_STRATEGY_KINDS=notifier,simple_notify_on_fill
#   trade:  ALLOWED_STRATEGY_KINDS=buyer,notifier,quiet_buyer
_raw_kinds = (os.getenv("ALLOWED_STRATEGY_KINDS") or "").strip()
if _raw_kinds:
    ALLOWED_STRATEGY_KINDS = [k.strip().lower() for k in _raw_kinds.split(",") if k.strip()]
else:
    ALLOWED_STRATEGY_KINDS = []  # пусто = разрешены все

# Advisory lock для роли trade (не даём двум процессам торговать одновременно)
TRADE_LOCK_KEY = int(os.getenv("TRADE_LOCK_KEY") or "4200420042")
_trade_lock_conn = None
_is_trade_leader = False
TRADE_LOCK_RETRY_S = float(os.getenv("TRADE_LOCK_RETRY_S") or "5")

def _try_acquire_trade_lock() -> bool:
    """
    Если RUN_ROLE=trade, пытаемся взять pg_try_advisory_lock.
    НИКОГДА не понижаем роль. Если lock занят — остаёмся read-only и будем ретраить.
    Соединение держим открытым (и для удержания lock, и чтобы не плодить коннекты).
    """
    global _trade_lock_conn, _is_trade_leader
    if RUN_ROLE != "trade":
        return False

    try:
        if _trade_lock_conn is None:
            _trade_lock_conn = engine.connect()
        got = bool(
            _trade_lock_conn.exec_driver_sql(
                "SELECT pg_try_advisory_lock(%s)", (TRADE_LOCK_KEY,)
            ).scalar()
        )
        if got:
            _is_trade_leader = True
            logger.info("🔒 trade lock acquired (key=%s). role=trade (leader)", TRADE_LOCK_KEY)
            return True
        return False
    except Exception:
        logger.exception("trade lock acquisition failed (will retry)")
        return False

def _release_trade_lock():
    global _trade_lock_conn
    if _trade_lock_conn is None:
        return
    try:
        _trade_lock_conn.exec_driver_sql("SELECT pg_advisory_unlock(%s)", (TRADE_LOCK_KEY,))
    except Exception:
        pass
    try:
        _trade_lock_conn.close()
    except Exception:
        pass
    _trade_lock_conn = None

atexit.register(_release_trade_lock)



def _short(s: str, n: int = 6) -> str:
    if not s:
        return ""
    return f"{s[:n]}…{s[-n:]}" if len(s) > 2 * n else s

def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _event_value(event: dict, *keys: str):
    for key in keys:
        if key in event and event.get(key) is not None:
            return event.get(key)
    return None


def _normalize_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_generic_event_key(event_type: str, event: dict) -> str:
    """
    Стабильный ключ дедупликации для market-channel событий.
    Если есть явный id/instance_id/timestamp+market/asset_id — используем их.
    Иначе fallback на sha256 от нормализованного payload.
    """
    instance_id = _normalize_text(_event_value(event, "instance_id", "instanceId"))
    if instance_id:
        return f"{event_type}:{instance_id}"

    event_id = _normalize_text(_event_value(event, "id", "event_id", "eventId"))
    if event_id:
        return f"{event_type}:{event_id}"

    market = _normalize_text(_event_value(event, "market", "market_id", "marketId"))
    asset_id = _normalize_text(_event_value(event, "asset_id", "assetId"))
    condition_id = _normalize_text(_event_value(event, "condition_id", "conditionId"))
    timestamp = _normalize_text(_event_value(event, "timestamp", "ts", "created_at", "createdAt"))

    parts = [event_type, market or "-", asset_id or "-", condition_id or "-", timestamp or "-"]
    compact_key = ":".join(parts)
    if timestamp or market or asset_id or condition_id:
        return compact_key

    raw = json.dumps(event, sort_keys=True, ensure_ascii=False, default=str)
    return f"{event_type}:sha256:{sha256(raw.encode('utf-8')).hexdigest()}"


def _maybe_store_special_event(event_type: str, event: dict):
    if not CUSTOM_FEATURE_ENABLED:
        return

    try:
        with Session() as s:
            insert_marketchanel_event(
                s,
                event_type=event_type,
                event_key=_build_generic_event_key(event_type, event),
                payload={
                    "asset_id": _event_value(event, "asset_id", "assetId"),
                    "market": _event_value(event, "market", "market_id", "marketId"),
                    "condition_id": _event_value(event, "condition_id", "conditionId"),
                    "instance_id": _event_value(event, "instance_id", "instanceId"),
                    "timestamp": _event_value(event, "timestamp", "ts", "created_at", "createdAt"),
                    "status": _event_value(event, "status"),
                    "question": _event_value(event, "question"),
                    "slug": _event_value(event, "slug"),
                    "outcome": _event_value(event, "outcome"),
                },
                raw_event=dict(event or {}),
                source="market_channel",
                asset_id=_normalize_text(_event_value(event, "asset_id", "assetId")),
                market=_normalize_text(_event_value(event, "market", "market_id", "marketId")),
                condition_id=_normalize_text(_event_value(event, "condition_id", "conditionId")),
                instance_id=_normalize_text(_event_value(event, "instance_id", "instanceId")),
            )
            s.commit()
    except Exception:
        logger.exception("insert_marketchanel_event failed for special event_type=%s", event_type)


def _maybe_notify_tick_size_change(event: dict):
    chat_id = TICK_SIZE_CHANGE_CHAT_ID
    if not chat_id:
        return

    try:
        asset_id = _event_value(event, "asset_id", "assetId")
        market = _event_value(event, "market", "market_id", "marketId")
        old_tick_size = _event_value(event, "old_tick_size", "oldTickSize")
        new_tick_size = _event_value(event, "new_tick_size", "newTickSize")
        timestamp = _event_value(event, "timestamp", "ts")

        text = (
            "📏 Tick size changed\n"
            f"market={market}\n"
            f"asset_id={asset_id}\n"
            f"old={old_tick_size}\n"
            f"new={new_tick_size}\n"
            f"ts={timestamp}"
        )
        send_telegram_to(chat_id, text)
    except Exception:
        logger.exception("tick_size_change telegram notify failed")

def _maybe_notify_market_resolved(event: dict):
    chat_id = MARKET_RESOLVED_CHAT_ID
    if not chat_id:
        return

    try:
        market = _event_value(event, "market", "condition_id", "conditionId")
        question = _event_value(event, "question")
        slug = _event_value(event, "slug")
        winning_asset_id = _event_value(event, "winning_asset_id", "winningAssetId")
        winning_outcome = _event_value(event, "winning_outcome", "winningOutcome")
        timestamp = _event_value(event, "timestamp", "ts")

        assets_ids_raw = (
            event.get("assets_ids")
            or event.get("asset_ids")
            or event.get("clob_token_ids")
            or []
        )

        if isinstance(assets_ids_raw, str):
            assets_ids = [assets_ids_raw]
        elif isinstance(assets_ids_raw, list):
            assets_ids = [str(x).strip() for x in assets_ids_raw if str(x or "").strip()]
        else:
            assets_ids = []

        short_assets = ", ".join(_short(x, 10) for x in assets_ids[:6])
        if len(assets_ids) > 6:
            short_assets += f", ... +{len(assets_ids) - 6}"

        lines = [
            "✅ Market resolved",
            f"market={market}",
            f"winning_outcome={winning_outcome}",
            f"winning_asset_id={winning_asset_id}",
            f"assets_count={len(assets_ids)}",
        ]

        if short_assets:
            lines.append(f"assets={short_assets}")
        if question:
            lines.append(f"question={question}")
        if slug:
            lines.append(f"slug={slug}")
        if timestamp:
            lines.append(f"ts={timestamp}")

        send_telegram_to(chat_id, "\n".join(lines))

    except Exception:
        logger.exception("market_resolved telegram notify failed")

def load_listen_assets() -> list[str]:
    """Список asset_id, которые нужно слушать (enabled=TRUE). Через общий хелпер."""
    with Session() as s:
        return list_enabled_assets(s)
    
def load_strategy_instance_assets() -> list[str]:
    """
    Safety net: asset_id из активных strategy_instance.

    Поддерживает оба формата params:
      - top-level asset_id / assetId / asset;
      - sport_best_bid_trigger: params["assets"] = [{"asset_id": ...}, ...].

    Это защищает от кейсов, когда listen_asset не успел создаться или LISTEN/NOTIFY
    был пропущен. Учитываем ALLOWED_STRATEGY_KINDS, чтобы процесс не подписывался
    на чужие kind в multi-process режиме.
    """
    sql = text("""
        select
            si.id as instance_id,
            si.params as params,
            st.kind as strategy_kind
        from strategy_instance si
        join strategy st
            on st.id::text = si.strategy_id::text
        where st.status::text = 'ENABLED'
          and si.status::text in ('PENDING', 'RUNNING')
    """)

    allowed_kinds = {
        str(k).strip().lower()
        for k in (ALLOWED_STRATEGY_KINDS or [])
        if str(k).strip()
    }

    out: set[str] = set()

    with Session() as s:
        rows = s.execute(sql).mappings().all()

    for row in rows:
        strategy_kind = str(row.get("strategy_kind") or "").strip().lower()
        if allowed_kinds and strategy_kind not in allowed_kinds:
            continue

        params = row.get("params") or {}
        if not isinstance(params, dict):
            continue

        for key in ("asset_id", "assetId", "asset"):
            asset_id = str(params.get(key) or "").strip()
            if asset_id:
                out.add(asset_id)

        assets = params.get("assets") or []
        if isinstance(assets, list):
            for item in assets:
                if not isinstance(item, dict):
                    continue
                asset_id = str(
                    item.get("asset_id")
                    or item.get("assetId")
                    or item.get("asset")
                    or ""
                ).strip()
                if asset_id:
                    out.add(asset_id)

    return sorted(out)

def load_desired_assets() -> list[str]:
    """
    Итоговый список WS-подписки:
      1) старый listen_asset;
      2) asset_id из активных strategy_instance.
    """
    assets: set[str] = set()

    try:
        assets.update(
            str(x).strip()
            for x in load_listen_assets()
            if str(x or "").strip()
        )
    except Exception:
        logger.exception("load_listen_assets failed")

    try:
        assets.update(
            str(x).strip()
            for x in load_strategy_instance_assets()
            if str(x or "").strip()
        )
    except Exception:
        logger.exception("load_strategy_instance_assets failed")

    return sorted(assets)

def cleanup_resolved_market(event: dict) -> None:
    """
    При resolved market:
      1) завершаем активные strategy_instance по condition_id / asset_id;
      2) выключаем listen_asset по assets_ids;
      3) periodic reconcile сам снимет эти asset_id с WS-подписки.
    """
    market = _normalize_text(_event_value(event, "market", "condition_id", "conditionId"))
    assets_ids_raw = (
        event.get("assets_ids")
        or event.get("asset_ids")
        or event.get("clob_token_ids")
        or []
    )

    if isinstance(assets_ids_raw, str):
        assets_ids = [assets_ids_raw]
    elif isinstance(assets_ids_raw, list):
        assets_ids = [str(x).strip() for x in assets_ids_raw if str(x or "").strip()]
    else:
        assets_ids = []

    if not market and not assets_ids:
        logger.warning("market_resolved cleanup skipped: no market/assets_ids event=%s", event)
        return

    with Session() as s:
        # 1) завершаем активные strategy instances.
        # condition_id обычно равен market; дополнительно матчим по params.asset_id.

        if market:
            s.execute(
                text("""
                    update strategy_instance
                    set status = 'COMPLETED',
                        close_reason = coalesce(close_reason, 'market_resolved'),
                        runtime_state = coalesce(runtime_state, '{}'::jsonb)
                            || jsonb_build_object(
                                'phase', 'COMPLETED',
                                'close_reason', 'market_resolved',
                                'market_resolved_event', cast(:event_json as jsonb)
                            ),
                        updated_at = now()
                    where status in ('PENDING', 'RUNNING', 'PAUSED')
                      and condition_id = :market
                """),
                {
                    "market": market,
                    "event_json": json.dumps(event, ensure_ascii=False, default=str),
                },
            )

        if assets_ids:
            s.execute(
                text("""
                    update strategy_instance
                    set status = 'COMPLETED',
                        close_reason = coalesce(close_reason, 'market_resolved'),
                        runtime_state = coalesce(runtime_state, '{}'::jsonb)
                            || jsonb_build_object(
                                'phase', 'COMPLETED',
                                'close_reason', 'market_resolved',
                                'market_resolved_event', cast(:event_json as jsonb)
                            ),
                        updated_at = now()
                    where status in ('PENDING', 'RUNNING', 'PAUSED')
                      and coalesce(
                            params ->> 'asset_id',
                            params ->> 'assetId',
                            params ->> 'asset'
                          ) = any(:assets_ids)
                """),
                {
                    "assets_ids": assets_ids,
                    "event_json": json.dumps(event, ensure_ascii=False, default=str),
                },
            )

            # 2) выключаем listen_asset.
            s.execute(
                text("""
                    update listen_asset
                    set enabled = false,
                        note = coalesce(note, '') || ' | disabled: market_resolved',
                        updated_at = now()
                    where asset_id = any(:assets_ids)
                """),
                {"assets_ids": assets_ids},
            )

        s.commit()

    logger.info(
        "🧹 market_resolved cleanup done: market=%s assets_ids=%s",
        market,
        assets_ids,
    )

class WSManager:
    """Менеджер WS-подписки: можно безопасно рестартовать с новым набором asset_id."""
    def __init__(self, *, url: str, on_event_cb):
        self.url = url
        self.on_event_cb = on_event_cb
        self._lock = threading.RLock()
        self._ws: WebSocketOrderBook | None = None
        self._thread: threading.Thread | None = None
        self._asset_ids: list[str] = []

    def current_assets(self) -> list[str]:
        with self._lock:
            return list(self._asset_ids)

    def _spawn(self, asset_ids: list[str]):
        # Если нечего слушать — молча выходим (рестарт решит, что делать)
        if not asset_ids:
            return None
        ws = WebSocketOrderBook(
            "market",
            self.url,
            asset_ids,
            None,
            self.on_event_cb,
            False,                 # verbose off
            auto_reconnect=True,   # keep reconnect on disconnect
            custom_feature_enabled=CUSTOM_FEATURE_ENABLED,
        )
        th = threading.Thread(target=ws.run, name="ws-market-runner", daemon=True)
        th.start()
        self._ws = ws
        self._thread = th
        return ws

    def _stop_current(self):
        with self._lock:
            if self._ws is None:
                return
            try:
                # теперь у клиента есть корректный stop() без дальнейшего реконнекта
                self._ws.stop()
            except Exception:
                pass
            
            # Подождём завершения потока чуть дольше, чтобы хвост успел дойти и поток завершился
            if self._thread is not None:
                deadline = time.time() + 5.0
                # первая попытка
                self._thread.join(timeout=0.5)
                # при необходимости — подождём циклами
                while self._thread.is_alive() and time.time() < deadline:
                    time.sleep(0.2)
                if self._thread.is_alive():
                    logger.warning("⚠️ WS thread is still alive after stop request")
            self._ws = None
            self._thread = None

    def start(self, asset_ids: list[str]):
        with self._lock:
            self._asset_ids = sorted(
                {
                    str(x).strip()
                    for x in (asset_ids or [])
                    if str(x or "").strip()
                }
            )
            logger.info(
                "📡 WS initial start: assets_count=%s assets=%s",
                len(self._asset_ids),
                self._asset_ids,
            )
            self._ws = self._spawn(self._asset_ids)

    def sync_assets(self, asset_ids: list[str]):
        aset_new = set(str(x) for x in (asset_ids or []))

        need_stop = False
        need_spawn = None
        fallback_restart = False
        ws_to_stop = None

        with self._lock:
            aset_old = set(str(x) for x in self._asset_ids)

            to_add_preview = sorted(aset_new - aset_old)
            to_remove_preview = sorted(aset_old - aset_new)

            logger.info(
                "🧭 sync_assets requested: old=%s new=%s add=%s remove=%s",
                sorted(aset_old),
                sorted(aset_new),
                to_add_preview,
                to_remove_preview,
            )

            if aset_new == aset_old:
                logger.info("🧭 sync_assets: no changes")
                return

            # WS ещё не поднят
            if self._ws is None:
                if not aset_new:
                    self._asset_ids = []
                    logger.info("🧭 sync_assets: ws is absent and desired set is empty")
                    return

                self._asset_ids = sorted(aset_new)
                need_spawn = list(self._asset_ids)
                logger.info("🧭 sync_assets: ws absent, will spawn with assets=%s", need_spawn)

            # Нужно полностью остановить подписку
            elif not aset_new:
                logger.info("📴 WS stopped: no subscriptions (was %s)", sorted(aset_old))
                ws_to_stop = self._ws
                self._asset_ids = []
                self._ws = None
                self._thread = None
                need_stop = True

            # Пытаемся динамически досинкать подписки
            else:
                to_add = sorted(aset_new - aset_old)
                to_remove = sorted(aset_old - aset_new)
                ws = self._ws
                logger.info(
                    "🧭 sync_assets dynamic phase: to_add=%s to_remove=%s current=%s",
                    to_add,
                    to_remove,
                    sorted(aset_old),
                )

                try:
                    if to_add:
                        ok = ws.subscribe_market_assets(
                            to_add,
                            custom_feature_enabled=CUSTOM_FEATURE_ENABLED,
                        )
                        if not ok:
                            raise RuntimeError(f"subscribe_market_assets failed for {to_add}")

                    if to_remove:
                        ok = ws.unsubscribe_market_assets(to_remove)
                        if not ok:
                            raise RuntimeError(f"unsubscribe_market_assets failed for {to_remove}")

                    self._asset_ids = sorted(aset_new)
                    logger.info(
                        "🧩 WS dynamic sync ok: +%s -%s final=%s",
                        to_add,
                        to_remove,
                        sorted(aset_new),
                    )
                    return

                except Exception:
                    logger.exception("dynamic WS sync failed; fallback to full restart")
                    ws_to_stop = ws
                    self._asset_ids = sorted(aset_new)
                    self._ws = None
                    self._thread = None
                    need_stop = True
                    need_spawn = list(self._asset_ids)
                    fallback_restart = True

        # stop/spawn делаем вне lock
        if need_stop and ws_to_stop is not None:
            thread_to_join = None

            with self._lock:
                # Берём ссылку на старый поток, если он ещё тот же самый
                if self._ws is None and self._thread is not None:
                    thread_to_join = self._thread

            try:
                ws_to_stop.stop()
            except Exception:
                logger.exception("failed to stop old ws during sync_assets")

            if thread_to_join is not None:
                try:
                    deadline = time.time() + 5.0
                    thread_to_join.join(timeout=0.5)
                    while thread_to_join.is_alive() and time.time() < deadline:
                        time.sleep(0.2)
                    if thread_to_join.is_alive():
                        logger.warning("⚠️ WS thread is still alive after sync_assets stop request")
                except Exception:
                    logger.exception("failed to join old ws thread during sync_assets")

        if need_spawn:
            with self._lock:
                # пока мы были вне lock, кто-то уже мог успеть поднять новый ws
                if self._ws is None and set(self._asset_ids) == set(need_spawn):
                    self._spawn(need_spawn)
                    if fallback_restart:
                        logger.info("🔁 WS restarted with assets=%s", sorted(need_spawn))
                    else:
                        logger.info("📡 WS start with assets=%s", sorted(need_spawn))
# Периодический принтер удалён: печатаем только в обработчике WS-событий (см. on_event_market_factory)

def on_event_market_factory(
    state: MarketState,
    assets_getter,
    market_data: MarketDataService,
    strategy_engine: StrategyEngine | None = None,
):
    # троттлинг печати по событиям
    last_print_ts = [0.0]
    def _on_event(event: dict):
        et = (event.get("event_type") or event.get("type") or "").lower()

        # WS может присылать батчи: price_changes / changes -> [ {asset_id, ...}, ... ]
        batch = event.get("price_changes") or event.get("changes")
        touched = set()
        allowed = set(assets_getter() or [])

        def _asset_id_from_event(row: dict) -> str | None:
            return _normalize_text(_event_value(row, "asset_id", "assetId", "token_id", "tokenId"))

        def _enrich_asset_event(event_type: str, parent: dict, row: dict, aid: str) -> dict:
            # price_changes batch rows often contain only asset_id + price fields, while
            # market/timestamp live on the parent event. Strategies need a normalized event.
            out = dict(row or {})
            out.setdefault("event_type", event_type)
            out.setdefault("type", event_type)
            out.setdefault("asset_id", aid)
            for key in (
                "market", "market_id", "marketId",
                "condition_id", "conditionId",
                "timestamp", "ts", "time",
                "tick_size", "old_tick_size", "new_tick_size",
            ):
                if out.get(key) is None and parent.get(key) is not None:
                    out[key] = parent.get(key)
            return out

        def _route_strategy_event(aid: str, ev: dict):
            if strategy_engine is None or not aid:
                return
            try:
                strategy_engine.on_market_event(aid, ev)
            except Exception:
                logger.exception("strategy_engine.on_market_event failed for asset %s", aid)

        if isinstance(batch, list) and batch:
            for ch in batch:
                if not isinstance(ch, dict):
                    continue
                aid = _asset_id_from_event(ch)
                if not aid or (allowed and aid not in allowed):
                    continue
                ch = _enrich_asset_event(et, event, ch, aid)
                if et == "book":
                    state.on_book(aid, ch)
                    # сохраняем слепок ордербука в БД
                    try:
                        market_data.save_orderbook(asset_id=aid, condition_id=None, book=ch)
                    except Exception:
                        logger.exception("save_orderbook failed for asset %s", aid)
                    _route_strategy_event(aid, ch)
                elif et == "price_change":
                    state.on_price_change(aid, ch)
                    try:
                        market_data.apply_price_change(asset_id=aid, condition_id=None, change=ch)
                    except Exception:
                        logger.exception("apply_price_change failed for asset %s", aid)
                    _route_strategy_event(aid, ch)
                elif et == "tick_size_change":
                    state.on_tick_size_change(aid, ch)
                    try:
                        with Session() as s:
                            insert_marketchanel_event(
                                s,
                                event_type="tick_size_change",
                                event_key=build_tick_size_change_event_key(ch),
                                payload={
                                    "asset_id": ch.get("asset_id"),
                                    "market": ch.get("market"),
                                    "old_tick_size": ch.get("old_tick_size"),
                                    "new_tick_size": ch.get("new_tick_size"),
                                    "timestamp": ch.get("timestamp"),
                                },
                                raw_event=dict(ch or {}),
                                source="market_channel",
                                asset_id=(str(ch.get("asset_id")).strip() if ch.get("asset_id") is not None else None),
                                market=(str(ch.get("market")).strip() if ch.get("market") is not None else None),
                                condition_id=(str(ch.get("condition_id")).strip() if ch.get("condition_id") is not None else None),
                                instance_id=(str(ch.get("instance_id")).strip() if ch.get("instance_id") is not None else None),
                            )
                            s.commit()
                    except Exception:
                        logger.exception("insert_marketchanel_event failed for asset %s", aid)

                    _maybe_notify_tick_size_change(ch)

                    _route_strategy_event(aid, ch)

                elif et in {"market_resolved", "new_market"}:
                    _maybe_store_special_event(et, ch)
                    if et == "market_resolved":
                        _maybe_notify_market_resolved(ch)
                        try:
                            cleanup_resolved_market(ch)
                        except Exception:
                            logger.exception("market_resolved cleanup failed")

                elif et == "last_trade_price":
                    state.on_trade(aid, ch)
                    try:
                        market_data.add_trade(asset_id=aid, condition_id=None, trade_event=ch, max_trades=100)
                    except Exception:
                        logger.exception("add_trade failed for asset %s", aid)
                    _route_strategy_event(aid, ch)
                touched.add(aid)
        else:
            # единичное событие старого стиля
            aid = _asset_id_from_event(event)
            if et not in {"market_resolved", "new_market"}:
                if not aid or (allowed and aid not in allowed):
                    return
                event = _enrich_asset_event(et, event, event, aid)
            if et == "book":
                state.on_book(aid, event)
                try:
                    market_data.save_orderbook(asset_id=aid, condition_id=None, book=event)
                except Exception:
                    logger.exception("save_orderbook failed for asset %s", aid)
                _route_strategy_event(aid, event)
            elif et == "price_change":
                state.on_price_change(aid, event)
                try:
                    market_data.apply_price_change(asset_id=aid, condition_id=None, change=event)
                except Exception:
                    logger.exception("apply_price_change failed for asset %s", aid)
                _route_strategy_event(aid, event)
            elif et == "tick_size_change":
                state.on_tick_size_change(aid, event)
                try:
                    with Session() as s:
                        insert_marketchanel_event(
                            s,
                            event_type="tick_size_change",
                            event_key=build_tick_size_change_event_key(event),
                            payload={
                                "asset_id": event.get("asset_id"),
                                "market": event.get("market"),
                                "old_tick_size": event.get("old_tick_size"),
                                "new_tick_size": event.get("new_tick_size"),
                                "timestamp": event.get("timestamp"),
                            },
                            raw_event=dict(event or {}),
                            source="market_channel",
                            asset_id=(str(event.get("asset_id")).strip() if event.get("asset_id") is not None else None),
                            market=(str(event.get("market")).strip() if event.get("market") is not None else None),
                            condition_id=(str(event.get("condition_id")).strip() if event.get("condition_id") is not None else None),
                            instance_id=(str(event.get("instance_id")).strip() if event.get("instance_id") is not None else None),
                        )
                        s.commit()
                except Exception:
                    logger.exception("insert_marketchanel_event failed for asset %s", aid)

                _maybe_notify_tick_size_change(event)

                _route_strategy_event(aid, event)

            elif et in {"market_resolved", "new_market"}:
                _maybe_store_special_event(et, event)
                if et == "market_resolved":
                    _maybe_notify_market_resolved(event)
                    try:
                        cleanup_resolved_market(event)
                    except Exception:
                        logger.exception("market_resolved cleanup failed")

            elif et == "last_trade_price":
                state.on_trade(aid, event)
                try:
                    market_data.add_trade(asset_id=aid, condition_id=None, trade_event=event, max_trades=100)
                except Exception:
                    logger.exception("add_trade failed for asset %s", aid)
                _route_strategy_event(aid, event)
            touched.add(aid)

        # Проверка правил по всем затронутым ассетам (только в роли trade)
        if rules is not None:
            for aid in touched:
                try:
                    rules.on_asset_event(aid)
                except Exception as e:
                    logger.warning("rules check failed for %s: %s", aid, e)


        # Печать стакана/ленты — отключаем (можно вернуть, переключив флаг)
        if SHOW_ORDERBOOK:
            now = time.time()
            if touched and now - last_print_ts[0] >= PRINT_ON_EVENT_MIN_INTERVAL:
                logger.info("==== MARKET STATE (depth=%d) ===", DEPTH_PRINT)
                to_print = sorted(a for a in touched if (not allowed or a in allowed))
                lines = state.pretty_print(to_print).splitlines()
                for ln in lines:
                    logger.info(ln)
                logger.info("===============================")
                last_print_ts[0] = now
    return _on_event


if __name__ == "__main__":
    logger.info("🚦 marketchanel start: RUN_ROLE=%s allowed_kinds=%s", RUN_ROLE, ALLOWED_STRATEGY_KINDS or "<ALL>")

    # ✅ Подписка напрямую по asset_ids
    #asset_ids = [
    #    "56831000532202254811410354120402056896323359630546371545035370679912675847818",
    #]

    state = MarketState(depth_print=DEPTH_PRINT, tape_max=TAPE_MAX)
    #start_debug_printer(state, asset_ids)
        
    # === Стратегический движок (ОРКЕСТРАТОР ПРАВИЛ) ===

    # ВАЖНО: при RUN_ROLE=trade мы можем быть НЕ лидером (lock занят).
    # Тогда стартуем read-only, и включим торговлю автоматически, когда станем лидером.
    place_order_fn = None
    cancel_order_fn = None

    strategy_engine = StrategyEngine(
        market_state=state,
        telegram_send_fn=lambda chat_id, text: send_telegram_to(chat_id, text),
        place_order_fn=place_order_fn,
        cancel_order_fn=cancel_order_fn,
        timer_interval_s=2,
        allowed_kinds=ALLOWED_STRATEGY_KINDS,
    )
    strategy_engine.reload()
    strategy_engine.start_timer()
    

    # === Trade-only subsystems ===

    _trade_threads_started = False
    _trade_threads_lock = threading.RLock()

    def _start_trade_subsystems_once():
        global rules, _trade_threads_started
        with _trade_threads_lock:
            if _trade_threads_started:
                return
            logger.info("🚀 starting trade-only subsystems (rules + trade listeners)")

            # Правила могут торговать напрямую (clob_place_order_fn), поэтому их запускаем ТОЛЬКО у лидера
            rules_local = RulesEngine(
                engine=engine,
                state=state,
                telegram_send_fn=lambda chat_id, text: send_telegram_to(chat_id, text),
                clob_place_order_fn=clob_place_order,
                on_rule_fired=strategy_engine.on_rule_fired,
            )
            rules_local.load_active_rules()
            rules = rules_local

            # 2) изменения правил → быстрый ребилд правил (без рестартов WS)
            def _listen_rules_changed():
                raw = engine.raw_connection()
                db = getattr(raw, "driver_connection", raw)
                cur = raw.cursor()
                try:
                    cur.execute("LISTEN rules_changed;")
                    raw.commit()
                    logger.info("👂 LISTEN rules_changed")
                except Exception:
                    logger.warning("LISTEN rules_changed not set (no trigger?)")
                    return
                try:
                    while True:
                        r, _, _ = select.select([db.fileno()], [], [], 5.0)
                        if not r:
                            continue
                        db.poll()
                        while db.notifies:
                            db.notifies.pop(0)
                            try:
                                rules.load_active_rules()
                                strategy_engine.reload()
                                current = manager.current_assets()
                                for aid in current:
                                    try:
                                        rules.on_asset_event(aid)
                                    except Exception as e:
                                        logger.warning("rules reevaluate failed for %s: %s", aid, e)
                            except Exception:
                                logger.error("reload rules failed")
                finally:
                    try:
                        cur.close(); raw.close()
                    except Exception:
                        pass

            # 3) сделки пользователя из userchanel → StrategyEngine
            def _listen_user_trades():
                raw = engine.raw_connection()
                db = getattr(raw, "driver_connection", raw)
                cur = raw.cursor()
                try:
                    cur.execute("LISTEN user_trade_event;")
                    raw.commit()
                    logger.info("👂 LISTEN user_trade_event")
                except Exception:
                    logger.warning("LISTEN user_trade_event not set (no trigger/rights?)")
                    return
                try:
                    while True:
                        r, _, _ = select.select([db.fileno()], [], [], 5.0)
                        if not r:
                            continue
                        db.poll()
                        while db.notifies:
                            note = db.notifies.pop(0)
                            payload = note.payload or ""
                            try:
                                evt = json.loads(payload) if payload else {}
                            except Exception:
                                logger.warning("bad user_trade_event payload: %s", payload[:200])
                                evt = {}
                            try:
                                logger.info("📥 user_trade_event recv payload=%s", payload[:500])
                            except Exception:
                                pass
                            try:
                                strategy_engine.on_user_trade(evt)
                                logger.info("➡️ routed user_trade_event to StrategyEngine (order_id=%s)", evt.get("order_id"))
                            except Exception:
                                logger.exception("strategy on_user_trade failed")
                finally:
                    try:
                        cur.close(); raw.close()
                    except Exception:
                        pass

            # 4) быстрый хинт о новых strategy_event
            def _listen_strategy_events():
                raw = engine.raw_connection()
                db = getattr(raw, "driver_connection", raw)
                cur = raw.cursor()
                try:
                    cur.execute("LISTEN strategy_event_new;")
                    raw.commit()
                    logger.info("👂 LISTEN strategy_event_new")
                except Exception:
                    logger.warning("LISTEN strategy_event_new not set")
                    try:
                        cur.close(); raw.close()
                    except Exception:
                        pass
                    return
                try:
                    while True:
                        r, _, _ = select.select([db.fileno()], [], [], 5.0)
                        if not r:
                            continue
                        db.poll()
                        while db.notifies:
                            db.notifies.pop(0)
                            try:
                                strategy_engine.poll_events_once(max_rows=200)
                            except Exception:
                                logger.exception("poll_events_once() on notify failed")
                finally:
                    try:
                        cur.close(); raw.close()
                    except Exception:
                        pass

            threading.Thread(target=_listen_rules_changed, name="rules-listen", daemon=True).start()
            threading.Thread(target=_listen_user_trades, name="user-trades-listen", daemon=True).start()
            threading.Thread(target=_listen_strategy_events, name="strategy-events-listen", daemon=True).start()

            _trade_threads_started = True

    def _trade_lock_manager():
        """
        Если RUN_ROLE=trade, ждём, пока освободится advisory lock.
        Как только стали лидером — включаем торговлю в StrategyEngine и поднимаем trade-only подсистемы.
        """
        if RUN_ROLE != "trade":
            return
        # первая попытка сразу
        while True:
            if _is_trade_leader:
                strategy_engine.set_trade_fns(place_order_fn=clob_place_order, cancel_order_fn=clob_cancel_order)
                _start_trade_subsystems_once()
                return
            got = _try_acquire_trade_lock()
            if got:
                # включаем торговлю в движке (важно: обновить уже загруженные ctx)
                strategy_engine.set_trade_fns(place_order_fn=clob_place_order, cancel_order_fn=clob_cancel_order)
                _start_trade_subsystems_once()
                return
            logger.warning("🔒 trade lock busy (key=%s). staying read-only; retry in %ss", TRADE_LOCK_KEY, TRADE_LOCK_RETRY_S)
            time.sleep(TRADE_LOCK_RETRY_S)

    # стартуем менеджер lock’а отдельным потоком (чтобы main-thread не блокировать)
    threading.Thread(target=_trade_lock_manager, name="trade-lock-manager", daemon=True).start()

    # Начальный набор подписки:
    #   1) listen_asset;
    #   2) активные strategy_instance.params.asset_id / assetId / asset.
    initial_assets = load_desired_assets()
    logger.info(
        "🎯 initial desired assets loaded: count=%s assets=%s",
        len(initial_assets),
        sorted(map(str, initial_assets)),
    )

    if not initial_assets and ALLOW_FALLBACK_ASSET:
        # fallback для ручного теста
        initial_assets = FALLBACK_ASSETS
        logger.warning("⚠️ using FALLBACK_ASSETS=%s", FALLBACK_ASSETS)
        
    # Менеджер WS
    manager = WSManager(url=MARKET_WSS, on_event_cb=None)
    # теперь можно безопасно передать getter, потому что manager уже создан
    manager.on_event_cb = on_event_market_factory(
        state,
        assets_getter=manager.current_assets,
        market_data=market_data,
        strategy_engine=strategy_engine,
    )
    manager.start(initial_assets)


    # === LISTEN/NOTIFY ===
    # 1) изменения набора рынков для подписки → dynamic subscribe/unsubscribe
    def _listen_assets_changed():
        raw = engine.raw_connection()
        db = getattr(raw, "driver_connection", raw)  # SQLAlchemy 2.x: DB-API коннект без депрекейта
        cur = raw.cursor()
        cur.execute("LISTEN assets_listen_changed;")
        raw.commit()
        logger.info("👂 LISTEN assets_listen_changed")
        try:
            while True:
                r, _, _ = select.select([db.fileno()], [], [], 5.0)
                if not r:
                    continue
                db.poll()
                while db.notifies:
                    db.notifies.pop(0)
                    try:
                        desired = load_desired_assets()
                        logger.info(
                            "👂 assets_listen_changed -> desired assets count=%s assets=%s",
                            len(desired),
                            sorted(map(str, desired)),
                        )
                        manager.sync_assets(desired)

                    except Exception:
                        logger.exception("reload desired assets failed")
        except Exception:
            logger.error("assets LISTEN error")
        finally:
            try:
                cur.close()
                raw.close()
            except Exception:
                pass
    threading.Thread(target=_listen_assets_changed, name="assets-listen", daemon=True).start()

    def _periodic_assets_reconcile():
        """
        Safety net: если LISTEN assets_listen_changed был пропущен,
        marketchanel всё равно подтянет актуальный desired assets.
        """
        while True:
            try:
                time.sleep(DESIRED_ASSETS_RECONCILE_SEC)

                desired = load_desired_assets()
                current = manager.current_assets()

                desired_set = {
                    str(x).strip()
                    for x in (desired or [])
                    if str(x or "").strip()
                }
                current_set = {
                    str(x).strip()
                    for x in (current or [])
                    if str(x or "").strip()
                }

                if desired_set != current_set:
                    logger.warning(
                        "🧭 assets reconcile mismatch: current_count=%s desired_count=%s "
                        "add=%s remove=%s",
                        len(current_set),
                        len(desired_set),
                        sorted(desired_set - current_set),
                        sorted(current_set - desired_set),
                    )
                    manager.sync_assets(sorted(desired_set))

            except Exception:
                logger.exception("periodic assets reconcile failed")

    if DESIRED_ASSETS_RECONCILE_SEC > 0:
        threading.Thread(
            target=_periodic_assets_reconcile,
            name="assets-periodic-reconcile",
            daemon=True,
        ).start()
    else:
        logger.warning("⚠️ periodic assets reconcile disabled")

     
    def _shutdown():
        logger.info("🛑 Завершаем корректно")
        try:
            # Остановим текущий WS (через менеджер)
            manager.sync_assets([])  # снимаем подписку / останавливаем WS
        except Exception:
            pass
        try:
            engine.dispose()
        except Exception:
            pass
        sys.exit(0)

    atexit.register(_shutdown)
    for _sig in ("SIGTERM", "SIGINT"):
        if hasattr(signal, _sig):
            signal.signal(getattr(signal, _sig), lambda s, f: _shutdown())
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda s, f: _shutdown())

    try:
        while True:
            time.sleep(3600)  # главный поток живёт, WS и вотчеры — в демонах
    except KeyboardInterrupt:
        _shutdown()
