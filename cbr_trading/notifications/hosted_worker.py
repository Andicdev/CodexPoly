from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from cbr_trading.notifications.repository import ClaimedNotification
from cbr_trading.notifications.settings import NotificationWorkerSettings
from cbr_trading.telegram import TelegramNotifier


class NotificationOutbox(Protocol):
    def ensure_ready(self) -> None: ...

    def claim_next(
        self,
        *,
        lease_seconds: float,
    ) -> ClaimedNotification | None: ...

    def mark_sent(self, row_id: int) -> None: ...

    def mark_failed(
        self,
        row_id: int,
        *,
        error_code: str,
        retry_delay_seconds: float,
    ) -> None: ...


class TelegramSender(Protocol):
    def send_text(self, text: str): ...


class NotificationHostedWorker:
    """Deliver outbox messages without blocking source or trading workers."""

    def __init__(
        self,
        *,
        settings: NotificationWorkerSettings,
        store: NotificationOutbox,
        sender: TelegramSender,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._store = store
        self._sender = sender
        self._logger = logger or logging.getLogger(
            "cbr_trading.notifications"
        )
        self._claimed_count = 0
        self._sent_count = 0
        self._failed_count = 0

    async def run_once(self) -> bool:
        claimed = await asyncio.to_thread(
            self._store.claim_next,
            lease_seconds=self._settings.lease_seconds,
        )
        if claimed is None:
            return False
        self._claimed_count += 1
        try:
            await asyncio.to_thread(
                self._sender.send_text,
                claimed.message_text,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed_count += 1
            error_code = type(exc).__name__
            try:
                await asyncio.to_thread(
                    self._store.mark_failed,
                    claimed.row_id,
                    error_code=error_code,
                    retry_delay_seconds=self._settings.retry_delay,
                )
            except Exception as persistence_exc:
                self._logger.error(
                    "Telegram notification failure could not be "
                    "persisted row_id=%s error_code=%s",
                    claimed.row_id,
                    type(persistence_exc).__name__,
                )
            self._logger.warning(
                "Telegram source notification failed row_id=%s "
                "attempt=%s error_code=%s",
                claimed.row_id,
                claimed.attempt_count,
                error_code,
            )
            return True
        await asyncio.to_thread(
            self._store.mark_sent,
            claimed.row_id,
        )
        self._sent_count += 1
        self._logger.info(
            "Telegram source notification sent row_id=%s attempt=%s",
            claimed.row_id,
            claimed.attempt_count,
        )
        return True

    async def run_forever(self) -> None:
        await asyncio.to_thread(self._store.ensure_ready)
        self._logger.info("Notification outbox schema ready")
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            while True:
                processed = await self.run_once()
                if not processed:
                    await asyncio.sleep(self._settings.poll_interval)
        finally:
            heartbeat.cancel()
            await asyncio.gather(
                heartbeat,
                return_exceptions=True,
            )

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._settings.heartbeat_interval)
            self._logger.info(
                "Notification heartbeat claimed=%s sent=%s failed=%s",
                self._claimed_count,
                self._sent_count,
                self._failed_count,
            )


def build_telegram_sender(
    settings: NotificationWorkerSettings,
) -> TelegramNotifier:
    return TelegramNotifier(
        bot_token=settings.telegram_bot_token or "",
        chat_id=settings.telegram_chat_id or "",
        timeout=settings.telegram_timeout,
    )
