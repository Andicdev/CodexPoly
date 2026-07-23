from __future__ import annotations

import logging
import unittest

from cbr_trading.client import DiscoveryResult
from cbr_trading.poller import CbrPoller
from cbr_trading.settings import CbrSettings


def _result(
    *,
    ok: bool,
    reason: str,
    rate: float | None = None,
    status_code: int | None = None,
) -> DiscoveryResult:
    return DiscoveryResult(
        ok=ok,
        reason=reason,
        url="https://cbr.ru/expected",
        request_url="https://cbr.ru/expected?_ts=1",
        status_code=status_code,
        title=(
            f"Bank of Russia cuts the key rate to {rate}%"
            if rate is not None
            else "Press release | Bank of Russia"
        ),
        new_rate=rate,
        error="Timeout: temporary" if reason == "fetch_failed" else None,
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class SequenceClient:
    def __init__(
        self,
        clock: FakeClock,
        results: list[DiscoveryResult],
        *,
        request_duration: float = 0.1,
    ):
        self.clock = clock
        self.results = list(results)
        self.request_duration = request_duration
        self.starts: list[float] = []
        self.release_dates: list[str | None] = []

    def discover_predicted_release(
        self,
        *,
        release_date: str | None = None,
    ) -> DiscoveryResult:
        self.starts.append(self.clock.now)
        self.release_dates.append(release_date)
        self.clock.now += self.request_duration
        return self.results.pop(0)


class SettingsTests(unittest.TestCase):
    def test_defaults_are_hot_and_title_only(self) -> None:
        settings = CbrSettings.from_env({})
        self.assertEqual(settings.mode, "hot")
        self.assertEqual(settings.poll_interval, 0.25)
        self.assertTrue(settings.cache_bust)
        self.assertFalse(
            hasattr(settings.client_config(), "full_body_fallback")
        )

    def test_reads_legacy_bor_environment(self) -> None:
        settings = CbrSettings.from_env(
            {
                "BOR_MODE": "live_once",
                "BOR_RELEASE_DATE": '"24.07.2026"',
                "BOR_POLL_SLEEP_SEC": "0.1",
                "BOR_DISABLE_CACHE_BUSTER": "true",
                "BOR_PREFIX_MAX_BYTES": "4096",
                "BOR_PREFIX_CHUNK_SIZE": "1024",
            }
        )
        self.assertEqual(settings.mode, "live_once")
        self.assertEqual(settings.release_date, "24.07.2026")
        self.assertEqual(settings.poll_interval, 0.1)
        self.assertFalse(settings.cache_bust)
        self.assertEqual(settings.prefix_max_bytes, 4096)

    def test_rejects_old_replay_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "BOR_MODE"):
            CbrSettings.from_env({"BOR_MODE": "replay_url"})


class PollingTests(unittest.TestCase):
    def test_heartbeat_includes_http_status(self) -> None:
        clock = FakeClock()
        client = SequenceClient(
            clock,
            [
                _result(
                    ok=False,
                    reason="not_published_yet",
                    status_code=200,
                )
            ],
        )
        settings = CbrSettings(heartbeat_interval=0)
        logger = logging.getLogger("test.poller.status")
        poller = CbrPoller(
            client,
            settings,
            logger=logger,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

        with self.assertLogs(logger, level="INFO") as captured:
            poller.run_until_published(max_iterations=1)

        self.assertIn("status=200", "\n".join(captured.output))

    def test_fetch_failure_includes_403_status(self) -> None:
        clock = FakeClock()
        client = SequenceClient(
            clock,
            [
                _result(
                    ok=False,
                    reason="fetch_failed",
                    status_code=403,
                )
            ],
        )
        logger = logging.getLogger("test.poller.403")
        poller = CbrPoller(
            client,
            CbrSettings(),
            logger=logger,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

        with self.assertLogs(logger, level="WARNING") as captured:
            poller.run_until_published(max_iterations=1)

        self.assertIn("status=403", "\n".join(captured.output))

    def test_uses_fixed_start_to_start_interval(self) -> None:
        clock = FakeClock()
        client = SequenceClient(
            clock,
            [
                _result(ok=False, reason="not_published_yet"),
                _result(ok=False, reason="fetch_failed"),
                _result(ok=True, reason="published", rate=14.25),
            ],
            request_duration=0.1,
        )
        settings = CbrSettings(
            release_date="24.07.2026",
            poll_interval=0.25,
            heartbeat_interval=10,
        )
        poller = CbrPoller(
            client,
            settings,
            logger=logging.getLogger("test.poller"),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

        result = poller.run_until_published()

        self.assertTrue(result.ok)
        self.assertEqual(result.new_rate, 14.25)
        self.assertEqual(client.starts, [0.0, 0.25, 0.5])
        self.assertEqual(
            client.release_dates,
            ["24.07.2026", "24.07.2026", "24.07.2026"],
        )
        self.assertEqual(len(clock.sleeps), 2)

    def test_slow_request_is_not_followed_by_extra_sleep(self) -> None:
        clock = FakeClock()
        client = SequenceClient(
            clock,
            [
                _result(ok=False, reason="not_published_yet"),
                _result(ok=True, reason="published", rate=14.25),
            ],
            request_duration=0.4,
        )
        settings = CbrSettings(
            poll_interval=0.25,
            heartbeat_interval=10,
        )
        poller = CbrPoller(
            client,
            settings,
            logger=logging.getLogger("test.poller"),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

        result = poller.run_until_published()

        self.assertTrue(result.ok)
        self.assertEqual(client.starts, [0.0, 0.4])
        self.assertEqual(clock.sleeps, [])

    def test_max_iterations_makes_offline_checks_bounded(self) -> None:
        clock = FakeClock()
        client = SequenceClient(
            clock,
            [
                _result(ok=False, reason="not_published_yet"),
                _result(ok=False, reason="not_published_yet"),
            ],
            request_duration=0.01,
        )
        settings = CbrSettings(
            poll_interval=0.25,
            heartbeat_interval=10,
        )
        poller = CbrPoller(
            client,
            settings,
            logger=logging.getLogger("test.poller"),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

        result = poller.run_until_published(max_iterations=2)

        self.assertFalse(result.ok)
        self.assertEqual(len(client.starts), 2)


if __name__ == "__main__":
    unittest.main()
