from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from cbr_trading.application import (
    CoordinationStatus,
    CoordinatorState,
    ResolutionTradingCoordinator,
)
from cbr_trading.domain import RepriceOnTickChange, ResolutionSignal
from cbr_trading.execution import (
    DryRunPreparedExecutor,
    PersistentOrderSupervisor,
    PolymarketPreflightPreparedExecutor,
    PolymarketPreparedExecutor,
    PreparationContext,
    PreparedExecutor,
    SupervisedPreparedExecutor,
)
from cbr_trading.fed import (
    FedDecisionSpec,
    FedMarketBinding,
    FedOfficialDocumentPoller,
    fed_july_2026_decision_spec,
    fed_july_2026_market_bindings,
)
from cbr_trading.live import (
    OrderSupervisionRuntime,
    SqlAlchemyOrderGroupRepository,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.notifications import (
    SqlAlchemyNotificationOutboxStore,
    source_event_notification_from_fed,
)
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    SqlAlchemyResolutionProfileStore,
    order_templates_from_profile,
)
from cbr_trading.resolution_hosted.batch_safety import (
    validate_profile_batch_notional,
)
from cbr_trading.resolution_hosted.earnings import (
    HostedPollResult,
    HostedPreparation,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources import (
    FED_RATE_CHANGE_METRIC,
    FED_SOURCE_NAME,
    FedResolutionSource,
    fed_signal_subject,
    resolution_signal_from_fed_observation,
)
from cbr_trading.strategies import (
    NUMERIC_THRESHOLD_STRATEGY_ID,
    NumericThresholdRule,
    NumericThresholdStrategy,
)


ExecutorFactory = Callable[
    [ResolutionExecutionProfile],
    PreparedExecutor,
]


@dataclass
class _ManagedFedResolution:
    profile: ResolutionExecutionProfile
    binding: FedMarketBinding
    coordinator: ResolutionTradingCoordinator
    executor: PreparedExecutor


class FedHostedResolutionWorker:
    """Poll one FOMC decision and fan its signal out to five markets."""

    def __init__(
        self,
        *,
        settings: HostedResolutionSettings,
        profile_store: SqlAlchemyResolutionProfileStore,
        lifecycle_store: Any | None = None,
        notification_outbox: (
            SqlAlchemyNotificationOutboxStore | None
        ) = None,
        db_session_factory: Callable[[], Any] | None = None,
        spec: FedDecisionSpec | None = None,
        bindings: Sequence[FedMarketBinding] | None = None,
        poller: FedOfficialDocumentPoller | None = None,
        executor_factory: ExecutorFactory | None = None,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._profile_store = profile_store
        self._lifecycle_store = lifecycle_store
        self._notification_outbox = notification_outbox
        self._db_session_factory = db_session_factory
        self._spec = spec or fed_july_2026_decision_spec()
        self._bindings = tuple(
            bindings
            if bindings is not None
            else fed_july_2026_market_bindings()
        )
        _validate_bindings(self._bindings)
        self._logger = logger or logging.getLogger(
            "cbr_trading.resolution_hosted.fed"
        )
        self._poller = poller or FedOfficialDocumentPoller(
            self._spec,
            logger=self._logger,
        )
        self._executor_factory = executor_factory
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._managed: list[_ManagedFedResolution] = []
        self._signal: ResolutionSignal | None = None
        self._notified = False
        self._supervision_runtime: (
            OrderSupervisionRuntime | None
        ) = None
        self._supervisor: PersistentOrderSupervisor | None = None
        self._closed = False
        self._poll_count = 0
        self._schemas_ready = False

    @property
    def managed_count(self) -> int:
        return len(self._managed)

    def prepare(self) -> tuple[HostedPreparation, ...]:
        if self._closed:
            raise RuntimeError("hosted FED resolution worker is closed")
        if self._managed:
            raise RuntimeError(
                "hosted FED resolution worker is already prepared"
            )
        return self.reconcile_profiles()

    def reconcile_profiles(self) -> tuple[HostedPreparation, ...]:
        if self._closed:
            raise RuntimeError("hosted FED resolution worker is closed")
        self._ensure_ready()
        profiles = tuple(
            self._profile_store.load_enabled(
                source_name=FED_SOURCE_NAME,
            )
        )
        bindings_by_scope = {
            binding.scope_id: binding
            for binding in self._bindings
        }
        enabled_keys = {profile.profile_key for profile in profiles}
        retained: list[_ManagedFedResolution] = []
        for managed in self._managed:
            if managed.profile.profile_key in enabled_keys:
                retained.append(managed)
                continue
            _expire_executor(
                managed.executor,
                reason="profile_disabled_or_out_of_window",
            )
            managed.coordinator.close()
            self._logger.info(
                "Hosted FED resolution detached profile=%s scope=%s",
                managed.profile.profile_key,
                managed.profile.scope_id,
            )
        self._managed = retained
        managed_keys = {
            managed.profile.profile_key for managed in self._managed
        }
        new_profiles = tuple(
            profile
            for profile in profiles
            if profile.profile_key not in managed_keys
        )
        if not new_profiles:
            return ()
        needs_supervision = (
            self._settings.mode is HostedResolutionMode.LIVE
            and any(
                isinstance(
                    profile.lifecycle_policy,
                    RepriceOnTickChange,
                )
                for profile in new_profiles
            )
        )
        if needs_supervision and not self._settings.supervision_enabled:
            raise ValueError(
                "live reprice profiles require "
                "RESOLUTION_SUPERVISION_ENABLED"
            )
        if self._settings.mode is not HostedResolutionMode.SHADOW:
            validate_profile_batch_notional(
                tuple(self._profile_store.load_enabled()),
                mode=self._settings.mode,
                safety=LiveSafetySettings.from_env(),
            )
        if needs_supervision:
            self._start_supervision()

        results: list[HostedPreparation] = []
        failures: list[str] = []
        newly_managed: list[_ManagedFedResolution] = []
        for profile in new_profiles:
            try:
                binding = _validated_profile_binding(
                    profile,
                    bindings_by_scope=bindings_by_scope,
                )
                managed, preparation = self._prepare_one(
                    profile=profile,
                    binding=binding,
                )
                if not preparation.ready:
                    error = (
                        preparation.error
                        or "executor_preparation_not_ready"
                    )
                    failures.append(f"{profile.profile_key}: {error}")
                    self._logger.error(
                        "Hosted FED preparation failed "
                        "profile=%s scope=%s error=%s",
                        profile.profile_key,
                        profile.scope_id,
                        error,
                    )
                    results.append(
                        HostedPreparation(
                            profile_key=profile.profile_key,
                            scope_id=profile.scope_id,
                            ticker="FED",
                            ready=False,
                            template_count=len(preparation.templates),
                            error=error,
                        )
                    )
                    _expire_executor(
                        managed.executor,
                        reason="preparation_failed",
                    )
                    managed.coordinator.close()
                    self._block_failed_profile(profile.profile_key)
                    continue
                newly_managed.append(managed)
                results.append(
                    HostedPreparation(
                        profile_key=profile.profile_key,
                        scope_id=profile.scope_id,
                        ticker="FED",
                        ready=True,
                        template_count=len(preparation.templates),
                    )
                )
            except Exception as exc:
                error = redact_exception(exc)
                failures.append(f"{profile.profile_key}: {error}")
                self._logger.error(
                    "Hosted FED preparation failed "
                    "profile=%s scope=%s error=%s",
                    profile.profile_key,
                    profile.scope_id,
                    error,
                )
                results.append(
                    HostedPreparation(
                        profile_key=profile.profile_key,
                        scope_id=profile.scope_id,
                        ticker="FED",
                        ready=False,
                        template_count=0,
                        error=error,
                    )
                )
                self._block_failed_profile(profile.profile_key)
        if failures:
            if self._lifecycle_store is not None:
                self._managed.extend(newly_managed)
                return tuple(results)
            for managed in newly_managed:
                _expire_executor(
                    managed.executor,
                    reason="preparation_batch_failed",
                )
                managed.coordinator.close()
            self.close()
            raise RuntimeError(
                "Hosted FED preparation failed: "
                + "; ".join(failures)
            )
        self._managed.extend(newly_managed)
        return tuple(results)

    def poll_once(self) -> HostedPollResult:
        if self._closed:
            raise RuntimeError("hosted FED resolution worker is closed")
        if not self._managed:
            return HostedPollResult(
                fact_count=0,
                waiting_count=0,
                completed_count=0,
                failed_count=0,
                expired_count=0,
            )
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("hosted FED clock must be timezone-aware")
        now = now.astimezone(timezone.utc)
        ready_profiles = tuple(
            managed
            for managed in self._managed
            if managed.coordinator.state is CoordinatorState.READY
            and now < managed.profile.expires_at
        )
        if ready_profiles and self._signal is None:
            observation = self._poller.poll_once()
            if observation is not None:
                self._signal = resolution_signal_from_fed_observation(
                    observation,
                    spec=self._spec,
                )

        waiting = 0
        completed = 0
        failed = 0
        expired = 0
        for managed in self._managed:
            state = managed.coordinator.state
            if state is CoordinatorState.READY:
                if now >= managed.profile.expires_at:
                    _expire_executor(
                        managed.executor,
                        reason="preparation_window_expired",
                    )
                    managed.coordinator.close()
                    expired += 1
                    continue
                outcome = managed.coordinator.poll_once()
                if outcome.status in {
                    CoordinationStatus.WAITING,
                    CoordinationStatus.IGNORED,
                }:
                    waiting += 1
                elif outcome.status is CoordinationStatus.COMPLETED:
                    completed += 1
                    self._logger.info(
                        "Hosted FED resolution completed scope=%s "
                        "bucket=%s mode=%s intents=%s results=%s",
                        managed.profile.scope_id,
                        managed.binding.bucket.value,
                        self._settings.mode.value,
                        len(outcome.intents),
                        len(outcome.order_results),
                    )
                else:
                    failed += 1
                    self._logger.error(
                        "Hosted FED resolution failed scope=%s "
                        "status=%s error=%s",
                        managed.profile.scope_id,
                        outcome.status.value,
                        outcome.error,
                    )
            elif state is CoordinatorState.COMPLETED:
                completed += 1
            elif state is CoordinatorState.FAILED:
                failed += 1
            elif state is CoordinatorState.CLOSED:
                expired += 1
        if self._signal is not None and not self._notified:
            self._enqueue_notification_after_execution()
        self._poll_count += 1
        return HostedPollResult(
            fact_count=1 if self._signal is not None else 0,
            waiting_count=waiting,
            completed_count=completed,
            failed_count=failed,
            expired_count=expired,
        )

    async def run_forever(self) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        next_refresh = 0.0
        next_empty_log = 0.0
        try:
            while not self._closed:
                monotonic_now = time.monotonic()
                if monotonic_now >= next_refresh:
                    try:
                        preparations = await asyncio.to_thread(
                            self.reconcile_profiles
                        )
                    except Exception:
                        self._expire_all(
                            reason="profile_reconciliation_failed"
                        )
                        raise
                    if preparations:
                        self._logger.info(
                            "Hosted FED resolution attached mode=%s "
                            "profiles=%s templates=%s",
                            self._settings.mode.value,
                            len(preparations),
                            sum(
                                item.template_count
                                for item in preparations
                            ),
                        )
                    elif (
                        not self._managed
                        and monotonic_now >= next_empty_log
                    ):
                        self._logger.warning(
                            "Hosted FED resolution has no enabled "
                            "in-window profiles"
                        )
                        next_empty_log = (
                            monotonic_now
                            + self._settings.no_profiles_retry_delay
                        )
                    next_refresh = (
                        monotonic_now
                        + self._settings.profile_refresh_interval
                    )
                await asyncio.to_thread(self.poll_once)
                await asyncio.sleep(self._settings.poll_interval)
        finally:
            heartbeat.cancel()
            await asyncio.gather(
                heartbeat,
                return_exceptions=True,
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        for managed in self._managed:
            try:
                managed.coordinator.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        self._managed.clear()
        if self._supervision_runtime is not None:
            try:
                self._supervision_runtime.stop()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
            self._supervision_runtime = None
            self._supervisor = None
        try:
            self._poller.close()
        except Exception as exc:
            if first_error is None:
                first_error = exc
        if first_error is not None:
            raise RuntimeError(redact_exception(first_error)) from None

    def _prepare_one(
        self,
        *,
        profile: ResolutionExecutionProfile,
        binding: FedMarketBinding,
    ) -> tuple[_ManagedFedResolution, Any]:
        source = FedResolutionSource(
            lambda: self._signal,
            scope_id=profile.scope_id,
        )
        yes_template, no_template = order_templates_from_profile(
            profile,
            strategy_id=NUMERIC_THRESHOLD_STRATEGY_ID,
            metadata={
                "rule_key": binding.rule_key,
                "ticker": "FED",
                "market_slug": binding.market_slug,
                "decision_id": self._spec.decision_id,
                "rate_bucket": binding.bucket.value,
            },
        )
        strategy = NumericThresholdStrategy(
            (
                NumericThresholdRule(
                    rule_key=binding.rule_key,
                    source=FED_SOURCE_NAME,
                    subject=fed_signal_subject(self._spec),
                    metric=FED_RATE_CHANGE_METRIC,
                    comparison_op=binding.comparison_op,
                    strike=binding.strike_bps,
                    rounding_places=0,
                    yes_template=yes_template,
                    no_template=no_template,
                ),
            )
        )
        executor = self._new_executor(profile)
        coordinator = ResolutionTradingCoordinator(
            source=source,
            strategies=(strategy,),
            executor=executor,
            context=PreparationContext(
                scope_id=profile.scope_id,
                source=profile.source_name,
                source_reference=profile.source_reference,
                attributes={
                    "profile_key": profile.profile_key,
                    "ticker": "FED",
                    "rule_key": binding.rule_key,
                    "decision_id": self._spec.decision_id,
                    "rate_bucket": binding.bucket.value,
                },
            ),
        )
        preparation = coordinator.prepare()
        return (
            _ManagedFedResolution(
                profile=profile,
                binding=binding,
                coordinator=coordinator,
                executor=executor,
            ),
            preparation,
        )

    def _new_executor(
        self,
        profile: ResolutionExecutionProfile,
    ) -> PreparedExecutor:
        if self._executor_factory is not None:
            return self._executor_factory(profile)
        if self._settings.mode is HostedResolutionMode.SHADOW:
            return DryRunPreparedExecutor()
        safety = LiveSafetySettings.from_env()
        if self._settings.mode is HostedResolutionMode.PREFLIGHT:
            return PolymarketPreflightPreparedExecutor(
                database_url=self._settings.database_url or "",
                safety=safety,
                db_session_factory=self._db_session_factory,
            )
        delegate: PreparedExecutor = PolymarketPreparedExecutor(
            database_url=self._settings.database_url or "",
            safety=safety,
            db_session_factory=self._db_session_factory,
        )
        if isinstance(
            profile.lifecycle_policy,
            RepriceOnTickChange,
        ):
            if self._supervisor is None:
                raise RuntimeError("order supervisor is unavailable")
            return SupervisedPreparedExecutor(
                delegate,
                supervisor=self._supervisor,
                on_registered=getattr(
                    self._supervision_runtime,
                    "notify_watch_set_changed",
                    None,
                ),
            )
        return delegate

    def _start_supervision(self) -> None:
        if self._supervision_runtime is not None:
            return
        safety = LiveSafetySettings.from_env()
        repository = SqlAlchemyOrderGroupRepository(
            database_url=self._settings.database_url,
            session_factory=self._db_session_factory,
        )
        gateway = PolymarketSupervisionOrderGateway(
            database_url=self._settings.database_url or "",
            safety=safety,
            db_session_factory=self._db_session_factory,
        )
        supervisor = PersistentOrderSupervisor(
            repository=repository,
            gateway=gateway,
            reconciliation_stale_after=timedelta(
                seconds=self._settings.supervision_stale_after
            ),
            reconciliation_batch_size=(
                self._settings.supervision_batch_size
            ),
        )
        runtime = OrderSupervisionRuntime(
            repository=repository,
            supervisor=supervisor,
            watch_refresh_interval=(
                self._settings.supervision_watch_refresh_interval
            ),
            reconciliation_interval=(
                self._settings.supervision_reconciliation_interval
            ),
            logger=self._logger,
        )
        try:
            runtime.ensure_ready()
            runtime.start()
        except Exception:
            runtime.stop()
            raise
        self._supervisor = supervisor
        self._supervision_runtime = runtime

    def _ensure_ready(self) -> None:
        if self._schemas_ready:
            return
        self._profile_store.ensure_ready()
        if self._lifecycle_store is not None:
            self._lifecycle_store.ensure_ready()
        if self._notification_outbox is not None:
            self._notification_outbox.ensure_ready()
        self._schemas_ready = True

    def _expire_all(self, *, reason: str) -> None:
        for managed in self._managed:
            try:
                _expire_executor(managed.executor, reason=reason)
            finally:
                managed.coordinator.close()

    def _block_failed_profile(self, profile_key: str) -> None:
        if self._lifecycle_store is None:
            return
        self._lifecycle_store.block_active_profile(
            profile_key=profile_key,
            reason_code="live_profile_preparation_failed",
        )

    def _enqueue_notification_after_execution(self) -> None:
        if self._notification_outbox is None or self._signal is None:
            self._notified = True
            return
        try:
            notification = source_event_notification_from_fed(
                signal=self._signal,
                bindings=self._bindings,
            )
            self._notification_outbox.enqueue(notification)
        except Exception as exc:
            self._logger.error(
                "FED notification enqueue failed error_type=%s",
                type(exc).__name__,
            )
            return
        self._notified = True

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._settings.heartbeat_interval)
            states: dict[str, int] = defaultdict(int)
            for managed in self._managed:
                states[managed.coordinator.state.value] += 1
            self._logger.info(
                "Hosted FED heartbeat mode=%s profiles=%s polls=%s "
                "signal=%s states=%s",
                self._settings.mode.value,
                len(self._managed),
                self._poll_count,
                self._signal is not None,
                dict(states),
            )


def _validate_bindings(
    bindings: Sequence[FedMarketBinding],
) -> None:
    if not bindings:
        raise ValueError("at least one FED market binding is required")
    scopes = [binding.scope_id for binding in bindings]
    keys = [binding.rule_key for binding in bindings]
    buckets = [binding.bucket for binding in bindings]
    if len(scopes) != len(set(scopes)):
        raise ValueError("FED binding scopes must be unique")
    if len(keys) != len(set(keys)):
        raise ValueError("FED binding rule keys must be unique")
    if len(buckets) != len(set(buckets)):
        raise ValueError("FED binding buckets must be unique")


def _validated_profile_binding(
    profile: ResolutionExecutionProfile,
    *,
    bindings_by_scope: dict[str, FedMarketBinding],
) -> FedMarketBinding:
    binding = bindings_by_scope.get(profile.scope_id)
    if binding is None:
        raise ValueError(
            "execution profile has no checked-in FED market binding"
        )
    if profile.source_name.casefold() != FED_SOURCE_NAME.casefold():
        raise ValueError("execution profile source does not match FED")
    if profile.condition_id.casefold() != binding.condition_id.casefold():
        raise ValueError(
            "execution profile condition_id does not match FED market"
        )
    if (
        profile.source_reference.rstrip("/").casefold()
        != binding.source_reference.rstrip("/").casefold()
    ):
        raise ValueError(
            "execution profile source_reference does not match FED market"
        )
    return binding


def _expire_executor(
    executor: PreparedExecutor,
    *,
    reason: str,
) -> None:
    expire = getattr(executor, "expire_pending", None)
    if callable(expire):
        expire(reason=reason)
