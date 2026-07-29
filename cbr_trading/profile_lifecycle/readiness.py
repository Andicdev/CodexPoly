from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from cbr_trading.execution import (
    PolymarketPreflightPreparedExecutor,
    PreparationContext,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    order_templates_from_profile,
)
from cbr_trading.profile_lifecycle.contracts import (
    ProfilePreflightClaim,
)
from cbr_trading.profile_lifecycle.settings import (
    ProfileReadinessSettings,
)
from cbr_trading.secret_guard import redact_exception


class ReadinessStore(Protocol):
    def ensure_ready(self) -> None: ...

    def claim_preflight(
        self,
        *,
        now: datetime,
        lease_seconds: float,
    ) -> ProfilePreflightClaim | None: ...

    def complete_preflight(
        self,
        claim: ProfilePreflightClaim,
        *,
        checked_at: datetime,
        valid_until: datetime,
        evidence,
    ) -> None: ...

    def fail_preflight(
        self,
        claim: ProfilePreflightClaim,
        *,
        checked_at: datetime,
        error_code: str,
    ) -> None: ...

    def defer_preflight(
        self,
        claim: ProfilePreflightClaim,
        *,
        checked_at: datetime,
        retry_at: datetime,
        error_code: str,
    ) -> None: ...


class ProfileStore(Protocol):
    def ensure_ready(self) -> None: ...

    def load(
        self,
        profile_key: str,
    ) -> ResolutionExecutionProfile: ...


ExecutorFactory = Callable[
    [ResolutionExecutionProfile],
    Any,
]


class ProfileReadinessWorker:
    """Authenticate and pre-sign both outcomes without submitting orders."""

    def __init__(
        self,
        *,
        settings: ProfileReadinessSettings,
        store: ReadinessStore,
        profile_store: ProfileStore,
        safety: LiveSafetySettings,
        executor_factory: ExecutorFactory | None = None,
        clock=None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._store = store
        self._profile_store = profile_store
        self._safety = safety
        self._executor_factory = executor_factory
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._logger = logger or logging.getLogger(
            "cbr_trading.profile_lifecycle.readiness"
        )
        self._checked = 0
        self._ready = 0
        self._retried = 0
        self._blocked = 0

    def run_once(self) -> bool:
        now = self._now()
        claim = self._store.claim_preflight(
            now=now,
            lease_seconds=self._settings.lease_seconds,
        )
        if claim is None:
            return False
        self._checked += 1
        executor = None
        try:
            profile = self._profile_store.load(claim.profile_key)
            templates = order_templates_from_profile(
                profile,
                strategy_id="profile_readiness",
            )
            executor = self._new_executor(profile)
            summary = executor.prepare(
                templates,
                context=PreparationContext(
                    scope_id=profile.scope_id,
                    source=profile.source_name,
                    source_reference=profile.source_reference,
                    attributes={
                        "profile_key": profile.profile_key,
                        "schedule_key": claim.schedule_key,
                    },
                ),
            )
            if not summary.ready:
                raise _PreflightNotReady(
                    _summary_error_code(summary)
                )
            checked_at = self._now()
            valid_until = min(
                checked_at
                + timedelta(
                    seconds=self._settings.readiness_ttl_seconds
                ),
                claim.deactivate_at,
            )
            if valid_until <= checked_at:
                raise RuntimeError("preflight_window_expired")
            details = tuple(getattr(executor, "details", ()))
            self._store.complete_preflight(
                claim,
                checked_at=checked_at,
                valid_until=valid_until,
                evidence={
                    "template_count": len(templates),
                    "prepared_count": len(summary.items),
                    "all_presigned": (
                        bool(details)
                        and all(
                            bool(item.order_presigned)
                            for item in details
                        )
                    ),
                    "maximum_notional": str(
                        getattr(executor, "maximum_notional", "0")
                    ),
                },
            )
            self._ready += 1
            self._logger.info(
                "Profile authenticated preflight ready profile=%s "
                "schedule=%s templates=%s",
                claim.profile_key,
                claim.schedule_key,
                len(templates),
            )
        except Exception as exc:
            error_code = _safe_error_code(exc)
            checked_at = self._now()
            retry_at = min(
                checked_at
                + timedelta(
                    seconds=self._settings.retry_seconds
                ),
                claim.deactivate_at,
            )
            should_retry = (
                error_code != "preflight_window_expired"
                and retry_at > checked_at
            )
            try:
                if should_retry:
                    self._store.defer_preflight(
                        claim,
                        checked_at=checked_at,
                        retry_at=retry_at,
                        error_code=error_code,
                    )
                else:
                    self._store.fail_preflight(
                        claim,
                        checked_at=checked_at,
                        error_code=error_code,
                    )
            except Exception as persistence_exc:
                self._logger.error(
                    "Profile preflight failure could not be persisted "
                    "profile=%s error_code=%s",
                    claim.profile_key,
                    type(persistence_exc).__name__,
                )
                raise
            if should_retry:
                self._retried += 1
                self._logger.warning(
                    "Profile authenticated preflight deferred "
                    "profile=%s schedule=%s error_code=%s",
                    claim.profile_key,
                    claim.schedule_key,
                    error_code,
                )
            else:
                self._blocked += 1
                self._logger.warning(
                    "Profile authenticated preflight blocked "
                    "profile=%s schedule=%s error_code=%s",
                    claim.profile_key,
                    claim.schedule_key,
                    error_code,
                )
        finally:
            if executor is not None:
                try:
                    executor.close()
                except Exception:
                    self._logger.warning(
                        "Profile preflight executor close failed "
                        "profile=%s",
                        claim.profile_key,
                    )
        return True

    async def run_forever(self) -> None:
        await asyncio.to_thread(self._store.ensure_ready)
        await asyncio.to_thread(self._profile_store.ensure_ready)
        self._logger.info(
            "Profile readiness worker ready (non-submitting)"
        )
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            while True:
                processed = await asyncio.to_thread(self.run_once)
                if not processed:
                    await asyncio.sleep(self._settings.poll_interval)
        finally:
            heartbeat.cancel()
            await asyncio.gather(
                heartbeat,
                return_exceptions=True,
            )

    def _new_executor(
        self,
        profile: ResolutionExecutionProfile,
    ):
        if self._executor_factory is not None:
            return self._executor_factory(profile)
        return PolymarketPreflightPreparedExecutor(
            database_url=self._settings.database_url or "",
            safety=self._safety,
        )

    def _now(self) -> datetime:
        now = self._clock()
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise ValueError(
                "profile readiness clock must be timezone-aware"
            )
        return now.astimezone(timezone.utc)

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._settings.heartbeat_interval)
            self._logger.info(
                "Profile readiness heartbeat checked=%s ready=%s "
                "retried=%s blocked=%s",
                self._checked,
                self._ready,
                self._retried,
                self._blocked,
            )


