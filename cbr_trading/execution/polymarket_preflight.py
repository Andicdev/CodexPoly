from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Sequence

from cbr_trading.domain.intents import (
    KeepOpenPolicy,
    OrderIntent,
    OrderSide,
    OrderTemplate,
    RepriceOnTickChange,
    TimeInForce,
)
from cbr_trading.domain.results import (
    ExecutionStatus,
    OrderExecutionResult,
)
from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.execution.prepared_executor import (
    PreparationContext,
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
)
from cbr_trading.execution.supervision_gateway import (
    replacement_price_for_tick,
)
from cbr_trading.live.account_repository import (
    TradingAccountRecord,
    build_trading_account_repository,
)
from cbr_trading.live.executor import LiveOrderExecutor
from cbr_trading.live.market import PolymarketMarketGateway
from cbr_trading.live.safety import (
    LiveSafetySettings,
    build_live_order_plan,
)
from cbr_trading.secret_guard import redact_exception


@dataclass(frozen=True)
class PolymarketPreflightDetail:
    template_id: str
    account_name: str
    condition_id: str
    outcome: str
    token_id: str
    quantity: Decimal
    desired_price: Decimal
    effective_price: Decimal
    tick_size: Decimal
    minimum_order_size: Decimal
    best_bid: Decimal | None
    best_ask: Decimal | None
    order_presigned: bool
    collateral_sufficient: bool


class PolymarketPreflightPreparedExecutor:
    """Authenticate and pre-sign arbitrary templates without submitting."""

    def __init__(
        self,
        *,
        database_url: str,
        safety: LiveSafetySettings,
        account_repository: Any | None = None,
        market_gateway: Any | None = None,
        live_executor: Any | None = None,
        db_session_factory: Callable[[], Any] | None = None,
    ):
        self._database_url = str(database_url or "").strip()
        self._safety = safety
        self._account_repository = account_repository
        self._market_gateway = market_gateway
        self._live_executor = live_executor
        self._db_session_factory = db_session_factory
        self._context: PreparationContext | None = None
        self._prepared: dict[str, OrderTemplate] = {}
        self._details: tuple[PolymarketPreflightDetail, ...] = ()
        self._maximum_notional = Decimal("0")
        self._execution_started = False
        self._closed = False

    @property
    def details(self) -> tuple[PolymarketPreflightDetail, ...]:
        return self._details

    @property
    def maximum_notional(self) -> Decimal:
        return self._maximum_notional

    def prepare(
        self,
        templates: Sequence[OrderTemplate],
        *,
        context: PreparationContext,
    ) -> PreparationSummary:
        template_rows = tuple(templates)
        if self._closed:
            return _failed_summary(
                template_rows,
                context=context,
                error="preflight_executor_closed",
            )
        if self._context is not None:
            return _failed_summary(
                template_rows,
                context=context,
                error="preflight_executor_already_prepared",
            )
        self._context = context
        if not self._database_url:
            return _failed_summary(
                template_rows,
                context=context,
                error="primary_database_not_configured",
            )

        try:
            self._resolve_dependencies()
            validation_safety = replace(
                self._safety,
                trading_enabled=True,
            )
            accounts: dict[str, TradingAccountRecord] = {}
            details: list[PolymarketPreflightDetail] = []
            maximum_notional = Decimal("0")
            prepared: dict[str, OrderTemplate] = {}
            for template in template_rows:
                if not isinstance(template, OrderTemplate):
                    raise TypeError(
                        "templates must contain OrderTemplate objects"
                    )
                if template.template_id in prepared:
                    raise ValueError("duplicate_template_id")
                if template.side != OrderSide.BUY:
                    raise ValueError("only_buy_templates_are_supported")
                if template.time_in_force != TimeInForce.GTC:
                    raise ValueError("only_gtc_templates_are_supported")
                if template.quantity is None or template.notional is not None:
                    raise ValueError(
                        "preflight currently requires share quantity"
                    )

                account_key = template.account_name.casefold()
                account = accounts.get(account_key)
                if account is None:
                    account = self._account_repository.load_active(
                        template.account_name
                    )
                    accounts[account_key] = account
                    accounts[account.name.casefold()] = account

                snapshot = self._market_gateway.load_snapshot(
                    condition_id=template.condition_id,
                    outcome=template.outcome.value,
                )
                effective_price = effective_price_for_template(
                    template,
                    tick_size=snapshot.tick_size,
                )
                plan = build_live_order_plan(
                    account=account,
                    rule_id=template.metadata.get("rule_id"),
                    rule_key=str(
                        template.metadata.get("rule_key") or ""
                    ),
                    quantity=template.quantity,
                    limit_price=effective_price,
                    snapshot=snapshot,
                    settings=validation_safety,
                )
                if plan.blockers:
                    raise ValueError(
                        f"Template {template.template_id} is blocked: "
                        + ",".join(plan.blockers)
                    )

                authenticated = (
                    self._live_executor.check_authenticated(
                        plan=plan,
                        account=account,
                        settings=validation_safety,
                        presign=True,
                    )
                )
                maximum_notional += plan.notional
                if (
                    validation_safety.max_total_notional is None
                    or maximum_notional
                    > validation_safety.max_total_notional
                ):
                    raise ValueError(
                        "prepared templates exceed aggregate notional cap"
                    )
                prepared[template.template_id] = template
                details.append(
                    PolymarketPreflightDetail(
                        template_id=template.template_id,
                        account_name=account.name,
                        condition_id=snapshot.condition_id,
                        outcome=template.outcome.value,
                        token_id=snapshot.token_id,
                        quantity=template.quantity,
                        desired_price=template.desired_price,
                        effective_price=effective_price,
                        tick_size=snapshot.tick_size,
                        minimum_order_size=(
                            snapshot.minimum_order_size
                        ),
                        best_bid=snapshot.best_bid,
                        best_ask=snapshot.best_ask,
                        order_presigned=(
                            authenticated.order_presigned
                        ),
                        collateral_sufficient=True,
                    )
                )
        except Exception as exc:
            self._prepared = {}
            self._details = ()
            self._maximum_notional = Decimal("0")
            return _failed_summary(
                template_rows,
                context=context,
                error=redact_exception(exc),
            )

        self._prepared = prepared
        self._details = tuple(details)
        self._maximum_notional = maximum_notional
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=template.template_id,
                    status=PreparationStatus.READY,
                    prepared_key=_prepared_key(
                        context,
                        template.template_id,
                    ),
                )
                for template in template_rows
            ),
            context=context,
        )

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        signal: ResolutionSignal,
    ) -> tuple[OrderExecutionResult, ...]:
        intent_rows = tuple(intents)
        if (
            not self._prepared
            or self._context is None
            or self._closed
        ):
            return _skipped_results(
                intent_rows,
                error="preflight_executor_not_ready",
            )
        if self._execution_started:
            return _skipped_results(
                intent_rows,
                error="preflight_executor_already_used",
            )
        if (
            signal.source.casefold()
            != self._context.source.casefold()
            or signal.signal_id != self._context.scope_id
        ):
            return _skipped_results(
                intent_rows,
                error="preflight_signal_scope_mismatch",
            )

        self._execution_started = True
        results: list[OrderExecutionResult] = []
        for intent in intent_rows:
            template = self._prepared.get(intent.template_id)
            if (
                template is None
                or intent
                != template.bind(signal_id=signal.signal_id)
            ):
                results.append(
                    OrderExecutionResult(
                        intent=intent,
                        status=ExecutionStatus.SKIPPED,
                        attempted=False,
                        error="preflight_intent_not_prepared",
                    )
                )
                continue
            results.append(
                OrderExecutionResult(
                    intent=intent,
                    status=ExecutionStatus.DRY_RUN,
                    attempted=False,
                )
            )
        return tuple(results)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._account_repository, "close", None)
        if callable(close):
            close()

    def _resolve_dependencies(self) -> None:
        if self._account_repository is None:
            self._account_repository = build_trading_account_repository(
                database_url=self._database_url,
                session_factory=self._db_session_factory,
            )
        if self._market_gateway is None:
            self._market_gateway = PolymarketMarketGateway()
        if self._live_executor is None:
            self._live_executor = LiveOrderExecutor()


