from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from cbr_trading.client import DiscoveryResult
from cbr_trading.settings import CbrSettings


class DiscoveryClient(Protocol):
    def discover_predicted_release(
        self,
        *,
        release_date: str | None = None,
    ) -> DiscoveryResult: ...


class CbrPoller:
    def __init__(
        self,
        client: DiscoveryClient,
        settings: CbrSettings,
        *,
        logger: logging.Logger | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)
        self._monotonic = monotonic
        self._sleep = sleep

    def run_once(self) -> DiscoveryResult:
        return self.client.discover_predicted_release(
            release_date=self.settings.release_date,
        )

    def run_until_published(
        self,
        *,
        max_iterations: int | None = None,
    ) -> DiscoveryResult:
        """Poll on a fixed start-to-start cadence and return on publication."""
        iteration = 0
        next_start = self._monotonic()
        last_heartbeat = next_start
        last_result: DiscoveryResult | None = None

        while True:
            iteration += 1
            result = self.run_once()
            last_result = result
            now = self._monotonic()

            if result.ok:
                self.logger.info(
                    "CBR release detected iteration=%s rate=%s title=%s url=%s",
                    iteration,
                    result.new_rate,
                    result.title,
                    result.url,
                )
                return result

            if result.reason == "fetch_failed":
                self.logger.warning(
                    "CBR fetch failed iteration=%s status=%s "
                    "error=%s url=%s",
                    iteration,
                    result.status_code,
                    result.error,
                    result.url,
                )
            elif (
                self.settings.heartbeat_interval == 0
                or (now - last_heartbeat)
                >= self.settings.heartbeat_interval
            ):
                self.logger.info(
                    "CBR waiting iteration=%s status=%s reason=%s "
                    "title=%s url=%s",
                    iteration,
                    result.status_code,
                    result.reason,
                    result.title,
                    result.url,
                )
                last_heartbeat = now

            if (
                max_iterations is not None
                and iteration >= max_iterations
            ):
                return last_result

            next_start += self.settings.poll_interval
            delay = next_start - self._monotonic()
            if delay > 0:
                self._sleep(delay)
            else:
                next_start = self._monotonic()
