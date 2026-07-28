from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from cbr_trading.db_runtime import SharedSqlAlchemyRuntime
from cbr_trading.earnings import SqlAlchemyEarningsStore
from cbr_trading.mstr_btc import SqlAlchemyMstrBtcAuditStore
from cbr_trading.notifications import (
    SqlAlchemyNotificationOutboxStore,
)
from cbr_trading.orchestration import (
    SqlAlchemyResolutionProfileStore,
)
from cbr_trading.profile_lifecycle import (
    SqlAlchemyProfileLifecycleStore,
)
from cbr_trading.resolution_hosted.earnings import (
    EarningsHostedResolutionWorker,
)
from cbr_trading.resolution_hosted.fed import (
    FedHostedResolutionWorker,
)
from cbr_trading.resolution_hosted.mstr_btc import (
    MstrBtcHostedResolutionWorker,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.runtime_secrets import runtime_secret_present
from cbr_trading.run_journal import (
    SqlAlchemyResolutionRunJournalStore,
)
from cbr_trading.resolution_hosted.runtime_repository import (
    SqlAlchemyResolutionRuntimeStore,
)
from cbr_trading.secret_guard import redact_exception


def main() -> int:
    _load_dotenv_if_available()
    try:
        settings = HostedResolutionSettings.from_env(os.environ)
        trading_enabled = _bool_setting(
            os.environ.get("CBR_LIVE_TRADING_ENABLED"),
            default=False,
        )
        _validate_live_runtime_configuration(
            settings=settings,
            trading_enabled=trading_enabled,
            environ=os.environ,
        )
    except Exception as exc:
        print(redact_exception(exc), file=sys.stderr)
        return 3
    logging.basicConfig(
        level=getattr(
            logging,
            settings.log_level,
            logging.INFO,
        ),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("cbr_trading.resolution_hosted")
    try:
        database_runtime = SharedSqlAlchemyRuntime(
            database_url=settings.database_url or "",
            application_name="codexpoly-resolution",
            pool_size=3,
            max_overflow=2,
        )
    except Exception as exc:
        logger.error(
            "Hosted resolution database runtime failed error=%s",
            redact_exception(RuntimeError(type(exc).__name__)),
        )
        return 3
    session_factory = database_runtime.session_factory
    earnings_store = SqlAlchemyEarningsStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    earnings_profile_store = SqlAlchemyResolutionProfileStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    mstr_audit_store = SqlAlchemyMstrBtcAuditStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    mstr_profile_store = SqlAlchemyResolutionProfileStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    fed_profile_store = SqlAlchemyResolutionProfileStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    notification_outbox = SqlAlchemyNotificationOutboxStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    runtime_store = SqlAlchemyResolutionRuntimeStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    lifecycle_store = SqlAlchemyProfileLifecycleStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    run_journal_store = SqlAlchemyResolutionRunJournalStore(
        database_url=settings.database_url,
        session_factory=session_factory,
    )
    earnings_worker = EarningsHostedResolutionWorker(
        settings=settings,
        earnings_store=earnings_store,
        profile_store=earnings_profile_store,
        lifecycle_store=lifecycle_store,
        run_journal_store=run_journal_store,
        db_session_factory=session_factory,
        logger=logging.getLogger(
            "cbr_trading.resolution_hosted.earnings"
        ),
    )
    mstr_worker = MstrBtcHostedResolutionWorker(
        settings=settings,
        audit_store=mstr_audit_store,
        profile_store=mstr_profile_store,
        lifecycle_store=lifecycle_store,
        db_session_factory=session_factory,
        logger=logging.getLogger(
            "cbr_trading.resolution_hosted.mstr_btc"
        ),
    )
    fed_worker = FedHostedResolutionWorker(
        settings=settings,
        profile_store=fed_profile_store,
        lifecycle_store=lifecycle_store,
        notification_outbox=notification_outbox,
        db_session_factory=session_factory,
        logger=logging.getLogger(
            "cbr_trading.resolution_hosted.fed"
        ),
    )
    try:
        asyncio.run(
            _run_workers(
                earnings_worker,
                mstr_worker,
                fed_worker,
                runtime_store=runtime_store,
                settings=settings,
                trading_enabled=trading_enabled,
            )
        )
    except KeyboardInterrupt:
        logger.info("Hosted resolution worker stopped")
        return 130
    except Exception as exc:
        logger.error(
            "Hosted resolution worker stopped error=%s",
            redact_exception(
                RuntimeError(type(exc).__name__)
            ),
        )
        return 5
    finally:
        try:
            earnings_worker.close()
        finally:
            try:
                runtime_store.close()
            finally:
                try:
                    lifecycle_store.close()
                finally:
                    try:
                        run_journal_store.close()
                    finally:
                        try:
                            mstr_worker.close()
                        finally:
                            try:
                                fed_worker.close()
                            finally:
                                notification_outbox.close()
                                fed_profile_store.close()
                                mstr_profile_store.close()
                                mstr_audit_store.close()
                                earnings_profile_store.close()
                                earnings_store.close()
                                database_runtime.close()
    return 0


async def _run_workers(
    *workers: object,
    runtime_store: SqlAlchemyResolutionRuntimeStore,
    settings: HostedResolutionSettings,
    trading_enabled: bool,
) -> None:
    await asyncio.to_thread(runtime_store.ensure_ready)
    process_started_at = datetime.now(timezone.utc)
    await asyncio.gather(
        *(worker.run_forever() for worker in workers),
        _runtime_heartbeat_loop(
            runtime_store=runtime_store,
            settings=settings,
            trading_enabled=trading_enabled,
            process_started_at=process_started_at,
        ),
    )


async def _runtime_heartbeat_loop(
    *,
    runtime_store: SqlAlchemyResolutionRuntimeStore,
    settings: HostedResolutionSettings,
    trading_enabled: bool,
    process_started_at: datetime,
) -> None:
    while True:
        await asyncio.to_thread(
            runtime_store.heartbeat,
            runtime_key="hosted-resolution",
            mode=settings.mode,
            supervision_enabled=settings.supervision_enabled,
            trading_enabled=trading_enabled,
            process_started_at=process_started_at,
            seen_at=datetime.now(timezone.utc),
            metadata={"profile_refresh": "dynamic"},
        )
        await asyncio.sleep(settings.runtime_heartbeat_interval)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _bool_setting(value: str | None, *, default: bool) -> bool:
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError("Invalid live trading boolean setting")


def _validate_live_runtime_configuration(
    *,
    settings: HostedResolutionSettings,
    trading_enabled: bool,
    environ: Mapping[str, str],
) -> None:
    if settings.mode is not HostedResolutionMode.LIVE:
        return
    required_positive_decimals = (
        "CBR_LIVE_MAX_ORDER_QTY",
        "CBR_LIVE_MAX_NOTIONAL",
        "CBR_LIVE_MAX_TOTAL_NOTIONAL",
    )
    decimal_settings_ready = True
    for key in required_positive_decimals:
        try:
            value = Decimal(str(environ.get(key) or "").strip())
        except InvalidOperation:
            decimal_settings_ready = False
            break
        if not value.is_finite() or value <= 0:
            decimal_settings_ready = False
            break
    ready = (
        trading_enabled
        and settings.supervision_enabled
        and decimal_settings_ready
        and bool(str(environ.get("CBR_LIVE_ALLOWED_ACCOUNT") or "").strip())
        and bool(str(environ.get("TRADING_ACCOUNT_NAME") or "").strip())
        and runtime_secret_present(
            "ACCOUNTS_MASTER_KEY",
            environ=environ,
        )
        and runtime_secret_present(
            "TRADING_ACCOUNT_PRIVATE_KEY_ENCRYPTED",
            environ=environ,
        )
    )
    if not ready:
        raise ValueError(
            "Live resolution runtime configuration is incomplete"
        )


if __name__ == "__main__":
    raise SystemExit(main())
