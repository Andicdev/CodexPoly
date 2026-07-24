import json, signal, sys, logging
from common import config
from common.db import Session, engine
from logic.ws.client import WebSocketOrderBook
from logic.services.trade_service import handle_trade_event
from logic.services.order_service import insert_order
from py_clob_client.client import ClobClient
from common.logger import get_logger 
from sqlalchemy import text
logger = get_logger(__name__)


def on_event_user(event: dict):
    # event — это RAW WS payload
    # тип может приходить как 'event_type' или как 'type'
    et = (event.get("event_type") or event.get("type") or "").lower()
    if et == "trade":
        # Диагностика входного события по доке
        logger.info("🔎 user trade keys=%s trader_side=%s", list(event.keys()), event.get("trader_side"))

        handle_trade_event(event, Session, clob_client)
        # 👉 после успешной обработки — отправим NOTIFY(и) для стратегий
        try:
            def _notify(payload_dict: dict):
                payload = json.dumps(payload_dict, ensure_ascii=False)
                logger.info("📤 NOTIFY user_trade_event payload=%s", payload)
                raw = engine.raw_connection()
                cur = raw.cursor()
                # ⚠️ raw-курсор — только строковый SQL (без sqlalchemy.text)
                cur.execute("NOTIFY user_trade_event, %s", (payload,))
                raw.commit()
                try:
                    cur.close(); raw.close()
                except Exception:
                    pass

            trade_id = event.get("id")
            tx_hash = event.get("transaction_hash")
            trader_side = (event.get("trader_side") or "").upper()

            # trader_side по доке: TAKER → taker_order_id; MAKER → maker_orders[*].order_id
            if not trader_side:
                trader_side = "TAKER" if event.get("taker_order_id") else ("MAKER" if event.get("maker_orders") else "")

            if trader_side == "TAKER":
                order_id = event.get("taker_order_id") or event.get("order_id")
                if not order_id:
                    logger.warning("TAKER trade but no taker_order_id/order_id in event; skip notify")
                else:
                    _notify({
                        "type": "trade",
                        "trade_id": trade_id,
                        "transaction_hash": tx_hash,
                        "trader_side": trader_side,
                        "raw_event": event,
                        "asset_id": event.get("asset_id"),
                        "order_id": order_id,
                        "side": event.get("side"),
                        "price": event.get("price"),
                        "size": event.get("size"),
                        "executed_at": event.get("timestamp") or event.get("executed_at"),
                    })
            elif trader_side == "MAKER":
                # Несколько NOTIFY — по каждой нашей maker-ноге (может исполниться сетка)
                mine1 = (event.get("trade_owner") or "").lower()
                mine2 = (event.get("owner") or "").lower()
                count = 0
                for mo in (event.get("maker_orders") or []):
                    # В примере из доки у legs поле называется 'owner' (UUID аккаунта)
                    if str(mo.get("owner", "")).lower() not in {mine1, mine2}:
                        continue
                    order_id = mo.get("order_id")
                    if not order_id:
                        logger.warning("MAKER leg without order_id: %s", mo)
                        continue
                    price = mo.get("price") or event.get("price")
                    size  = mo.get("matched_amount") or event.get("size")
                    _notify({
                        "type": "trade",
                        "trade_id": trade_id,
                        "transaction_hash": tx_hash,
                        "trader_side": trader_side,
                        "raw_event": event,
                        "asset_id": event.get("asset_id"),
                        "order_id": order_id,
                        "side": event.get("side"),
                        "price": price,
                        "size": size,
                        "executed_at": event.get("timestamp") or event.get("executed_at"),
                    })
                    count += 1
                if count == 0:
                    logger.info("MAKER trade without our legs — no notify (maker_orders есть, но не наши)")
            else:
                logger.warning("Unknown trader_side for trade event; skip notify. keys=%s", list(event.keys()))
        except Exception:
            logger.exception("failed to NOTIFY user_trade_event")
    elif et == "order":
        s = Session()
        try:
            insert_order(event, s, strategy_id=None)
        finally:
            s.close()
    else:
        # полезно увидеть неизвестные типы на этапе отладки
        logger.info("⚠️ Неизвестный тип события: %s | keys=%s", et, list(event.keys()))

if __name__ == "__main__":
    clob_client = ClobClient(
        host="https://clob.polymarket.com",
        key=config.PK,
        chain_id=137,
        signature_type=1,
        funder=config.POLYMARKET_ADDRESS1,
    )
    clob_client.set_api_creds(clob_client.create_or_derive_api_creds())

    url = "wss://ws-subscriptions-clob.polymarket.com"
    auth = {
        "apiKey": config.POLYMARKET_API_KEY,
        "secret": config.POLYMARKET_API_SECRET,
        "passphrase": config.POLYMARKET_API_PASSPHRASE,
    }
    condition_ids = []  # если фильтруешь рынки — укажи здесь

    ws = WebSocketOrderBook("user", url, condition_ids, auth, on_event_user, True)

    def _handle_sigterm(signum, frame):
        logger.info("🛑 SIGTERM: завершаем корректно")
        try:
            engine.dispose()
        except Exception:
            pass
        sys.exit(0)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    ws.run()
