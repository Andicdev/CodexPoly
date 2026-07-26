from __future__ import annotations

import asyncio
import logging
import os
import sys

from cbr_trading.earnings import SqlAlchemyEarningsStore
from cbr_trading.mstr_btc import SqlAlchemyMstrBtcAuditStore
from cbr_trading.orchestration import (
    SqlAlchemyResolutionProfileStore,
)
from cbr_trading.resolution_hosted.earnings import (
    EarningsHostedResolutionWorker,
)
from cbr_trading.resolution_hosted.mstr_btc import (
    MstrBtcHostedResolutionWorker,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionSettings,
)
from cbr_trading.secret_guard import redact_exception


def main() -> int:
    _load_dotenv_if_available()
    try:
        settings = HostedResolutionSettings.from_env(os.environ)
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
    earnings_store = SqlAlchemyEarningsStore(
        database_url=settings.database_url
    )
    earnings_profile_store = SqlAlchemyResolutionProfileStore(
        database_url=settings.database_url
    )
    mstr_audit_store = SqlAlchemyMstrBtcAuditStore(
        database_url=settings.database_url
    )
    mstr_profile_store = SqlAlchemyResolutionProfileStore(
        database_url=settings.database_url
    )
    earnings_worker = EarningsHostedResolutionWorker(
        settings=settings,
        earnings_store=earnings_store,
        profile_store=earnings_profile_store,
        logger=logging.getLogger(
            "cbr_trading.resolution_hosted.earnings"
        ),
    )
    mstr_worker = MstrBtcHostedResolutionWorker(
        settings=settings,
        audit_store=mstr_audit_store,
        profile_store=mstr_profile_store,
        logger=logging.getLogger(
            "cbr_trading.resolution_hosted.mstr_btc"
        ),
    )
    try:
        asyncio.run(
            _run_workers(
                earnings_worker,
                mstr_worker,
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
                mstr_worker.close()
            finally:
                mstr_profile_store.close()
                mstr_audit_store.close()
                earnings_profile_store.close()
                earnings_store.close()
    return 0


async def _run_workers(*workers: object) -> None:
    await asyncio.gather(
        *(worker.run_forever() for worker in workers)
    )


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    raise SystemExit(main())
