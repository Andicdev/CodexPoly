from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from cbr_trading.execution.order_group_repository import (
    OrderGroupRepository,
)
from cbr_trading.execution.order_supervisor import OrderSupervisor
from cbr_trading.execution.tick_size_detector import (
    TickSizeChangeDetector,
    TickSizeWatch,
)
from cbr_trading.live.market_channel import (
    PolymarketMarketChannel,
)
from cbr_trading.secret_guard import redact_exception


class OrderSupervisionRuntimeError(RuntimeError):
    """Sanitized lifecycle failure in the supervision background service."""


class _MarketChannel(Protocol):
    async def run(self) -> object: ...

    async def close(self) -> None: ...


class OrderSupervisionRuntime:
    """Refresh active watches and reconcile interrupted groups in background."""

    def __init__(
        self,
        *,
        repository: OrderGroupRepository,
        supervisor: OrderSupervisor,
        watch_refresh_interval: float = 2.0,
        reconciliation_interval: float = 30.0,
        channel_factory: Callable[
            [Sequence[TickSizeWatch]],
            _MarketChannel,
        ]
        | None = None,
        logger: logging.Logger | None = None,
    ):
        if watch_refresh_interval <= 0:
            raise ValueError("watch_refresh_interval must be positive")
        if reconciliation_interval <= 0:
            raise ValueError("reconciliation_interval must be positive")
        self._repository = repository
        self._supervisor = supervisor
        self._watch_refresh_interval = float(
            watch_refresh_interval
        )
        self._reconciliation_interval = float(
            reconciliation_interval
        )
        self._logger = logger or logging.getLogger(__name__)
        self._channel_factory = (
            channel_factory or self._default_channel_factory
        )
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()
        self._idle_release = threading.Event()
        self._started = threading.Event()
        self._state_lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._error: str | None = None
        self._active_watch_count = 0
        self._supervisor_closed = False

    @property
    def active_watch_count(self) -> int:
        with self._state_lock:
            return self._active_watch_count

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def ensure_ready(self) -> None:
        try:
            self._repository.ensure_ready()
        except Exception as exc:
            raise OrderSupervisionRuntimeError(
                redact_exception(exc)
            ) from None

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None:
                raise RuntimeError("supervision runtime already started")
            try:
                self.ensure_ready()
            except Exception:
                self._close_supervisor()
                raise
            thread = threading.Thread(
                target=self._thread_main,
                name="resolution-order-supervision",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        if not self._started.wait(timeout=5):
            self.stop()
            raise OrderSupervisionRuntimeError(
                "supervision runtime did not start"
            )
        self._raise_if_failed()

    def release_when_idle(self) -> None:
        self._idle_release.set()
        self._notify()

    def notify_watch_set_changed(self) -> None:
        """Wake the runtime after a durable order-group registration."""

        self._notify()

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is None:
            self._raise_if_failed()
            return
        deadline = (
            None
            if timeout is None
            else time.monotonic() + timeout
        )
        while thread.is_alive():
            remaining = (
                None
                if deadline is None
                else deadline - time.monotonic()
            )
            if remaining is not None and remaining <= 0:
                break
            thread.join(
                0.5
                if remaining is None
                else min(0.5, remaining)
            )
        if thread.is_alive():
            raise TimeoutError("supervision runtime is still running")
        self._raise_if_failed()

    def stop(self) -> None:
        self._stop_requested.set()
        self._notify()
        thread = self._thread
        if (
            thread is not None
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=10)
            if thread.is_alive():
                raise OrderSupervisionRuntimeError(
                    "supervision runtime did not stop"
                )
        elif thread is None:
            self._close_supervisor()
        self._raise_if_failed()

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            with self._state_lock:
                self._error = redact_exception(exc)
            self._logger.error(
                "order supervision runtime failed: %s",
                redact_exception(exc),
            )
        finally:
            self._started.set()
            self._close_supervisor()

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        with self._state_lock:
            self._loop = loop
            self._wake = wake
        self._started.set()

        channel: _MarketChannel | None = None
        channel_task: asyncio.Task[Any] | None = None
        current_watches: tuple[TickSizeWatch, ...] = ()
        next_reconciliation = 0.0
        try:
            while not self._stop_requested.is_set():
                # Clear before loading durable state. A registration wakeup
                # that arrives during the load then remains set and forces an
                # immediate second pass instead of being lost.
                wake.clear()
                now = loop.time()
                if now >= next_reconciliation:
                    await self._reconcile()
                    next_reconciliation = (
                        loop.time() + self._reconciliation_interval
                    )

                loaded_watches = await self._load_watches()
                desired_watches = (
                    current_watches
                    if loaded_watches is None
                    else loaded_watches
                )
                channel_ended = bool(
                    channel_task is not None
                    and channel_task.done()
                )
                if (
                    desired_watches != current_watches
                    or channel_ended
                ):
                    await self._stop_channel(
                        channel,
                        channel_task,
                        expected=(
                            self._stop_requested.is_set()
                            or desired_watches != current_watches
                        ),
                    )
                    channel = None
                    channel_task = None
                    current_watches = ()
                    self._set_active_watch_count(0)
                    if desired_watches:
                        try:
                            channel = self._channel_factory(
                                desired_watches
                            )
                            channel_task = asyncio.create_task(
                                channel.run()
                            )
                            current_watches = desired_watches
                            self._set_active_watch_count(
                                len(current_watches)
                            )
                            self._logger.info(
                                "market-channel watches active count=%s",
                                len(current_watches),
                            )
                        except Exception as exc:
                            self._logger.error(
                                "market-channel start failed: %s",
                                redact_exception(exc),
                            )

                if self._idle_release.is_set():
                    pending = await self._has_pending_work()
                    if pending is False:
                        break

                timeout = min(
                    self._watch_refresh_interval,
                    max(
                        0.01,
                        next_reconciliation - loop.time(),
                    ),
                )
                try:
                    await asyncio.wait_for(
                        wake.wait(),
                        timeout=timeout,
                    )
                except TimeoutError:
                    pass
        finally:
            await self._stop_channel(
                channel,
                channel_task,
                expected=True,
            )
            self._set_active_watch_count(0)
            with self._state_lock:
                self._wake = None
                self._loop = None

    async def _load_watches(
        self,
    ) -> tuple[TickSizeWatch, ...] | None:
        try:
            watches = tuple(
                await asyncio.to_thread(
                    self._repository.load_active_tick_size_watches
                )
            )
            return tuple(
                sorted(
                    watches,
                    key=lambda item: (
                        item.asset_id,
                        item.old_tick,
                        item.new_tick,
                    ),
                )
            )
        except Exception as exc:
            self._logger.error(
                "active tick-size watch refresh failed: %s",
                redact_exception(exc),
            )
            return None

    async def _has_pending_work(self) -> bool | None:
        try:
            return bool(
                await asyncio.to_thread(
                    self._repository.has_pending_supervision_work
                )
            )
        except Exception as exc:
            self._logger.error(
                "pending supervision check failed: %s",
                redact_exception(exc),
            )
            return None

    async def _reconcile(self) -> None:
        try:
            results = tuple(
                await asyncio.to_thread(
                    self._supervisor.reconcile
                )
            )
        except Exception as exc:
            self._logger.error(
                "order supervision recovery failed: %s",
                redact_exception(exc),
            )
            return
        if results:
            self._logger.info(
                "order supervision recovery processed count=%s",
                len(results),
            )
        for result in results:
            if result.error:
                self._logger.warning(
                    "order supervision terminal alert "
                    "group=%s status=%s reason=%s",
                    result.order_group_id,
                    result.status.value,
                    result.error,
                )

    async def _stop_channel(
        self,
        channel: _MarketChannel | None,
        task: asyncio.Task[Any] | None,
        *,
        expected: bool,
    ) -> None:
        if channel is not None:
            try:
                await channel.close()
            except Exception as exc:
                self._logger.warning(
                    "market-channel close failed: %s",
                    redact_exception(exc),
                )
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=10)
        except TimeoutError:
            task.cancel()
            with contextlib.suppress(
                asyncio.CancelledError,
                Exception,
            ):
                await task
            self._logger.error(
                "market-channel did not stop within 10 seconds"
            )
        except Exception as exc:
            if not expected:
                self._logger.error(
                    "market-channel stopped unexpectedly: %s",
                    redact_exception(exc),
                )

    def _default_channel_factory(
        self,
        watches: Sequence[TickSizeWatch],
    ) -> PolymarketMarketChannel:
        detector = TickSizeChangeDetector(tuple(watches))
        return PolymarketMarketChannel(
            detector=detector,
            supervisor=self._supervisor,
            logger=self._logger,
        )

    def _set_active_watch_count(self, value: int) -> None:
        with self._state_lock:
            self._active_watch_count = value

    def _notify(self) -> None:
        with self._state_lock:
            loop = self._loop
            wake = self._wake
        if (
            loop is not None
            and wake is not None
            and not loop.is_closed()
        ):
            loop.call_soon_threadsafe(wake.set)

    def _close_supervisor(self) -> None:
        with self._state_lock:
            if self._supervisor_closed:
                return
            self._supervisor_closed = True
        try:
            self._supervisor.close()
        except Exception as exc:
            with self._state_lock:
                if self._error is None:
                    self._error = redact_exception(exc)

    def _raise_if_failed(self) -> None:
        with self._state_lock:
            error = self._error
        if error:
            raise OrderSupervisionRuntimeError(error)
