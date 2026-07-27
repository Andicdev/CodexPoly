from __future__ import annotations

import asyncio
import logging
import os
import sys

from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.orchestration import (
    SqlAlchemyResolutionProfileStore,
)
from cbr_trading.profile_lifecycle.readiness import (
    ProfileReadinessWorker,
)
from cbr_trading.profile_lifecycle.repository import (
    SqlAlchemyProfileLifecycleStore,
)
from cbr_trading.profile_lifecycle.settings import (
    ProfileReadinessSettings,
)
from cbr_trading.secret_guard import redact_exception


def main() -> int:
    _load_dotenv_if_available()
    try:
        settings = ProfileReadinessSettings.from_env(os.environ)
        safety = LiveSafetySettings.from_env(os.environ)
    except Exception as exc:
        print(redact_exception(exc), file=sys.stderr)
        return 3
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(
        "cbr_trading.profile_lifecycle.readiness"
    )
    store = SqlAlchemyProfileLifecycleStore(
        database_url=settings.database_url
    )
    profile_store = SqlAlchemyResolutionProfileStore(
        database_url=settings.database_url
    )
    worker = ProfileReadinessWorker(
        settings=settings,
        store=store,
        profile_store=profile_store,
        safety=safety,
        logger=logger,
    )
    try:
        asyncio.run(worker.run_forever())
    except KeyboardInterrupt:
        logger.info("Profile readiness worker stopped")
        return 130
    except Exception as exc:
        logger.error(
            "Profile readiness worker stopped error=%s",
            redact_exception(RuntimeError(type(exc).__name__)),
        )
        return 5
    finally:
        profile_store.close()
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
