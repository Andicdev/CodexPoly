from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from cbr_trading.notifications import (
    SourceEventNotification,
    source_event_notification_from_profile_lifecycle,
)
from cbr_trading.profile_lifecycle.contracts import (
    ProfileScheduleTransition,
)
from cbr_trading.profile_lifecycle.settings import (
    ProfileLifecycleSettings,
)


class LifecycleStore(Protocol):
    def ensure_ready(self) -> None: ...

    def expire_due(
        self,
        *,
        now: datetime,
    ) -> ProfileScheduleTransition | None: ...

    def block_due_unready(
        self,
        *,
        now: datetime,
        grace_seconds: float,
    ) -> ProfileScheduleTransition | None: ...

    def request_due_preflight(
        self,
        *,
        now: datetime,
    ) -> ProfileScheduleTransition | None: ...

    def activate_due_ready(
        self,
        *,
        now: datetime,
        max_total_notional,
        live_heartbeat_stale_seconds: float,
        activation_grace_seconds: float,
    ) -> ProfileScheduleTransition | None: ...

    def load_unnotified_event(
        self,
    ) -> ProfileScheduleTransition | None: ...

    def mark_event_notified(self, event_id: int) -> None: ...


class NotificationOutbox(Protocol):
    def ensure_ready(self) -> None: ...

    def enqueue(
        self,
        notification: SourceEventNotification,
        *,
        delivery_delay_seconds: float = 0,
    ): ...


@dataclass(frozen=True)
class ProfileLifecycleRunResult:
    expired: int = 0
    blocked: int = 0
    preflight_requested: int = 0
    activated: int = 0
    notifications_enqueued: int = 0


class ProfileLifecycleController:
    """Move scheduled profiles through fail-closed database states."""

    def __init__(
        self,
        *,
        settings: ProfileLifecycleSettings,
        store: LifecycleStore,
        notification_outbox: NotificationOutbox,
        clock=None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._store = store
        self._notification_outbox = notification_outbox
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._logger = logger or logging.getLogger(
            "cbr_trading.profile_lifecycle"
        )
        self._runs = 0
        self._totals = ProfileLifecycleRunResult()

    def run_once(self) -> ProfileLifecycleRunResult:
        now = self._clock()
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError(
                "profile lifecycle clock must be timezone-aware"
            )
        now = now.astimezone(timezone.utc)
        expired = self._drain(
            lambda: self._store.expire_due(now=now)
        )
        blocked = self._drain(
            lambda: self._store.block_due_unready(
                now=now,
                grace_seconds=(
                    self._settings.activation_grace_seconds
                ),
            )
        )
        requested = self._drain(
            lambda: self._store.request_due_preflight(now=now)
        )
        activated = 0
        if self._settings.auto_live_enabled:
            activated = self._drain(
                lambda: self._store.activate_due_ready(
                    now=now,
                    max_total_notional=(
                        self._settings.max_total_notional
                    ),
                    live_heartbeat_stale_seconds=(
                        self._settings.live_heartbeat_stale_seconds
                    ),
                    activation_grace_seconds=(
                        self._settings.activation_grace_seconds
                    ),
                )
            )
        notifications = self._drain_notifications()
        result = ProfileLifecycleRunResult(
            expired=expired,
            blocked=blocked,
            preflight_requested=requested,
            activated=activated,
            notifications_enqueued=notifications,
        )
        self._runs += 1
        self._totals = ProfileLifecycleRunResult(
            expired=self._totals.expired + expired,
            blocked=self._totals.blocked + blocked,
            preflight_requested=(
                self._totals.preflight_requested + requested
            ),
            activated=self._totals.activated + activated,
            notifications_enqueued=(
                self._totals.notifications_enqueued
                + notifications
            ),
        )
        return result

    async def run_forever(self) -> None:
        await asyncio.to_thread(self._store.ensure_ready)
        await asyncio.to_thread(
            self._notification_outbox.ensure_ready
        )
        self._logger.info(
            "Profile lifecycle ready auto_live=%s",
            self._settings.auto_live_enabled,
        )
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            while True:
                result = await asyncio.to_thread(self.run_once)
                if any(result.__dict__.values()):
                    self._logger.info(
                        "Profile lifecycle transitions "
                        "requested=%s activated=%s blocked=%s "
                        "expired=%s notifications=%s",
                        result.preflight_requested,
                        result.activated,
                        result.blocked,
                        result.expired,
                        result.notifications_enqueued,
                    )
                await asyncio.sleep(self._settings.poll_interval)
        finally:
            heartbeat.cancel()
            await asyncio.gather(
                heartbeat,
                return_exceptions=True,
            )

    def _drain(self, operation) -> int:
        count = 0
        while count < self._settings.batch_size:
            transition = operation()
            if transition is None:
                break
            count += 1
        return count

    def _drain_notifications(self) -> int:
        count = 0
        while count < self._settings.batch_size:
            transition = self._store.load_unnotified_event()
            if transition is None:
                break
            notification = (
                source_event_notification_from_profile_lifecycle(
                    transition
                )
            )
            self._notification_outbox.enqueue(notification)
            self._store.mark_event_notified(transition.event_id)
            count += 1
        return count

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._settings.heartbeat_interval)
            self._logger.info(
                "Profile lifecycle heartbeat runs=%s "
                "requested=%s activated=%s blocked=%s expired=%s "
                "notifications=%s auto_live=%s",
                self._runs,
                self._totals.preflight_requested,
                self._totals.activated,
                self._totals.blocked,
                self._totals.expired,
                self._totals.notifications_enqueued,
                self._settings.auto_live_enabled,
            )
