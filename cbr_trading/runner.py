from __future__ import annotations

import json
import logging
from dataclasses import asdict

from cbr_trading.application import (
    CbrPollModeDiscoveryClient,
    CoordinationPreparation,
    ResolutionTradingCoordinator,
    pipeline_outcome_from_coordination,
)
from cbr_trading.client import CbrClient, RequestsTransport
from cbr_trading.execution import (
    CbrWarmPreparedExecutorAdapter,
    DryRunPreparedExecutor,
    PreparedExecutor,
    UnavailablePreparedExecutor,
    cbr_preparation_context,
)
from cbr_trading.live.runner_executor import (
    LivePreparationError,
    WarmLiveOrderExecutor,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.poller import CbrPoller
from cbr_trading.release import build_predicted_release_url
from cbr_trading.rule_repository import (
    RuleLoadError,
    SqlAlchemyRuleRepository,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)
from cbr_trading.settings import CbrSettings
from cbr_trading.sources import CbrResolutionSource
from cbr_trading.strategies import CbrRateDecisionStrategy
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

    strategy_error: str | None = None
    try:
        strategy = CbrRateDecisionStrategy(subscriptions)
    except Exception as exc:
        strategy_error = _safe_exception(exc)
        strategy = CbrRateDecisionStrategy(())
        logger.error(
            "CBR strategy preparation failed; monitoring continues "
            "with trading skipped: %s",
            strategy_error,
        )

    release_url = build_predicted_release_url(
        release_date=settings.release_date,
        release_time_suffix=settings.release_time_suffix,
    )
    context = cbr_preparation_context(release_url)
    client = CbrClient(
        RequestsTransport(),
        settings.client_config(),
    )
    poller = CbrPoller(client, settings, logger=logger)
    source = CbrResolutionSource(
        CbrPollModeDiscoveryClient(
            poller,
            wait_until_published=settings.mode != "live_once",
        ),
        previous_rate_provider=lambda: settings.previous_rate,
    )

    live_adapter: CbrWarmPreparedExecutorAdapter | None = None
    executor: PreparedExecutor
    if settings.dry_run:
        executor = DryRunPreparedExecutor()
    elif strategy_error:
        executor = UnavailablePreparedExecutor(strategy_error)
    elif rules_load_error:
        executor = UnavailablePreparedExecutor(rules_load_error)
    elif not subscriptions:
        executor = UnavailablePreparedExecutor(
            "no active CBR rules"
        )
    elif not settings.rules_database_url:
        executor = UnavailablePreparedExecutor(
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
            live_adapter = CbrWarmPreparedExecutorAdapter(live_executor)
            executor = live_adapter
        except Exception as exc:
            if live_executor is not None:
                live_executor.close()
            construction_error = _safe_exception(exc)
            executor = UnavailablePreparedExecutor(
                construction_error
            )
            logger.error(
                "CBR live executor preparation failed; monitoring "
                "continues with trading skipped: %s",
                construction_error,
            )

    allow_monitor_only = not strategy.order_templates()
    coordinator = ResolutionTradingCoordinator(
        source=source,
        strategies=(strategy,),
        executor=executor,
        context=context,
        allow_monitor_only=allow_monitor_only,
    )
    preparation = coordinator.prepare()
    if not preparation.ready:
        preparation_error = _preparation_error(preparation)
        coordinator.close()
        executor = UnavailablePreparedExecutor(preparation_error)
        coordinator = ResolutionTradingCoordinator(
            source=source,
            strategies=(strategy,),
            executor=executor,
            context=context,
            allow_monitor_only=allow_monitor_only,
        )
        fallback_preparation = coordinator.prepare()
        if not fallback_preparation.ready:
            raise RuntimeError(
                "CBR unavailable executor could not be prepared"
            )
        logger.error(
            "CBR live executor preparation failed; monitoring "
            "continues with trading skipped: %s",
            preparation_error,
        )
    elif live_adapter is not None:
        summary = live_adapter.legacy_preparation_summary
        if summary is not None:
            logger.info(
                "CBR live executor warmed before polling rules=%s "
                "accounts=%s outcomes=%s maximum_notional=%s",
                summary.rule_count,
                summary.account_count,
                summary.outcome_count,
                summary.maximum_notional,
            )

    try:
        try:
            coordination = coordinator.poll_once()
        except KeyboardInterrupt:
            logger.info("CBR detector stopped by user")
            return 130

        result = source.last_discovery
        if result is None:
            output = {
                "ok": False,
                "reason": "source_error",
                "error": coordination.error,
            }
        else:
            output = asdict(result)

        if (
            result is not None
            and result.ok
            and coordination.signal is not None
        ):
            telegram = (
                TelegramNotifier(
                    bot_token=settings.telegram_bot_token or "",
                    chat_id=settings.telegram_chat_id or "",
                    timeout=settings.telegram_timeout,
                )
                if settings.telegram_enabled
                else None
            )

            outcome = pipeline_outcome_from_coordination(
                coordination,
                release=result,
                previous_rate=settings.previous_rate,
                strategy=strategy,
                rules_load_error=(
                    rules_load_error or strategy_error
                ),
            )
            if telegram is not None:
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
        coordinator.close()


def _safe_exception(exc: Exception) -> str:
    detail = redact_sensitive_text(exc)
    if isinstance(exc, LivePreparationError) and detail:
        return detail
    return redact_exception(exc)


def _preparation_error(
    preparation: CoordinationPreparation,
) -> str:
    for item in preparation.summary.items:
        if item.error:
            return redact_sensitive_text(item.error)
    return redact_sensitive_text(
        preparation.error or "executor preparation failed"
    )
