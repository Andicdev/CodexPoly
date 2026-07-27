from __future__ import annotations

import asyncio
import logging
import os
import sys

from cbr_trading.notifications.hosted_worker import (
    NotificationHostedWorker,
    build_telegram_sender,
)
from cbr_trading.notifications.repository import (
    SqlAlchemyNotificationOutboxStore,
)
from cbr_trading.notifications.settings import NotificationWorkerSettings
from cbr_trading.secret_guard import redact_exception


def main() -> int:
    _load_dotenv_if_available()
    try:
        settings = NotificationWorkerSettings.from_env(os.environ)
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
    logger = logging.getLogger("cbr_trading.notifications")
    store = SqlAlchemyNotificationOutboxStore(
        database_url=settings.database_url
    )
    worker = NotificationHostedWorker(
        settings=settings,
        store=store,
        sender=build_telegram_sender(settings),
        logger=logger,
    )
    try:
        asyncio.run(worker.run_forever())
    except KeyboardInterrupt:
        logger.info("Notification worker stopped")
        return 130
    except Exception as exc:
        logger.error(
            "Notification worker stopped error=%s",
            redact_exception(RuntimeError(type(exc).__name__)),
        )
        return 5
    finally:
        store.close()
    return 0


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    raise SystemExit(main())
