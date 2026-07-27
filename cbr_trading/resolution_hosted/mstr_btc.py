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
from cbr_trading.domain import RepriceOnTickChange
from cbr_trading.execution import (
    DryRunPreparedExecutor,
    PersistentOrderSupervisor,
    PolymarketPreflightPreparedExecutor,
    PolymarketPreparedExecutor,
    PreparationContext,
    PreparedExecutor,
    SupervisedPreparedExecutor,
)
from cbr_trading.live import (
    OrderSupervisionRuntime,
    SqlAlchemyOrderGroupRepository,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.live.supervision_gateway import (
    PolymarketSupervisionOrderGateway,
)
from cbr_trading.mstr_btc import (
    MstrBtcFactCandidate,
    MstrBtcMarketBinding,
    MstrBtcResolutionRule,
    SqlAlchemyMstrBtcAuditStore,
    mstr_jul21_27_market_bindings,
    mstr_jul21_27_resolution_rules,
)
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    SqlAlchemyResolutionProfileStore,
    order_templates_from_profile,
)
from cbr_trading.resolution_hosted.earnings import (
    HostedPollResult,
    HostedPreparation,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.resolution_hosted.batch_safety import (
    validate_profile_batch_notional,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources import (
    MSTR_BTC_SOURCE_NAME,
    MstrBtcResolutionSource,
    mstr_btc_signal_metric,
    mstr_btc_signal_subject,
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
class _ManagedMstrResolution:
    profile: ResolutionExecutionProfile
    rule: MstrBtcResolutionRule
    binding: MstrBtcMarketBinding
    coordinator: ResolutionTradingCoordinator
    executor: PreparedExecutor


class MstrBtcHostedResolutionWorker:
    """Compose persisted MSTR facts with market-scoped numeric strategies."""

    def __init__(
        self,
        *,
        settings: HostedResolutionSettings,
        audit_store: SqlAlchemyMstrBtcAuditStore,
        profile_store: SqlAlchemyResolutionProfileStore,
        lifecycle_store: Any | None = None,
        rules: Sequence[MstrBtcResolutionRule] | None = None,
        bindings: Sequence[MstrBtcMarketBinding] | None = None,
        executor_factory: ExecutorFactory | None = None,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._audit_store = audit_store
        self._profile_store = profile_store
        self._lifecycle_store = lifecycle_store
        self._rules = tuple(
            rules
            if rules is not None
            else mstr_jul21_27_resolution_rules()
        )
        self._bindings = tuple(
            bindings
            if bindings is not None
            else mstr_jul21_27_market_bindings()
        )
        _validate_rule_bindings(self._rules, self._bindings)
        self._executor_factory = executor_factory
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._logger = logger or logging.getLogger(
            "cbr_trading.resolution_hosted.mstr_btc"
        )
        self._managed: list[_ManagedMstrResolution] = []
        self._facts_by_scope: dict[
            str,
            tuple[MstrBtcFactCandidate, ...],
        ] = {}
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
            raise RuntimeError("hosted MSTR resolution worker is closed")
        if self._managed:
            raise RuntimeError(
                "hosted MSTR resolution worker is already prepared"
            )
        return self.reconcile_profiles()

    def reconcile_profiles(self) -> tuple[HostedPreparation, ...]:
        """Match in-memory coordinators to the current enabled profiles."""
        if self._closed:
            raise RuntimeError("hosted MSTR resolution worker is closed")
        self._ensure_ready()
        profiles = tuple(
            self._profile_store.load_enabled(
                source_name=MSTR_BTC_SOURCE_NAME,
            )
        )

        rules_by_signal = {
            rule.signal_id: rule for rule in self._rules
        }
        bindings_by_signal = {
            binding.signal_id: binding
            for binding in self._bindings
        }
        enabled_keys = {profile.profile_key for profile in profiles}
        retained: list[_ManagedMstrResolution] = []
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
                "Hosted MSTR resolution detached "
                "profile=%s scope=%s",
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
        if needs_supervision:
            if not self._settings.supervision_enabled:
                raise ValueError(
                    "live reprice profiles require "
                    "RESOLUTION_SUPERVISION_ENABLED"
                )
        if self._settings.mode is not HostedResolutionMode.SHADOW:
            enabled_batch = tuple(
                self._profile_store.load_enabled()
            )
            validate_profile_batch_notional(
                enabled_batch,
                mode=self._settings.mode,
                safety=LiveSafetySettings.from_env(),
            )
        if needs_supervision:
            self._start_supervision()

        results: list[HostedPreparation] = []
        failures: list[str] = []
        newly_managed: list[_ManagedMstrResolution] = []
        for profile in new_profiles:
            try:
                rule, binding = _validated_profile_rule(
                    profile,
                    rules_by_signal=rules_by_signal,
                    bindings_by_signal=bindings_by_signal,
                )
                managed, preparation = self._prepare_one(
                    profile=profile,
                    rule=rule,
                    binding=binding,
                )
                if not preparation.ready:
                    error = (
                        preparation.error
                        or "executor_preparation_not_ready"
                    )
                    failures.append(
                        f"{profile.profile_key}: {error}"
                    )
                    results.append(
                        HostedPreparation(
                            profile_key=profile.profile_key,
                            scope_id=profile.scope_id,
                            ticker="MSTR",
                            ready=False,
                            template_count=len(
                                preparation.templates
                            ),
                            error=error,
                        )
                    )
                    _expire_executor(
                        managed.executor,
                        reason="preparation_failed",
                    )
                    managed.coordinator.close()
                    self._block_failed_profile(
                        profile.profile_key
                    )
                    continue
                newly_managed.append(managed)
                results.append(
                    HostedPreparation(
                        profile_key=profile.profile_key,
                        scope_id=profile.scope_id,
                        ticker="MSTR",
                        ready=True,
                        template_count=len(
                            preparation.templates
                        ),
                    )
                )
            except Exception as exc:
                error = redact_exception(exc)
                failures.append(
                    f"{profile.profile_key}: {error}"
                )
                results.append(
                    HostedPreparation(
                        profile_key=profile.profile_key,
                        scope_id=profile.scope_id,
                        ticker="MSTR",
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
                "Hosted MSTR resolution preparation failed: "
                + "; ".join(failures)
            )
        self._managed.extend(newly_managed)
        return tuple(results)

    def poll_once(self) -> HostedPollResult:
        if self._closed:
            raise RuntimeError("hosted MSTR resolution worker is closed")
        if not self._managed:
            return HostedPollResult(
                fact_count=0,
                waiting_count=0,
                completed_count=0,
                failed_count=0,
                expired_count=0,
            )

        weekly_scopes = sorted(
            {managed.rule.weekly_scope_id for managed in self._managed}
        )
        facts = tuple(
            fact
            for scope_id in weekly_scopes
            for fact in self._audit_store.load_validated_facts(
                scope_id=scope_id,
            )
        )
        grouped: dict[str, list[MstrBtcFactCandidate]] = defaultdict(
            list
        )
        for fact in facts:
            grouped[fact.scope_id].append(fact)
        self._facts_by_scope = {
            scope_id: tuple(rows)
            for scope_id, rows in grouped.items()
        }

        waiting = 0
        completed = 0
        failed = 0
        expired = 0
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(
                "hosted MSTR resolution clock must be timezone-aware"
            )
        now = now.astimezone(timezone.utc)
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
                    self._logger.warning(
                        "Hosted MSTR resolution expired "
                        "scope=%s rule=%s",
                        managed.profile.scope_id,
                        managed.rule.rule_key,
                    )
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
                        "Hosted MSTR resolution completed "
                        "scope=%s rule=%s mode=%s intents=%s "
                        "results=%s",
                        managed.profile.scope_id,
                        managed.rule.rule_key,
                        self._settings.mode.value,
                        len(outcome.intents),
                        len(outcome.order_results),
                    )
                else:
                    failed += 1
                    self._logger.error(
                        "Hosted MSTR resolution failed "
                        "scope=%s rule=%s status=%s error=%s",
                        managed.profile.scope_id,
                        managed.rule.rule_key,
                        outcome.status.value,
                        outcome.error,
                    )
            elif state is CoordinatorState.COMPLETED:
                completed += 1
            elif state is CoordinatorState.FAILED:
                failed += 1
            elif state is CoordinatorState.CLOSED:
                expired += 1
        self._poll_count += 1
        return HostedPollResult(
            fact_count=len(facts),
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
                            "Hosted MSTR resolution attached "
                            "mode=%s profiles=%s templates=%s",
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
                            "Hosted MSTR resolution has no enabled "
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
        if first_error is not None:
            raise RuntimeError(redact_exception(first_error)) from None

    def _ensure_ready(self) -> None:
        if self._schemas_ready:
            return
        self._audit_store.ensure_ready()
        self._profile_store.ensure_ready()
        if self._lifecycle_store is not None:
            self._lifecycle_store.ensure_ready()
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

    def _prepare_one(
        self,
        *,
        profile: ResolutionExecutionProfile,
        rule: MstrBtcResolutionRule,
        binding: MstrBtcMarketBinding,
    ) -> tuple[_ManagedMstrResolution, Any]:
        source = MstrBtcResolutionSource(
            candidate_provider=lambda: self._facts_by_scope.get(
                rule.weekly_scope_id,
                (),
            ),
            rules=(rule,),
        )
        yes_template, no_template = order_templates_from_profile(
            profile,
            strategy_id=NUMERIC_THRESHOLD_STRATEGY_ID,
            metadata={
                "rule_key": rule.rule_key,
                "ticker": "MSTR",
                "market_slug": binding.market_slug,
                "weekly_scope_id": rule.weekly_scope_id,
            },
        )
        strategy = NumericThresholdStrategy(
            (
                NumericThresholdRule(
                    rule_key=rule.rule_key,
                    source=MSTR_BTC_SOURCE_NAME,
                    subject=mstr_btc_signal_subject(
                        rule.weekly_scope_id
                    ),
                    metric=mstr_btc_signal_metric(rule.activity),
                    comparison_op=rule.comparison_op,
                    strike=rule.threshold_btc,
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
                    "ticker": "MSTR",
                    "rule_key": rule.rule_key,
                    "weekly_scope_id": rule.weekly_scope_id,
                },
            ),
        )
        preparation = coordinator.prepare()
        return (
            _ManagedMstrResolution(
                profile=profile,
                rule=rule,
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
            )
        delegate: PreparedExecutor = PolymarketPreparedExecutor(
            database_url=self._settings.database_url or "",
            safety=safety,
        )
        if isinstance(
            profile.lifecycle_policy,
            RepriceOnTickChange,
        ):
            if self._supervisor is None:
                raise RuntimeError(
                    "order supervisor is unavailable"
                )
            return SupervisedPreparedExecutor(
                delegate,
                supervisor=self._supervisor,
            )
        return delegate

    def _start_supervision(self) -> None:
        if self._supervision_runtime is not None:
            return
        safety = LiveSafetySettings.from_env()
        repository = SqlAlchemyOrderGroupRepository(
            database_url=self._settings.database_url,
        )
        gateway = PolymarketSupervisionOrderGateway(
            database_url=self._settings.database_url or "",
            safety=safety,
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

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._settings.heartbeat_interval
            )
            states: dict[str, int] = defaultdict(int)
            for managed in self._managed:
                states[managed.coordinator.state.value] += 1
            self._logger.info(
                "Hosted MSTR resolution heartbeat mode=%s "
                "profiles=%s polls=%s states=%s",
                self._settings.mode.value,
                len(self._managed),
                self._poll_count,
                dict(states),
            )


def _validate_rule_bindings(
    rules: Sequence[MstrBtcResolutionRule],
    bindings: Sequence[MstrBtcMarketBinding],
) -> None:
    if not rules:
        raise ValueError("at least one MSTR resolution rule is required")
    if not bindings:
        raise ValueError("at least one MSTR market binding is required")
    rule_signal_ids = [rule.signal_id for rule in rules]
    binding_signal_ids = [binding.signal_id for binding in bindings]
    if len(rule_signal_ids) != len(set(rule_signal_ids)):
        raise ValueError("MSTR resolution rule signal_ids must be unique")
    if len(binding_signal_ids) != len(set(binding_signal_ids)):
        raise ValueError("MSTR market binding signal_ids must be unique")
    if set(rule_signal_ids) != set(binding_signal_ids):
        raise ValueError(
            "MSTR rules and market bindings must cover the same signals"
        )
    bindings_by_signal = {
        binding.signal_id: binding for binding in bindings
    }
    for rule in rules:
        binding = bindings_by_signal[rule.signal_id]
        if binding.rule_key != rule.rule_key:
            raise ValueError(
                "MSTR market binding rule_key does not match source rule"
            )


def _validated_profile_rule(
    profile: ResolutionExecutionProfile,
    *,
    rules_by_signal: dict[str, MstrBtcResolutionRule],
    bindings_by_signal: dict[str, MstrBtcMarketBinding],
) -> tuple[MstrBtcResolutionRule, MstrBtcMarketBinding]:
    rule = rules_by_signal.get(profile.scope_id)
    binding = bindings_by_signal.get(profile.scope_id)
    if rule is None or binding is None:
        raise ValueError(
            "execution profile has no checked-in MSTR source rule"
        )
    if profile.source_name.casefold() != MSTR_BTC_SOURCE_NAME.casefold():
        raise ValueError("execution profile source does not match MSTR")
    if profile.condition_id.casefold() != binding.condition_id.casefold():
        raise ValueError(
            "execution profile condition_id does not match MSTR market"
        )
    if (
        profile.source_reference.rstrip("/").casefold()
        != binding.source_reference.casefold()
    ):
        raise ValueError(
            "execution profile source_reference does not match MSTR market"
        )
    return rule, binding


def _expire_executor(
    executor: PreparedExecutor,
    *,
    reason: str,
) -> None:
    expire = getattr(executor, "expire_pending", None)
    if callable(expire):
        expire(reason=reason)
