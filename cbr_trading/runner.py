from __future__ import annotations

import json
import logging
from dataclasses import asdict

from cbr_trading.client import CbrClient, RequestsTransport
from cbr_trading.pipeline import (
    DryRunOrderExecutor,
    PipelineOutcome,
    TradingPipeline,
)
from cbr_trading.poller import CbrPoller
from cbr_trading.settings import CbrSettings
from cbr_trading.telegram import TelegramError, TelegramNotifier


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def main() -> int:
    _load_dotenv_if_available()
    settings = CbrSettings.from_env()
    if not settings.dry_run:
        raise RuntimeError(
            "Live order execution is not connected yet. "
            "Set CBR_DRY_RUN=1."
        )
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format=(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ),
    )
    logger = logging.getLogger("cbr_trading")

    logger.info(
        "CBR title-only detector starting mode=%s interval=%s "
        "release_date=%s suffix=%s cache_bust=%s dry_run=%s telegram=%s",
        settings.mode,
        settings.poll_interval,
        settings.release_date,
        settings.release_time_suffix,
        settings.cache_bust,
        settings.dry_run,
        settings.telegram_enabled,
    )

    client = CbrClient(
        RequestsTransport(),
        settings.client_config(),
    )
    poller = CbrPoller(client, settings, logger=logger)

    try:
        if settings.mode == "live_once":
            result = poller.run_once()
        else:
            result = poller.run_until_published()
    except KeyboardInterrupt:
        logger.info("CBR detector stopped by user")
        return 130

    output = asdict(result)
    if result.ok:
        telegram = (
            TelegramNotifier(
                bot_token=settings.telegram_bot_token or "",
                chat_id=settings.telegram_chat_id or "",
                timeout=settings.telegram_timeout,
            )
            if settings.telegram_enabled
            else None
        )

        def notify_after_orders(outcome: PipelineOutcome) -> None:
            if telegram is None:
                return
            try:
                sent = telegram.notify_pipeline(
                    outcome,
                    dry_run=settings.dry_run,
                )
                logger.info(
                    "CBR Telegram notification sent after order processing "
                    "message_id=%s",
                    sent.message_id,
                )
            except TelegramError as exc:
                logger.error(
                    "CBR Telegram notification failed after order "
                    "processing: %s",
                    exc,
                )

        pipeline = TradingPipeline(
            executor=DryRunOrderExecutor(),
            notifier=notify_after_orders,
        )
        outcome = pipeline.process(
            release=result,
            previous_rate=settings.previous_rate,
            subscriptions=(),
        )
        output = asdict(outcome)
        logger.info(
            "CBR dry-run pipeline completed change_bps=%s rules=%s "
            "orders=%s execution_error=%s",
            outcome.change_bps,
            len(outcome.evaluations),
            len(outcome.order_results),
            outcome.execution_error,
        )

    print(json.dumps(output, ensure_ascii=False))
    return 0
