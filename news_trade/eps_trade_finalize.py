# news_trade/eps_trade_finalize.py
from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Optional

from common.logger import get_logger
from common.telegram_utils import send_message_to_chat
from news_trade.eps_orders import place_trade_from_eps_out

logger = get_logger(__name__)


def trade_enabled() -> bool:
    """
    Default: disabled (safe). Enable explicitly:
      EPS_TRADE_ENABLED=1
    """
    v = (os.getenv("EPS_TRADE_ENABLED", "0") or "0").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def send_telegram_sync(chat_id: str | None, text: str) -> None:
    if not chat_id:
        return

    async def _run():
        await send_message_to_chat(chat_id=str(chat_id), text=text, parse_mode=None)

    try:
        asyncio.run(_run())
    except RuntimeError:
        # already running loop
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except Exception:
            logger.exception("telegram send failed (loop)")
    except Exception:
        logger.exception("telegram send failed")


def build_order_placed_message(ticker: str, trade: dict) -> str:
    return "\n".join(
        [
            "✅ Order placed",
            f"• ticker: {ticker}",
            f"• outcome: {trade.get('outcome')}",
            f"• condition_id: {trade.get('condition_id')}",
            f"• account: {trade.get('account_name')}",
            f"• qty: {trade.get('size')}",
            f"• price: {trade.get('price')}",
            f"• orderID: {trade.get('orderID')}",
        ]
    )


def maybe_trade_and_finalize(
    *,
    row: Any,
    row_id: int,
    ticker: str,
    out: dict,
    tg_chat_id: str | None,
    set_status_done_with_trade: Callable[[int, dict, dict], None],
    log_prefix: str = "",
    enabled: Optional[bool] = None,
) -> dict | None:
    """
    Common glue for poll/ws:

      - if trading disabled -> return None
      - else place_trade_from_eps_out(row,out)
      - if skipped -> log and return trade dict
      - if success -> set row done + notify telegram
      - if fail -> log error and return trade dict
    """
    if enabled is None:
        enabled = trade_enabled()

    if not enabled:
        return None

    trade = place_trade_from_eps_out(row, out)  # returns dict
    # robust guards
    if not isinstance(trade, dict):
        logger.error("%s trade returned non-dict: %r", log_prefix, trade)
        return None

    if trade.get("skipped"):
        logger.info(
            "%s trade skipped row_id=%s ticker=%s reason=%s",
            log_prefix,
            row_id,
            ticker,
            trade.get("reason"),
        )
        return trade

    if trade.get("success"):
        try:
            set_status_done_with_trade(int(row_id), out, trade)
        except Exception:
            logger.exception("%s failed to set status done row_id=%s ticker=%s", log_prefix, row_id, ticker)

        try:
            send_telegram_sync(tg_chat_id, build_order_placed_message(ticker, trade))
        except Exception:
            logger.exception("%s failed to telegram order placed row_id=%s ticker=%s", log_prefix, row_id, ticker)

        return trade

    # failed
    logger.error("%s order failed row_id=%s ticker=%s resp=%s", log_prefix, row_id, ticker, trade.get("raw"))
    return trade