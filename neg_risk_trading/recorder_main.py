from __future__ import annotations

import asyncio
import logging
import sys

from cbr_trading.secret_guard import redact_exception
from neg_risk_trading.recorder import ContinuousShadowRecorder
from neg_risk_trading.settings import NegRiskRecorderSettings


def main() -> int:
    try:
        settings = NegRiskRecorderSettings.from_env()
    except Exception as exc:
        print(
            "Neg-risk recorder configuration failed: "
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
    logger = logging.getLogger("neg_risk_trading.recorder")
    logger.info(
        "Neg-risk shadow recorder starting "
        "event=%s quantities=%s database_target=%s "
        "live_orders_enabled=false",
        settings.event_slug,
        len(settings.quantities),
        settings.database_target,
    )
    try:
        asyncio.run(
            ContinuousShadowRecorder(
                settings=settings,
                logger=logger,
            ).run()
        )
    except KeyboardInterrupt:
        logger.info("Neg-risk shadow recorder stopped")
        return 0
    except Exception as exc:
        logger.error(
            "Neg-risk shadow recorder failed: %s",
            redact_exception(exc),
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
