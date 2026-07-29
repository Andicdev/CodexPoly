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
from cbr_trading.resolution_hosted.lifecycle import (
    block_terminal_profile_failure,
    complete_profile_lifecycle,
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
    lifecycle_completed: bool = False
    lifecycle_failure_status: CoordinationStatus | None = None
    lifecycle_blocked: bool = False


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
        current_profiles = {
            managed.profile.profile_key: managed.profile
            for managed in self._managed
        }
        desired_profiles = {
            profile.profile_key: profile for profile in profiles
        }
        if current_profiles == desired_profiles:
            return ()

        if self._managed:
            self._detach_batch(
                reason="profile_disabled_or_out_of_window"
            )
        if not profiles:
            return ()

        needs_supervision = (
            self._settings.mode is HostedResolutionMode.LIVE
            and any(
                isinstance(
                    profile.lifecycle_policy,
                    RepriceOnTickChange,
                )
                for profile in profiles
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

        validated: list[
            tuple[ResolutionExecutionProfile, FedMarketBinding]
        ] = []
        result_by_key: dict[str, HostedPreparation] = {}
        failures: list[str] = []
        for profile in profiles:
            try:
                binding = _validated_profile_binding(
                    profile,
                    bindings_by_scope=bindings_by_scope,
                )
                validated.append((profile, binding))
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
                result_by_key[profile.profile_key] = HostedPreparation(
                    profile_key=profile.profile_key,
                    scope_id=profile.scope_id,
                    ticker="FED",
                    ready=False,
                    template_count=0,
                    error=error,
                )
                self._block_failed_profile(profile.profile_key)

        if failures and self._lifecycle_store is None:
            raise RuntimeError(
                "Hosted FED profile validation failed: "
                + "; ".join(failures)
            )
        if validated:
            managed_rows, preparation = self._prepare_batch(validated)
            if not preparation.ready:
                error = (
                    preparation.error
                    or "executor_preparation_not_ready"
                )
                for managed in managed_rows:
                    profile = managed.profile
                    failures.append(f"{profile.profile_key}: {error}")
                    result_by_key[
                        profile.profile_key
                    ] = HostedPreparation(
                        profile_key=profile.profile_key,
                        scope_id=profile.scope_id,
                        ticker="FED",
                        ready=False,
                        template_count=2,
                        error=error,
                    )
                    self._block_failed_profile(profile.profile_key)
                first = managed_rows[0]
                _expire_executor(
                    first.executor,
                    reason="preparation_failed",
                )
                first.coordinator.close()
                if self._lifecycle_store is None:
                    raise RuntimeError(
                        "Hosted FED batch preparation failed: "
                        + "; ".join(failures)
                    )
            else:
                self._managed.extend(managed_rows)
                for managed in managed_rows:
                    profile = managed.profile
                    result_by_key[
                        profile.profile_key
                    ] = HostedPreparation(
                        profile_key=profile.profile_key,
                        scope_id=profile.scope_id,
                        ticker="FED",
                        ready=True,
                        template_count=2,
                    )

        return tuple(
            result_by_key[profile.profile_key]
            for profile in profiles
        )

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
        first = self._managed[0]
        state = first.coordinator.state
        expired_profiles = tuple(
            managed
            for managed in self._managed
            if now >= managed.profile.expires_at
        )
        if expired_profiles and state is CoordinatorState.READY:
            expired = len(self._managed)
            self._detach_batch(reason="preparation_window_expired")
            self._poll_count += 1
            return HostedPollResult(
                fact_count=1 if self._signal is not None else 0,
                waiting_count=0,
                completed_count=0,
                failed_count=0,
                expired_count=expired,
            )

        if state is CoordinatorState.READY and self._signal is None:
            observation = self._poller.poll_once()
            if observation is not None:
                self._signal = resolution_signal_from_fed_observation(
                    observation,
                    spec=self._spec,
                )

        profile_count = len(self._managed)
        waiting = completed = failed = expired = 0
        if state is CoordinatorState.READY:
            outcome = first.coordinator.poll_once()
            if outcome.status in {
                CoordinationStatus.WAITING,
                CoordinationStatus.IGNORED,
            }:
                waiting = profile_count
            elif outcome.status is CoordinationStatus.COMPLETED:
                completed = profile_count
                for managed in self._managed:
                    self._complete_profile(managed)
                    profile_intents = tuple(
                        intent
                        for intent in outcome.intents
                        if str(
                            intent.metadata.get("profile_key") or ""
                        )
                        == managed.profile.profile_key
                    )
                    template_ids = {
                        intent.template_id for intent in profile_intents
                    }
                    profile_results = tuple(
                        result
                        for result in outcome.order_results
                        if result.intent.template_id in template_ids
                    )
                    self._logger.info(
                        "Hosted FED resolution completed scope=%s "
                        "bucket=%s mode=%s intents=%s results=%s",
                        managed.profile.scope_id,
                        managed.binding.bucket.value,
                        self._settings.mode.value,
                        len(profile_intents),
                        len(profile_results),
                    )
            else:
                failed = profile_count
                for managed in self._managed:
                    if (
                        managed.coordinator.state
                        is CoordinatorState.FAILED
                    ):
                        managed.lifecycle_failure_status = outcome.status
                        self._block_profile(managed)
                    self._logger.error(
                        "Hosted FED resolution failed scope=%s "
                        "status=%s error=%s",
                        managed.profile.scope_id,
                        outcome.status.value,
                        outcome.error,
                    )
        elif state is CoordinatorState.COMPLETED:
            completed = profile_count
            for managed in self._managed:
                self._complete_profile(managed)
        elif state is CoordinatorState.FAILED:
            failed = profile_count
            for managed in self._managed:
                self._block_profile(managed)
        elif state is CoordinatorState.CLOSED:
            expired = profile_count
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
        if self._managed:
            try:
                self._managed[0].coordinator.close()
            except Exception as exc:
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

    def _prepare_batch(
        self,
        rows: Sequence[
            tuple[ResolutionExecutionProfile, FedMarketBinding]
        ],
    ) -> tuple[list[_ManagedFedResolution], Any]:
        if not rows:
            raise ValueError("FED batch requires at least one profile")
        batch_scope_id = f"{self._spec.decision_id}:execution_batch"
        source = FedResolutionSource(
            lambda: self._signal,
            scope_id=batch_scope_id,
        )
        rules: list[NumericThresholdRule] = []
        for profile, binding in rows:
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
            rules.append(
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
                )
            )
        strategy = NumericThresholdStrategy(
            tuple(rules)
        )
        profiles = tuple(profile for profile, _binding in rows)
        executor = self._new_executor(profiles)
        coordinator = ResolutionTradingCoordinator(
            source=source,
            strategies=(strategy,),
            executor=executor,
            context=PreparationContext(
                scope_id=batch_scope_id,
                source=FED_SOURCE_NAME,
                source_reference=self._spec.board_statement_url,
                attributes={
                    "profile_keys": tuple(
                        profile.profile_key for profile in profiles
                    ),
                    "ticker": "FED",
                    "decision_id": self._spec.decision_id,
                },
            ),
        )
        preparation = coordinator.prepare()
        return (
            [
                _ManagedFedResolution(
                    profile=profile,
                    binding=binding,
                    coordinator=coordinator,
                    executor=executor,
                )
                for profile, binding in rows
            ],
            preparation,
        )

    def _new_executor(
        self,
        profiles: Sequence[ResolutionExecutionProfile],
    ) -> PreparedExecutor:
        profile_rows = tuple(profiles)
        if not profile_rows:
            raise ValueError("FED executor requires at least one profile")
        if self._executor_factory is not None:
            return self._executor_factory(profile_rows[0])
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
        if any(
            isinstance(
                profile.lifecycle_policy,
                RepriceOnTickChange,
            )
            for profile in profile_rows
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
        if not self._managed:
            return
        managed = self._managed[0]
        try:
            _expire_executor(managed.executor, reason=reason)
        finally:
            managed.coordinator.close()

    def _detach_batch(self, *, reason: str) -> None:
        if not self._managed:
            return
        managed_rows = tuple(self._managed)
        self._managed.clear()
        first = managed_rows[0]
        try:
            _expire_executor(first.executor, reason=reason)
        finally:
            first.coordinator.close()
        for managed in managed_rows:
            self._logger.info(
                "Hosted FED resolution detached profile=%s scope=%s",
                managed.profile.profile_key,
                managed.profile.scope_id,
            )

    def _block_failed_profile(self, profile_key: str) -> None:
        if self._lifecycle_store is None:
            return
        self._lifecycle_store.block_active_profile(
            profile_key=profile_key,
            reason_code="live_profile_preparation_failed",
        )

    def _complete_profile(
        self,
        managed: _ManagedFedResolution,
    ) -> None:
        if managed.lifecycle_completed:
            return
        managed.lifecycle_completed = complete_profile_lifecycle(
            self._lifecycle_store,
            profile_key=managed.profile.profile_key,
            logger=self._logger,
        )

    def _block_profile(
        self,
        managed: _ManagedFedResolution,
    ) -> None:
        if (
            managed.lifecycle_blocked
            or managed.lifecycle_failure_status is None
        ):
            return
        managed.lifecycle_blocked = block_terminal_profile_failure(
            self._lifecycle_store,
            profile_key=managed.profile.profile_key,
            status=managed.lifecycle_failure_status,
            logger=self._logger,
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