class _PreflightNotReady(RuntimeError):
    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


def _summary_error_code(summary: Any) -> str:
    errors = " ".join(
        str(getattr(item, "error", "") or "").casefold()
        for item in tuple(getattr(summary, "items", ()))
    )
    if "insufficient collateral" in errors:
        return "preflight_insufficient_collateral"
    if any(
        marker in errors
        for marker in (
            "max_notional",
            "max_order",
            "aggregate notional",
            "account_not_allowed",
            "live safety",
        )
    ):
        return "preflight_safety_not_ready"
    if any(
        marker in errors
        for marker in (
            "wallet",
            "signature type",
            "decrypt",
            "authentication",
        )
    ):
        return "preflight_account_authentication_failed"
    if any(
        marker in errors
        for marker in (
            "order book",
            "condition",
            "tick size",
            "minimum order",
            "market snapshot",
        )
    ):
        return "preflight_market_not_ready"
    if any(
        marker in errors
        for marker in (
            "timeout",
            "connection",
            "unexpectedresponse",
            "rate limit",
            "httperror",
        )
    ):
        return "preflight_transport_unavailable"
    return "authenticated_preflight_not_ready"


def _safe_error_code(exc: Exception) -> str:
    explicit = str(getattr(exc, "error_code", "") or "").strip()
    if explicit:
        return explicit[:100]
    safe = redact_exception(exc).casefold()
    if "window_expired" in safe:
        return "preflight_window_expired"
    if "not_ready" in safe:
        return "authenticated_preflight_not_ready"
    return f"preflight_{type(exc).__name__.casefold()}"[:100]