def effective_price_for_template(
    template: OrderTemplate,
    *,
    tick_size: Decimal,
) -> Decimal:
    policy = template.lifecycle_policy
    if isinstance(policy, KeepOpenPolicy):
        return template.desired_price
    if not isinstance(policy, RepriceOnTickChange):
        raise TypeError("unsupported_lifecycle_policy")
    current_tick = Decimal(str(tick_size))
    if current_tick not in {policy.old_tick, policy.new_tick}:
        raise ValueError("unexpected_tick_size_for_reprice_policy")
    return replacement_price_for_tick(
        template.desired_price,
        tick_size=current_tick,
        side=template.side,
    )


def _prepared_key(
    context: PreparationContext,
    template_id: str,
) -> str:
    payload = (
        f"{context.scope_id}|{context.source}|{template_id}"
    ).encode("utf-8")
    return f"preflight:{hashlib.sha256(payload).hexdigest()}"


def _failed_summary(
    templates: Sequence[OrderTemplate],
    *,
    context: PreparationContext,
    error: str,
) -> PreparationSummary:
    safe_error = str(error or "preflight_failed").strip()
    return PreparationSummary(
        items=tuple(
            PreparationItem(
                template_id=template.template_id,
                status=PreparationStatus.FAILED,
                error=safe_error,
            )
            for template in templates
            if isinstance(template, OrderTemplate)
        ),
        context=context,
    )


def _skipped_results(
    intents: Sequence[OrderIntent],
    *,
    error: str,
) -> tuple[OrderExecutionResult, ...]:
    return tuple(
        OrderExecutionResult(
            intent=intent,
            status=ExecutionStatus.SKIPPED,
            attempted=False,
            error=error,
        )
        for intent in intents
    )
