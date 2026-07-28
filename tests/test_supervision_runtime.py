from __future__ import annotations

import asyncio
import threading
import time
import unittest
from decimal import Decimal

from cbr_trading.execution import TickSizeWatch
from cbr_trading.live.supervision_runtime import (
    OrderSupervisionRuntime,
    OrderSupervisionRuntimeError,
)


def _watch(asset_id: str) -> TickSizeWatch:
    return TickSizeWatch(
        asset_id=asset_id,
        old_tick=Decimal("0.01"),
        new_tick=Decimal("0.001"),
    )


class _Repository:
    def __init__(self):
        self._lock = threading.Lock()
        self.watches: tuple[TickSizeWatch, ...] = ()
        self.pending = False
        self.ready_calls = 0
        self.load_calls = 0
        self.pending_calls = 0
        self.ready_error: Exception | None = None

    def ensure_ready(self) -> None:
        self.ready_calls += 1
        if self.ready_error is not None:
            raise self.ready_error

    def load_active_tick_size_watches(
        self,
    ) -> tuple[TickSizeWatch, ...]:
        with self._lock:
            self.load_calls += 1
            return self.watches

    def has_pending_supervision_work(self) -> bool:
        with self._lock:
            self.pending_calls += 1
            return self.pending

    def update(
        self,
        *,
        watches: tuple[TickSizeWatch, ...],
        pending: bool,
    ) -> None:
        with self._lock:
            self.watches = watches
            self.pending = pending


class _Supervisor:
    def __init__(self):
        self.reconcile_calls = 0
        self.close_calls = 0

    def reconcile(self) -> tuple[()]:
        self.reconcile_calls += 1
        return ()

    def close(self) -> None:
        self.close_calls += 1


class _Channel:
    def __init__(self, watches: tuple[TickSizeWatch, ...]):
        self.watches = watches
        self.started = threading.Event()
        self.closed = threading.Event()
        self._stop = asyncio.Event()

    async def run(self) -> tuple[()]:
        self.started.set()
        await self._stop.wait()
        return ()

    async def close(self) -> None:
        self.closed.set()
        self._stop.set()


class _EndingChannel(_Channel):
    async def run(self) -> tuple[()]:
        self.started.set()
        return ()


class _ChannelFactory:
    def __init__(self):
        self.channels: list[_Channel] = []
        self.created = threading.Event()

    def __call__(
        self,
        watches: tuple[TickSizeWatch, ...],
    ) -> _Channel:
        channel = _Channel(tuple(watches))
        self.channels.append(channel)
        self.created.set()
        return channel


def _wait_for(predicate, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("condition was not reached")
        time.sleep(0.01)


class OrderSupervisionRuntimeTests(unittest.TestCase):
    def test_refreshes_channels_and_stops_after_work_is_idle(self) -> None:
        repository = _Repository()
        repository.update(
            watches=(_watch("asset-yes"),),
            pending=True,
        )
        supervisor = _Supervisor()
        factory = _ChannelFactory()
        runtime = OrderSupervisionRuntime(
            repository=repository,
            supervisor=supervisor,
            watch_refresh_interval=0.01,
            reconciliation_interval=0.02,
            channel_factory=factory,
        )

        runtime.start()
        _wait_for(lambda: len(factory.channels) == 1)
        self.assertTrue(factory.channels[0].started.wait(1))
        self.assertEqual(runtime.active_watch_count, 1)

        repository.update(
            watches=(_watch("asset-no"),),
            pending=True,
        )
        _wait_for(lambda: len(factory.channels) == 2)
        self.assertTrue(factory.channels[0].closed.wait(1))
        self.assertEqual(
            factory.channels[1].watches[0].asset_id,
            "asset-no",
        )

        repository.update(watches=(), pending=False)
        runtime.release_when_idle()
        runtime.wait(timeout=2)

        self.assertTrue(factory.channels[1].closed.is_set())
        self.assertEqual(runtime.active_watch_count, 0)
        self.assertGreaterEqual(supervisor.reconcile_calls, 1)
        self.assertEqual(supervisor.close_calls, 1)

    def test_startup_hold_keeps_empty_runtime_alive_until_release(self) -> None:
        repository = _Repository()
        supervisor = _Supervisor()
        runtime = OrderSupervisionRuntime(
            repository=repository,
            supervisor=supervisor,
            watch_refresh_interval=0.01,
            reconciliation_interval=0.02,
            channel_factory=_ChannelFactory(),
        )

        runtime.start()
        time.sleep(0.03)

        self.assertTrue(runtime.running)
        runtime.release_when_idle()
        runtime.wait(timeout=2)
        self.assertEqual(supervisor.close_calls, 1)

    def test_registration_notification_bypasses_long_refresh_interval(
        self,
    ) -> None:
        repository = _Repository()
        supervisor = _Supervisor()
        factory = _ChannelFactory()
        runtime = OrderSupervisionRuntime(
            repository=repository,
            supervisor=supervisor,
            watch_refresh_interval=30,
            reconciliation_interval=30,
            channel_factory=factory,
        )

        runtime.start()
        initial_load_calls = repository.load_calls
        repository.update(
            watches=(_watch("asset-yes"),),
            pending=True,
        )
        runtime.notify_watch_set_changed()

        _wait_for(lambda: len(factory.channels) == 1)
        self.assertTrue(factory.channels[0].started.wait(1))
        self.assertGreater(repository.load_calls, initial_load_calls)

        repository.update(watches=(), pending=False)
        runtime.release_when_idle()
        runtime.wait(timeout=2)

    def test_restarts_subscription_handle_that_ends(self) -> None:
        repository = _Repository()
        repository.update(
            watches=(_watch("asset-yes"),),
            pending=True,
        )
        supervisor = _Supervisor()
        channels: list[_Channel] = []

        def channel_factory(
            watches: tuple[TickSizeWatch, ...],
        ) -> _Channel:
            channel = (
                _EndingChannel(tuple(watches))
                if not channels
                else _Channel(tuple(watches))
            )
            channels.append(channel)
            return channel

        runtime = OrderSupervisionRuntime(
            repository=repository,
            supervisor=supervisor,
            watch_refresh_interval=0.01,
            reconciliation_interval=1,
            channel_factory=channel_factory,
        )

        runtime.start()
        _wait_for(lambda: len(channels) >= 2)

        self.assertTrue(channels[0].started.is_set())
        self.assertTrue(channels[1].started.wait(1))
        repository.update(watches=(), pending=False)
        runtime.release_when_idle()
        runtime.wait(timeout=2)

    def test_schema_readiness_failure_closes_supervisor(self) -> None:
        repository = _Repository()
        repository.ready_error = RuntimeError("schema missing")
        supervisor = _Supervisor()
        runtime = OrderSupervisionRuntime(
            repository=repository,
            supervisor=supervisor,
            channel_factory=_ChannelFactory(),
        )

        with self.assertRaisesRegex(
            OrderSupervisionRuntimeError,
            "schema missing",
        ):
            runtime.start()

        self.assertEqual(supervisor.close_calls, 1)

    def test_stop_before_start_closes_owned_supervisor(self) -> None:
        supervisor = _Supervisor()
        runtime = OrderSupervisionRuntime(
            repository=_Repository(),
            supervisor=supervisor,
            channel_factory=_ChannelFactory(),
        )

        runtime.stop()
        runtime.stop()

        self.assertEqual(supervisor.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
