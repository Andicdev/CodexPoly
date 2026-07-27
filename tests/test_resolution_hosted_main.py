from __future__ import annotations

import asyncio
import unittest
from datetime import datetime

from cbr_trading.resolution_hosted.__main__ import _run_workers
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
    HostedResolutionSettings,
)


class _Worker:
    def __init__(self, started: asyncio.Event) -> None:
        self.runs = 0
        self._started = started

    async def run_forever(self) -> None:
        self.runs += 1
        await self._started.wait()


class _RuntimeStore:
    def __init__(self, started: asyncio.Event) -> None:
        self.ready_checks = 0
        self.heartbeats: list[dict] = []
        self._started = started

    def ensure_ready(self) -> None:
        self.ready_checks += 1

    def heartbeat(self, **kwargs) -> None:
        self.heartbeats.append(kwargs)
        self._started.set()


class HostedResolutionMainTests(unittest.TestCase):
    def test_runs_all_source_specific_workers(self) -> None:
        async def exercise() -> tuple[_Worker, _Worker, _RuntimeStore]:
            started = asyncio.Event()
            earnings = _Worker(started)
            mstr = _Worker(started)
            runtime = _RuntimeStore(started)
            task = asyncio.create_task(
                _run_workers(
                    earnings,
                    mstr,
                    runtime_store=runtime,
                    settings=HostedResolutionSettings(
                        mode=HostedResolutionMode.LIVE,
                        database_url="postgresql://unused",
                        supervision_enabled=True,
                        runtime_heartbeat_interval=0.01,
                    ),
                    trading_enabled=True,
                )
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return earnings, mstr, runtime

        earnings, mstr, runtime = asyncio.run(exercise())

        self.assertEqual(earnings.runs, 1)
        self.assertEqual(mstr.runs, 1)
        self.assertEqual(runtime.ready_checks, 1)
        self.assertEqual(len(runtime.heartbeats), 1)
        heartbeat = runtime.heartbeats[0]
        self.assertEqual(heartbeat["mode"], HostedResolutionMode.LIVE)
        self.assertTrue(heartbeat["supervision_enabled"])
        self.assertTrue(heartbeat["trading_enabled"])
        self.assertIsInstance(
            heartbeat["process_started_at"],
            datetime,
        )


if __name__ == "__main__":
    unittest.main()
