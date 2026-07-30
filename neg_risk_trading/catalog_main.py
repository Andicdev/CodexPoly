from __future__ import annotations

import logging
import sys

from cbr_trading.secret_guard import redact_exception
from neg_risk_trading.catalog_service import (
    ContinuousCatalogScanner,
)
from neg_risk_trading.settings import NegRiskCatalogSettings


def main() -> int:
    try:
        settings = NegRiskCatalogSettings.from_env()
    except Exception as exc:
        print(
            "Neg-risk catalog configuration failed: "
            f"{redact_exception(exc)}",
            file=sys.stderr,
        )
        return 2
    logging.basicConfig(
        level=getattr(
            logging,
            settings.log_level,
            logging.INFO,
        ),
        format=(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ),
    )
    logger = logging.getLogger("neg_risk_trading.catalog")
    logger.info(
        "Neg-risk catalog scanner starting "
        "poll_seconds=%.3f page_size=%s "
        "database_target=%s live_orders_enabled=false",
        settings.poll_interval_seconds,
        settings.page_size,
        settings.database_target,
    )
    try:
        ContinuousCatalogScanner(
            settings=settings,
            logger=logger,
        ).run_forever()
    except KeyboardInterrupt:
        logger.info("Neg-risk catalog scanner stopped")
        return 0
    except Exception as exc:
        logger.error(
            "Neg-risk catalog scanner failed: %s",
            redact_exception(exc),
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
