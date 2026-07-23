from __future__ import annotations

import json
import logging
from dataclasses import asdict

from cbr_trading.client import CbrClient, RequestsTransport
from cbr_trading.live.runner_executor import (
    LivePreparationError,
    UnavailableLiveOrderExecutor,
    WarmLiveOrderExecutor,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.pipeline import (
    DryRunOrderExecutor,
    OrderExecutor,
    PipelineOutcome,
    TradingPipeline,
)
from cbr_trading.poller import CbrPoller
from cbr_trading.rule_repository import (
    RuleLoadError,
    SqlAlchemyRuleRepository,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)
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
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format=(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ),
    )
    logger = logging.getLogger("cbr_trading")

    logger.info(
        "CBR title-only detector starting mode=%s interval=%s "
        "release_date=%s suffix=%s cache_bust=%s dry_run=%s "
        "rules_db=%s primary_db=%s/%s analytics_db=%s/%s "
        "telegram=%s",
        settings.mode,
        settings.poll_interval,
        settings.release_date,
        settings.release_time_suffix,
        settings.cache_bust,
        settings.dry_run,
        settings.rules_db_enabled,
        settings.primary_database_target,
        settings.primary_database_source,
        settings.analytics_database_target,
        settings.analytics_database_source,
        settings.telegram_enabled,
    )

    subscriptions: tuple[dict, ...] = ()
    rules_load_error: str | None = None
    if settings.rules_db_enabled:
        if not settings.rules_database_url:
            rules_load_error = (
                settings.primary_database_error
                or "Primary database URL is not configured"
            )
            logger.error(
                "CBR rule preload failed; monitoring continues with "
                "trading skipped: %s",
                rules_load_error,
            )
        else:
            repository = SqlAlchemyRuleRepository(
                database_url=settings.rules_database_url,
            )
            try:
                subscriptions = tuple(
                    repository.load_active_cbr_rules()
                )
            except RuleLoadError as exc:
                rules_load_error = redact_sensitive_text(exc)
                logger.error(
                    "CBR rule preload failed; monitoring continues with "
                    "trading skipped: %s",
                    rules_load_error,
                )
            finally:
                repository.close()
        if rules_load_error is None:
            logger.info(
                "CBR rules preloaded read-only count=%s",
                len(subscriptions),
            )
        if not subscriptions and rules_load_error is None:
            logger.warning(
                "CBR rule preload returned no active fast-path rules; "
                "monitoring continues with trading skipped"
            )

    executor: OrderExecutor
    if settings.dry_run:
        executor = DryRunOrderExecutor()
    elif rules_load_error:
        executor = UnavailableLiveOrderExecutor(rules_load_error)
    elif not subscriptions:
        executor = UnavailableLiveOrderExecutor(
            "no active CBR rules"
        )
    elif not settings.rules_database_url:
        executor = UnavailableLiveOrderExecutor(
            "primary database URL is not configured"
        )
    else:
        live_executor: WarmLiveOrderExecutor | None = None
        try:
            live_executor = WarmLiveOrderExecutor(
                subscriptions=subscriptions,
                database_url=settings.rules_database_url,
                safety=LiveSafetySettings.from_env(),
            )
            summary = live_executor.prepare()
        except Exception as exc:
            if live_executor is not None:
                live_executor.close()
            safe_error = _safe_exception(exc)
            executor = UnavailableLiveOrderExecutor(safe_error)
            logger.error(
                "CBR live executor preparation failed; monitoring "
                "continues with trading skipped: %s",
                safe_error,
            )
        else:
            executor = live_executor
            logger.info(
                "CBR live executor warmed before polling rules=%s "
                "accounts=%s outcomes=%s maximum_notional=%s",
                summary.rule_count,
                summary.account_count,
                summary.outcome_count,
                summary.maximum_notional,
            )

    client = CbrClient(
        RequestsTransport(),
        settings.client_config(),
    )
    poller = CbrPoller(client, settings, logger=logger)

    try:
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
                        "CBR Telegram notification sent after order "
                        "processing message_id=%s",
                        sent.message_id,
                    )
                except TelegramError as exc:
                    logger.error(
                        "CBR Telegram notification failed after order "
                        "processing: %s",
                        exc,
                    )

            pipeline = TradingPipeline(
                executor=executor,
                notifier=notify_after_orders,
            )
            outcome = pipeline.process(
                release=result,
                previous_rate=settings.previous_rate,
                subscriptions=subscriptions,
                rules_load_error=rules_load_error,
            )
            output = asdict(outcome)
            logger.info(
                "CBR %s pipeline completed change_bps=%s rules=%s "
                "orders=%s execution_error=%s",
                "dry-run" if settings.dry_run else "live",
                outcome.change_bps,
                len(outcome.evaluations),
                len(outcome.order_results),
                outcome.execution_error,
            )

        print(json.dumps(output, ensure_ascii=False))
        return 0
    finally:
        close = getattr(executor, "close", None)
        if callable(close):
            close()


def _safe_exception(exc: Exception) -> str:
    detail = redact_sensitive_text(exc)
    if isinstance(exc, LivePreparationError) and detail:
        return detail
    return redact_exception(exc)
