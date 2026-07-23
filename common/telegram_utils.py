import asyncio
import time
import requests
from common import config
from decimal import Decimal
from common.logger import get_logger
logger = get_logger(__name__)
# from typing import List, Dict, Any, Optional
import re

_TG_API_BASE = "https://api.telegram.org/bot"
_TG_TIMEOUT = float(getattr(config, "TG_HTTP_TIMEOUT", 20))
_TG_SESSION: requests.Session | None = None

def _tg_session() -> requests.Session:
    global _TG_SESSION
    if _TG_SESSION is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "polymarket-bot/telegram_utils"})
        _TG_SESSION = s
    return _TG_SESSION

def _tg_send_sync(*, token: str, chat_id: str | int, text: str, parse_mode: str | None) -> dict:
    """
    Sync sender via Telegram Bot API (no python-telegram-bot, no httpx).
    Raises on non-OK responses.
    """
    url = f"{_TG_API_BASE}{token}/sendMessage"
    payload: dict = {"chat_id": str(chat_id), "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            r = _tg_session().post(url, json=payload, timeout=_TG_TIMEOUT)
            # Telegram can return 200 with {"ok": false, ...}
            data = r.json() if r.headers.get("content-type","").lower().startswith("application/json") else {}

            # Handle HTTP-level rate limit
            if r.status_code == 429:
                retry_after = 2.0
                try:
                    retry_after = float(r.headers.get("Retry-After") or retry_after)
                except Exception:
                    pass
                logger.warning("telegram api 429: sleep %.2fs (attempt %s/3)", retry_after, attempt)
                time.sleep(retry_after)
                continue

            if r.status_code >= 500:
                backoff = 2.0 * attempt
                logger.warning("telegram api %s: sleep %.2fs (attempt %s/3)", r.status_code, backoff, attempt)
                time.sleep(backoff)
                continue

            # Non-200 or ok=false -> raise
            if r.status_code != 200 or not data or not data.get("ok", False):
                desc = ""
                try:
                    desc = str((data or {}).get("description") or "")
                except Exception:
                    desc = ""
                raise RuntimeError(f"Telegram send failed: http={r.status_code} desc={desc[:200]}")

            return data
        except Exception as e:
            # Do not retry Markdown/HTML entity parse errors — caller may fallback to plain text.
            s = ""
            try:
                s = str(e).lower()
            except Exception:
                s = ""
            if ("can't parse entities" in s) or ("cant parse entities" in s) or ("parse entities" in s):
                raise
            last_err = e
            backoff = 1.5 * attempt
            logger.warning("telegram api error: %s (attempt %s/3) -> sleep %.2fs", str(e)[:240], attempt, backoff)
            time.sleep(backoff)
    raise RuntimeError(f"Telegram send failed after retries: {last_err}")

async def _tg_send(*, token: str, chat_id: str | int, text: str, parse_mode: str | None) -> dict:
    return await asyncio.to_thread(_tg_send_sync, token=token, chat_id=chat_id, text=text, parse_mode=parse_mode)

# ---------------- MarkdownV2 safe helper (opt-in) ----------------
_MDV2_SPECIAL = r"_*\[\]()~`>#+\-=|{}.! "
_MDV2_RE = re.compile(r"([_\*\[\]\(\)~`>#+\-=|{}\.\!])")

def tg_escape_markdown_v2(text: str) -> str:
    """
    Escape text for Telegram MarkdownV2.
    Opt-in helper: use only if you set parse_mode="MarkdownV2".
    """
    t = "" if text is None else str(text)
    return _MDV2_RE.sub(r"\\\1", t)

async def send_message_to_chat_mdv2(chat_id: str | int, text: str) -> None:
    """
    Safe send with MarkdownV2 (escapes everything that may break entities).
    Does NOT change existing callers; use from places that currently ломают Markdown.
    """
    await send_message_to_chat(chat_id=str(chat_id), text=tg_escape_markdown_v2(text), parse_mode="MarkdownV2")

def _looks_like_parse_entities(exc: Exception) -> bool:
    """Detect Telegram Markdown/HTML parse errors."""
    try:
        s = str(exc).lower()
    except Exception:
        return False
    return ("can't parse entities" in s) or ("cant parse entities" in s) or ("parse entities" in s)

def _safe_preview(text: str, limit: int = 700) -> str:
    try:
        t = text if text is not None else ""
        t = str(t)
        if len(t) <= limit:
            return t
        return t[:limit] + "…"
    except Exception:
        return "<unprintable>"

async def _notify_send_failure_to_errors(
    *,
    original_chat_id: str | int | None,
    parse_mode: str | None,
    text: str,
    error: Exception,
):
    """
    Best-effort: notify ERRORS_CHANNEL_ID that a TG message failed to send.
    MUST NOT raise and MUST NOT recurse endlessly.
    """
    err_chat = getattr(config, "ERRORS_CHANNEL_ID", None)
    if not err_chat:
        return

    # recursion guard: if we already failed to send into errors channel, stop.
    try:
        if str(original_chat_id) == str(err_chat):
            return
    except Exception:
        pass

    token = config.TG_BOT_TOKEN
    if not token:
        return

    try:

        msg = "\n".join([
            "🚨 Telegram send failed",
            f"• target_chat: {original_chat_id}",
            f"• parse_mode: {parse_mode}",
            f"• error: {type(error).__name__}: {error}",
            f"• text_len: {len(str(text or ''))}",
            "",
            "— preview —",
            _safe_preview(text),
        ])
        # IMPORTANT: send without parse_mode to avoid new parse errors
        await _tg_send(token=token, chat_id=str(err_chat), text=msg, parse_mode=None)

        logger.info("📬 Error notification sent: chat_id=%s", err_chat)
    except Exception as e2:
        # do not recurse
        logger.warning("send_failure_notify: could not send to ERRORS_CHANNEL_ID: %s", e2)


async def handle_order_update(order: dict, changes: list[str]):
    if not changes:
        return

    order_id = order.get("id", "")[:10] + "..."
    question = order.get("question", "❓ Неизвестный рынок")
    market = order.get("market", "???")
    side = order.get("side", "?")
    outcome = order.get("outcome", "?")
    original_size = order.get("original_size", "?")
    size_matched = order.get("size_matched", "?")
    price = order.get("price", "?")

    text = (
        #f"🔄 Обновление ордера {order_id}\n"
        f"🧠 {question}\n"
        #f"• Рынок ID: `{market}`\n"
        f"• {side} {outcome} {price}\n"
        f"• Объём: {original_size} | Матчед: {size_matched}\n\n"
        + "\n".join(f"• {change}" for change in changes)
        + f"\n\n🔗 [Проверить на Polygonscan](https://polygonscan.com/tx/{order.get('id', '')})"
    )

    await send_telegram_message(text)



async def handle_market_notification(market: dict, is_new: bool):
    if not is_new:
        return

    # Здесь в будущем будут фильтры: "если подходит под критерии"
    # например: if not market['question'].lower().startswith("will "): return

    url = f"https://polymarket.com/market/{market['market_slug']}"
    text = f"🆕 Новый рынок:\n{market['question']}\n{url}"

    await send_telegram_message(text)
    await asyncio.sleep(2)  # Задержка для обхода флуда

async def send_telegram_message(
    text: str,
    parse_mode: str | None = "Markdown",
):
    token = config.TG_BOT_TOKEN
    channel_id = config.CHANNEL_ID

    if not token or not channel_id:
        logger.error("⚠️ TG_BOT_TOKEN или CHANNEL_ID не заданы")
        return
    
    logger.info(f"📨 Отправка сообщения в Telegram: {text[:40]}...")
    logger.debug(f"TOKEN={token[:6]}..., CHAT_ID={channel_id}")
    
    for attempt in range(3):
        try:
            await _tg_send(token=token, chat_id=channel_id, text=text, parse_mode=parse_mode)

            logger.info("📬 Уведомление отправлено в канал")
            return
        except Exception as e:
            logger.warning(f"⚠️ Попытка {attempt+1}: Ошибка Telegram: {e}")
            await asyncio.sleep(4 * (attempt + 1))

async def send_message_in_user_channel(
    text: str,
    parse_mode: str | None = "Markdown",
):
    token = config.TG_BOT_TOKEN
    user_channel_id = config.User_CHANNEL_ID  # как и было

    if not token or not user_channel_id:
        logger.error("⚠️ TG_BOT_TOKEN или USER_CHANNEL_ID не заданы")
        return

    logger.info(f"📨 Отправка уведомления в пользовательский канал: {text[:40]}...")
    logger.debug(f"TOKEN={token[:6]}..., CHAT_ID={user_channel_id}")


    for attempt in range(3):
        try:
            await _tg_send(token=token, chat_id=user_channel_id, text=text, parse_mode=parse_mode)

            logger.info("📬 Сообщение отправлено в пользовательский канал")
            return
        except Exception as e:
            logger.warning(f"⚠️ Попытка {attempt+1}: Ошибка Telegram: {e}")
            await asyncio.sleep(4 * (attempt + 1))

# --------- безопасная отправка с разбиением и подробным логом ----------
MAX_TG_TEXT = 3800  # безопасный запас до лимита Telegram 4096

def _chunk_text_by_lines(text: str, max_len: int = MAX_TG_TEXT) -> list[str]:
    """Режем по строкам, чтобы не превысить лимит Telegram и не ломать форматирование."""
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    cur: list[str] = []
    curlen = 0
    for line in text.splitlines():
        add = len(line) + (1 if cur else 0)  # +1 за перевод строки если не первая строка
        if cur and curlen + add > max_len:
            parts.append("\n".join(cur))
            cur, curlen = [line], len(line)
        else:
            if cur:
                cur.append(line)
                curlen += add
            else:
                cur = [line]
                curlen = len(line)
    if cur:
        parts.append("\n".join(cur))
    return parts

async def send_message_safe(
    *,
    text: str,
    channel: int | str | None,
    wallet: str | None = None,
    user_name: str | None = None,
    parse_mode: str | None = "Markdown",
):
    """
    Универсальная «безопасная» отправка: режет длинный текст на части и логирует контекст.
    Никакой зависимости от agents.tasks.public_users — только этот модуль.
    """
    # нормализуем chat_id
    chat_id = None
    if channel is not None:
        if isinstance(channel, str) and channel.lstrip("-").isdigit():
            chat_id = int(channel)
        else:
            chat_id = channel

    chunks = _chunk_text_by_lines(text, MAX_TG_TEXT)
    total = len(chunks)
    for idx, chunk in enumerate(chunks, 1):
        msg = chunk if total == 1 else f"({idx}/{total})\n{chunk}"
        # Лог — из этого модуля (никаких «public_users» в имени логгера)
        logger.info(
            "telegram-send ctx: user=%s wallet=%s chat=%s len=%s part=%s/%s",
            user_name,
            (wallet[:12] + "…") if wallet else None,
            chat_id,
            len(msg),
            idx,
            total,
        )
        if chat_id is not None:
            await send_message_to_chat(chat_id, msg, parse_mode=parse_mode)
        else:
            await send_message_in_user_channel(msg, parse_mode=parse_mode)



async def send_strategy_notification(text: str):
    token = config.TG_BOT_TOKEN
    strategy_channel_id = config.STRATEGY_CHANNEL_ID

    if not token or not strategy_channel_id:
        logger.error("⚠️ TG_BOT_TOKEN или STRATEGY_CHANNEL_ID не заданы")
        return

    logger.info(f"📨 Уведомление в стратегический канал: {text[:40]}...")

    for attempt in range(3):
        try:
            await _tg_send(token=token, chat_id=strategy_channel_id, text=text, parse_mode="Markdown")
            logger.info("📬 Стратегическое уведомление отправлено")
            return
        except Exception as e:
            logger.warning(f"⚠️ Попытка {attempt+1}: Telegram error: {e}")
            await asyncio.sleep(4 * (attempt + 1))

def build_strategy_message(
    strat_name: str,
    slug: str,
    order_type: str,
    event: str,
    side: str,
    token_label: str,
    price: Decimal,
    size: Decimal
) -> str:
    
    if event == "order_placed":
        header = f"📤 Отправлен ордер {side.upper()} для токена {token_label.upper()}"
    elif event == "order_filled":
        header = f"✅ Исполнен ордер {side.upper()} для токена {token_label.upper()}"
    elif event == "stop_loss_placed":
        header = f"✅ Размещен стоп-лосс {side.upper()} для токена {token_label.upper()}"    
    else:
        header = f"📍 Событие по ордеру: {event}"

    return "\n".join([
        header,
        f"📈 Рынок: {slug}",
        f"💰 Цена: `{price}`",
        f"📦 Объём: `{size}`",
        f"📊 Стратегия: {strat_name} ",
        f"🧩 Тип ордера: `{order_type}`"
    ])


async def send_message_to_chat(chat_id: str, text: str, parse_mode: str | None = "Markdown"):


    """
    Универсальная отправка в указанный чат (канал/юзер).
    По умолчанию используем Markdown (как принято в проекте).
    Если parse_mode не нужен — передай None (тогда Telegram получит plain text).
 
    """

    token = config.TG_BOT_TOKEN
    if not token or not chat_id:
        logger.error("⚠️ TG_BOT_TOKEN или chat_id не заданы для send_message_to_chat")
        return
    last_exc: Exception | None = None
    used_fallback_plain = False
    for attempt in range(3):
        try:
            await _tg_send(token=token, chat_id=chat_id, text=text, parse_mode=parse_mode)
            logger.info(f"📬 Сообщение отправлено: chat_id={chat_id}")
            return
        except Exception as e:
            last_exc = e
            # If this is a Markdown parse error, try ONE fallback with parse_mode=None immediately.
            if (not used_fallback_plain) and parse_mode and _looks_like_parse_entities(e):
                used_fallback_plain = True
                try:
                    logger.warning(
                        "⚠️ Telegram parse error (likely Markdown). Fallback to plain text once. chat_id=%s err=%s",
                        chat_id, e
                    )
                    await _tg_send(token=token, chat_id=chat_id, text=text, parse_mode=None)
                    logger.info("📬 Сообщение отправлено (plain fallback): chat_id=%s", chat_id)
                    return
                except Exception as e_fb:
                    last_exc = e_fb
                    logger.warning("⚠️ Plain fallback failed: %s", e_fb)

            logger.warning(f"⚠️ Попытка {attempt+1}: Ошибка Telegram: {e}")
            await asyncio.sleep(4 * (attempt + 1))

    # If we are here — message was NOT sent after retries/fallbacks.
    if last_exc is not None:
        await _notify_send_failure_to_errors(
            original_chat_id=chat_id,
            parse_mode=parse_mode,
            text=text,
            error=last_exc,
        )


# ==== NEW: удобная отправка почасовых сводок (синхронная) ====
def send_ingest_summary_sync(text: str, *, parse_mode: str | None = "Markdown") -> None:
    """
    Синхронная отправка сводки инжеста в чат TELEGRAM_INGEST_CHAT_ID.
    Удобно вызывать из синхронных тасков.
    """
    chat_id = getattr(config, "TELEGRAM_INGEST_CHAT_ID", None)
    if not chat_id:
        logger.info("ingest_summary: TELEGRAM_INGEST_CHAT_ID не задан — пропускаем отправку")
        return
    token = config.TG_BOT_TOKEN
    if not token:
        logger.error("⚠️ TG_BOT_TOKEN не задан — сводка не отправлена")
        return

    async def _run():
        await send_message_to_chat(chat_id=chat_id, text=text, parse_mode=parse_mode)

    try:
        # если уже есть активный loop (на всякий), используем его
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # запускаем корутину как таск — без await (fire-and-forget)
            loop.create_task(_run())
        else:
            asyncio.run(_run())
    except Exception as e:
        logger.warning(f"ingest_summary: ошибка отправки: {e}")

def send_message_to_chat_sync(
    *,
    chat_id: str | int,
    text: str,
    parse_mode: str | None = "Markdown",
) -> None:
    """
    Синхронная отправка сообщения в произвольный Telegram chat_id.
    Удобно вызывать из sync-воркеров.
    """
    if not chat_id:
        logger.info("send_message_to_chat_sync: empty chat_id — пропускаем отправку")
        return

    async def _run():
        await send_message_to_chat(chat_id=str(chat_id), text=text, parse_mode=parse_mode)

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(_run())
        else:
            asyncio.run(_run())
    except Exception as e:
        logger.warning(f"send_message_to_chat_sync: ошибка отправки: {e}")

def send_error_notification_sync(
    text: str,
    *,
    chat_id: str | None = None,
    parse_mode: str | None = None,
) -> None:
    """
    Простой синхронный хелпер для отправки ошибок в отдельный канал.
    Использование:

        try:
            ...
        except Exception as e:
            log.warning("gamma_markets_worker: task failed: %s", e)
            send_error_notification_sync(f"gamma_markets_worker: task failed: {e}")
    """
    # если явно не передали chat_id — берём ERRORS_CHANNEL_ID из конфига
    if chat_id is None:
        chat_id = getattr(config, "ERRORS_CHANNEL_ID", None)
    if not chat_id:
        logger.info("send_error_notification_sync: ERRORS_CHANNEL_ID не задан — пропускаем отправку")
        return

    async def _run():
        await send_message_to_chat(chat_id=str(chat_id), text=text, parse_mode=parse_mode)

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            loop.create_task(_run())
        else:
            asyncio.run(_run())
    except Exception as e:
        logger.warning(f"send_error_notification_sync: ошибка отправки: {e}")