from __future__ import annotations

import asyncio
import unittest

from cbr_trading.resolution_hosted.__main__ import _run_workers


class _Worker:
    def __init__(self) -> None:
        self.runs = 0

    async def run_forever(self) -> None:
        await asyncio.sleep(0)
        self.runs += 1


class HostedResolutionMainTests(unittest.TestCase):
    def test_runs_all_source_specific_workers(self) -> None:
        earnings = _Worker()
        mstr = _Worker()

        asyncio.run(_run_workers(earnings, mstr))

        self.assertEqual(earnings.runs, 1)
        self.assertEqual(mstr.runs, 1)


if __name__ == "__main__":
    unittest.main()
