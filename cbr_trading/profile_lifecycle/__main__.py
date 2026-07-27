from __future__ import annotations

import asyncio
import logging
import os
import sys

from cbr_trading.notifications import (
    SqlAlchemyNotificationOutboxStore,
)
from cbr_trading.profile_lifecycle.controller import (
    ProfileLifecycleController,
)
from cbr_trading.profile_lifecycle.repository import (
    SqlAlchemyProfileLifecycleStore,
)
from cbr_trading.profile_lifecycle.settings import (
    ProfileLifecycleSettings,
)
from cbr_trading.secret_guard import redact_exception


def main() -> int:
    _load_dotenv_if_available()
    try:
        settings = ProfileLifecycleSettings.from_env(os.environ)
    except Exception as exc:
        print(redact_exception(exc), file=sys.stderr)
        return 3
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("cbr_trading.profile_lifecycle")
    store = SqlAlchemyProfileLifecycleStore(
        database_url=settings.database_url
    )
    outbox = SqlAlchemyNotificationOutboxStore(
        database_url=settings.database_url
    )
    controller = ProfileLifecycleController(
        settings=settings,
        store=store,
        notification_outbox=outbox,
        logger=logger,
    )
    try:
        asyncio.run(controller.run_forever())
    except KeyboardInterrupt:
        logger.info("Profile lifecycle worker stopped")
        return 130
    except Exception as exc:
        logger.error(
            "Profile lifecycle worker stopped error=%s",
            redact_exception(RuntimeError(type(exc).__name__)),
        )
        return 5
    finally:
        outbox.close()
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
