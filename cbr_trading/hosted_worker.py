from __future__ import annotations

import logging
import time
from collections.abc import Callable

from cbr_trading.runner import main as run_cbr


def main(
    *,
    runner: Callable[[], int] = run_cbr,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run one CBR event, then stay healthy as a hosted service."""
    exit_code = runner()
    if exit_code != 0:
        return exit_code

    logger = logging.getLogger("cbr_trading")
    logger.info(
        "CBR event processing finished; hosted worker is idle and "
        "will not restart the completed event"
    )
    try:
        while True:
            sleep(300)
            logger.info(
                "CBR hosted worker idle after completed event"
            )
    except KeyboardInterrupt:
        logger.info("CBR hosted worker stopped")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
