from __future__ import annotations

import asyncio
import logging
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
from cbr_trading.earnings import (
    EarningsFactCandidate,
    EarningsMarketRule,
    SqlAlchemyEarningsStore,
)
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
from cbr_trading.orchestration import (
    ResolutionExecutionProfile,
    SqlAlchemyResolutionProfileStore,
    order_templates_from_profile,
)
from cbr_trading.resolution_hosted.settings import (
    HostedResolutionMode,
    HostedResolutionSettings,
)
from cbr_trading.secret_guard import redact_exception
from cbr_trading.sources.earnings import (
    EARNINGS_NON_GAAP_EPS_METRIC,
    EARNINGS_SOURCE_NAME,
    EarningsResolutionSource,
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


@dataclass(frozen=True)
class HostedPreparation:
    profile_key: str
    scope_id: str
    ticker: str
    ready: bool
    template_count: int
    error: str | None = None


@dataclass(frozen=True)
class HostedPollResult:
    fact_count: int
    waiting_count: int
    completed_count: int
    failed_count: int
    expired_count: int = 0


@dataclass
class _ManagedResolution:
    profile: ResolutionExecutionProfile
    rule: EarningsMarketRule
    coordinator: ResolutionTradingCoordinator
    executor: PreparedExecutor


class EarningsHostedResolutionWorker:
    """Poll validated facts and compose the source-neutral trading path."""

    def __init__(
        self,
        *,
        settings: HostedResolutionSettings,
        earnings_store: SqlAlchemyEarningsStore,
        profile_store: SqlAlchemyResolutionProfileStore,
        executor_factory: ExecutorFactory | None = None,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger | None = None,
    ):
        self._settings = settings
        self._earnings_store = earnings_store
        self._profile_store = profile_store
        self._executor_factory = executor_factory
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._logger = logger or logging.getLogger(
            "cbr_trading.resolution_hosted"
        )
        self._managed: list[_ManagedResolution] = []
        self._facts_by_scope: dict[
            str,
            tuple[EarningsFactCandidate, ...],
        ] = {}
        self._supervision_runtime: (
            OrderSupervisionRuntime | None
        ) = None
        self._supervisor: PersistentOrderSupervisor | None = None
        self._closed = False
        self._poll_count = 0

    @property
    def managed_count(self) -> int:
        return len(self._managed)

    def prepare(self) -> tuple[HostedPreparation, ...]:
        if self._closed:
            raise RuntimeError("hosted resolution worker is closed")
        if self._managed:
            raise RuntimeError(
                "hosted resolution worker is already prepared"
            )
        self._earnings_store.ensure_ready()
        self._profile_store.ensure_ready()
        rules = tuple(self._earnings_store.load_active_rules())
        profiles = tuple(
            self._profile_store.load_enabled(
                source_name=EARNINGS_SOURCE_NAME,
            )
        )
        if not profiles:
            return ()
        rules_by_scope = {rule.scope_id: rule for rule in rules}
        if len(rules_by_scope) != len(rules):
            raise ValueError(
                "active earnings rules contain duplicate scopes"
            )
        if (
            self._settings.mode is HostedResolutionMode.LIVE
            and any(
                isinstance(
                    profile.lifecycle_policy,
                    RepriceOnTickChange,
                )
                for profile in profiles
            )
        ):
            if not self._settings.supervision_enabled:
                raise ValueError(
                    "live reprice profiles require "
                    "RESOLUTION_SUPERVISION_ENABLED"
                )
            self._start_supervision()

        results: list[HostedPreparation] = []
        failures: list[str] = []
        for profile in profiles:
            try:
                rule = _validated_rule(profile, rules_by_scope)
                managed, preparation = self._prepare_one(
                    profile=profile,
                    rule=rule,
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
                            ticker=rule.ticker,
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
                    continue
                self._managed.append(managed)
                results.append(
                    HostedPreparation(
                        profile_key=profile.profile_key,
                        scope_id=profile.scope_id,
                        ticker=rule.ticker,
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
                        ticker=(
                            rules_by_scope[profile.scope_id].ticker
                            if profile.scope_id in rules_by_scope
                            else "UNKNOWN"
                        ),
                        ready=False,
                        template_count=0,
                        error=error,
                    )
                )
        if failures:
            for managed in self._managed:
                _expire_executor(
                    managed.executor,
                    reason="preparation_batch_failed",
                )
            self.close()
            raise RuntimeError(
                "Hosted resolution preparation failed: "
                + "; ".join(failures)
            )
        return tuple(results)

    def poll_once(self) -> HostedPollResult:
        if self._closed:
            raise RuntimeError("hosted resolution worker is closed")
        if not self._managed:
            return HostedPollResult(
                fact_count=0,
                waiting_count=0,
                completed_count=0,
                failed_count=0,
                expired_count=0,
            )
        facts = tuple(
            self._earnings_store.load_validated_facts()
        )
        grouped: dict[str, list[EarningsFactCandidate]] = defaultdict(
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
            raise ValueError("hosted resolution clock must be timezone-aware")
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
                        "Hosted earnings resolution expired "
                        "scope=%s ticker=%s",
                        managed.rule.scope_id,
                        managed.rule.ticker,
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
                        "Hosted earnings resolution completed "
                        "scope=%s ticker=%s mode=%s intents=%s "
                        "results=%s",
                        managed.rule.scope_id,
                        managed.rule.ticker,
                        self._settings.mode.value,
                        len(outcome.intents),
                        len(outcome.order_results),
                    )
                else:
                    failed += 1
                    self._logger.error(
                        "Hosted earnings resolution failed "
                        "scope=%s ticker=%s status=%s error=%s",
                        managed.rule.scope_id,
                        managed.rule.ticker,
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
        while not self._closed:
            preparations = await asyncio.to_thread(self.prepare)
            if preparations:
                break
            self._logger.warning(
                "Hosted resolution has no enabled in-window profiles"
            )
            await asyncio.sleep(
                self._settings.no_profiles_retry_delay
            )
        if self._closed:
            return
        self._logger.info(
            "Hosted resolution ready mode=%s profiles=%s templates=%s",
            self._settings.mode.value,
            len(preparations),
            sum(item.template_count for item in preparations),
        )
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            while True:
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

    def _prepare_one(
        self,
        *,
        profile: ResolutionExecutionProfile,
        rule: EarningsMarketRule,
    ) -> tuple[_ManagedResolution, Any]:
        source = EarningsResolutionSource(
            candidate_provider=lambda: self._facts_by_scope.get(
                profile.scope_id,
                (),
            ),
            rules=(rule,),
        )
        yes_template, no_template = order_templates_from_profile(
            profile,
            strategy_id=NUMERIC_THRESHOLD_STRATEGY_ID,
            metadata={
                "rule_key": rule.rule_key,
                "ticker": rule.ticker,
            },
        )
        strategy = NumericThresholdStrategy(
            (
                NumericThresholdRule(
                    rule_key=rule.rule_key,
                    source=EARNINGS_SOURCE_NAME,
                    subject=_signal_subject(rule),
                    metric=_signal_metric(rule),
                    comparison_op=rule.comparison_op,
                    strike=rule.strike,
                    rounding_places=rule.rounding_places,
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
                    "ticker": rule.ticker,
                },
            ),
        )
        preparation = coordinator.prepare()
        return (
            _ManagedResolution(
                profile=profile,
                rule=rule,
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
                "Hosted resolution heartbeat mode=%s profiles=%s "
                "polls=%s states=%s",
                self._settings.mode.value,
                len(self._managed),
                self._poll_count,
                dict(states),
            )


def _validated_rule(
    profile: ResolutionExecutionProfile,
    rules_by_scope: dict[str, EarningsMarketRule],
) -> EarningsMarketRule:
    rule = rules_by_scope.get(profile.scope_id)
    if rule is None:
        raise ValueError(
            "execution profile has no active earnings source rule"
        )
    if profile.source_name.casefold() != EARNINGS_SOURCE_NAME.casefold():
        raise ValueError("execution profile source does not match earnings")
    if not rule.condition_id:
        raise ValueError("earnings rule has no condition_id")
    if profile.condition_id.casefold() != rule.condition_id.casefold():
        raise ValueError(
            "execution profile condition_id does not match source rule"
        )
    return rule


def _signal_subject(rule: EarningsMarketRule) -> str:
    return (
        f"company:{rule.ticker}:earnings:"
        f"{rule.fiscal_year}Q{rule.fiscal_quarter}"
    )


def _signal_metric(rule: EarningsMarketRule) -> str:
    return (
        EARNINGS_NON_GAAP_EPS_METRIC
        if rule.metric.value == "non_gaap_eps"
        else "company.earnings.eps.gaap"
    )


def _expire_executor(
    executor: PreparedExecutor,
    *,
    reason: str,
) -> None:
    expire = getattr(executor, "expire_pending", None)
    if callable(expire):
        expire(reason=reason)
