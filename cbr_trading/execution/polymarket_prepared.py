from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence

from cbr_trading.domain.intents import (
    OrderIntent,
    OrderSide,
    OrderTemplate,
    TimeInForce,
)
from cbr_trading.domain.results import (
    ExecutionHandle,
    ExecutionStatus,
    OrderExecutionResult,
    PlacedOrder,
)
from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.execution.polymarket_preflight import (
    PolymarketPreflightDetail,
    effective_price_for_template,
)
from cbr_trading.execution.prepared_executor import (
    PreparationContext,
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
)
from cbr_trading.live.account_repository import (
    SqlAlchemyTradingAccountRepository,
    TradingAccountRecord,
)
from cbr_trading.live.executor import (
    decrypt_private_key,
    signature_type_for_wallet,
)
from cbr_trading.live.market import PolymarketMarketGateway
from cbr_trading.live.resolution_idempotency import (
    SqlAlchemyResolutionExecutionLedger,
    make_resolution_idempotency_key,
)
from cbr_trading.live.safety import (
    LiveOrderPlan,
    LiveSafetySettings,
    build_live_order_plan,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)


_COLLATERAL_SCALE = Decimal("1000000")
_ACCEPTED_STATUSES = frozenset({"LIVE", "MATCHED", "DELAYED"})


class PolymarketPreparedExecutionError(RuntimeError):
    """Sanitized failure while warming a source-neutral live executor."""


@dataclass(frozen=True)
class _PreparedOrder:
    template: OrderTemplate
    account: TradingAccountRecord
    client: Any
    plan: LiveOrderPlan
    signed_order: Any
    detail: PolymarketPreflightDetail


@dataclass(frozen=True)
class _SelectedOrder:
    index: int
    intent: OrderIntent
    prepared: _PreparedOrder
    claim: Any


class PolymarketPreparedExecutor:
    """Pre-sign and submit arbitrary source-neutral Polymarket templates."""

    def __init__(
        self,
        *,
        database_url: str,
        safety: LiveSafetySettings,
        account_repository: Any | None = None,
        market_gateway: Any | None = None,
        ledger: Any | None = None,
        client_factory: Callable[[str, str], Any] | None = None,
        decryptor: Callable[[bytes, str], str] | None = None,
    ):
        self._database_url = str(database_url or "").strip()
        self._safety = safety
        self._account_repository = account_repository
        self._market_gateway = market_gateway
        self._ledger = ledger
        self._client_factory = client_factory
        self._decryptor = decryptor or decrypt_private_key
        self._context: PreparationContext | None = None
        self._prepared: dict[str, _PreparedOrder] = {}
        self._claims: dict[str, Any] = {}
        self._clients: dict[str, Any] = {}
        self._accounts: dict[str, TradingAccountRecord] = {}
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

    def claim_id_for_template(self, template_id: str) -> int:
        claim = self._claims.get(str(template_id or "").strip())
        if claim is None:
            raise PolymarketPreparedExecutionError(
                "Resolution execution claim is unavailable"
            )
        return int(claim.claim_id)

    def record_cleanup(
        self,
        *,
        template_id: str,
        cleanup: Mapping[str, Any],
    ) -> None:
        if self._ledger is None:
            raise PolymarketPreparedExecutionError(
                "Resolution execution ledger is unavailable"
            )
        self._ledger.record_cleanup(
            self.claim_id_for_template(template_id),
            cleanup=cleanup,
        )

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
                error="polymarket_executor_closed",
            )
        if self._context is not None:
            return _failed_summary(
                template_rows,
                context=context,
                error="polymarket_executor_already_prepared",
            )
        self._context = context

        try:
            if not self._database_url:
                raise PolymarketPreparedExecutionError(
                    "Primary database URL is not configured"
                )
            self._validate_global_safety()
            self._resolve_dependencies()
            self._ledger.ensure_ready()

            prepared: dict[str, _PreparedOrder] = {}
            details: list[PolymarketPreflightDetail] = []
            notional_by_account: dict[str, Decimal] = {}
            balance_by_account: dict[str, Decimal] = {}
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
                        "live execution currently requires share quantity"
                    )

                account, client, balance = self._load_warm_account(
                    template.account_name
                )
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
                    settings=self._safety,
                )
                if plan.blockers:
                    raise ValueError(
                        f"Template {template.template_id} is blocked: "
                        + ",".join(plan.blockers)
                    )
                self._refresh_authenticated_book(
                    client=client,
                    plan=plan,
                )
                signed_order = client.create_limit_order(
                    token_id=plan.token_id,
                    price=str(plan.limit_price),
                    size=str(plan.quantity),
                    side=template.side.value,
                    post_only=plan.post_only,
                )
                _validate_signed_order(
                    signed_order,
                    plan=plan,
                )

                account_key = account.name.casefold()
                balance_by_account[account_key] = balance
                notional_by_account[account_key] = (
                    notional_by_account.get(
                        account_key,
                        Decimal("0"),
                    )
                    + plan.notional
                )
                prepared[template.template_id] = _PreparedOrder(
                    template=template,
                    account=account,
                    client=client,
                    plan=plan,
                    signed_order=signed_order,
                    detail=PolymarketPreflightDetail(
                        template_id=template.template_id,
                        account_name=account.name,
                        condition_id=plan.condition_id,
                        outcome=template.outcome.value,
                        token_id=plan.token_id,
                        quantity=plan.quantity,
                        desired_price=template.desired_price,
                        effective_price=plan.limit_price,
                        tick_size=plan.tick_size,
                        minimum_order_size=plan.minimum_order_size,
                        best_bid=plan.best_bid,
                        best_ask=plan.best_ask,
                        order_presigned=True,
                        collateral_sufficient=True,
                    ),
                )
                details.append(
                    prepared[template.template_id].detail
                )

            for account_key, maximum in notional_by_account.items():
                if balance_by_account[account_key] < maximum:
                    raise PolymarketPreparedExecutionError(
                        "Insufficient collateral for prepared account"
                    )
            maximum_notional = sum(
                notional_by_account.values(),
                Decimal("0"),
            )
            if (
                self._safety.max_total_notional is None
                or maximum_notional
                > self._safety.max_total_notional
            ):
                raise PolymarketPreparedExecutionError(
                    "Prepared templates exceed aggregate notional cap"
                )

            claims = tuple(
                self._ledger.reserve_many(
                    context=context,
                    templates=tuple(
                        item.template for item in prepared.values()
                    ),
                    effective_prices={
                        template_id: item.plan.limit_price
                        for template_id, item in prepared.items()
                    },
                )
            )
            if len(claims) != len(prepared):
                raise PolymarketPreparedExecutionError(
                    "Resolution claim reservation count mismatch"
                )
            claim_by_template = {
                claim.template_id: claim for claim in claims
            }
            if set(claim_by_template) != set(prepared):
                raise PolymarketPreparedExecutionError(
                    "Resolution claim reservation identity mismatch"
                )
        except Exception as exc:
            self._prepared = {}
            self._claims = {}
            self._details = ()
            self._maximum_notional = Decimal("0")
            return _failed_summary(
                template_rows,
                context=context,
                error=redact_exception(exc),
            )

        self._prepared = prepared
        self._claims = claim_by_template
        self._details = tuple(details)
        self._maximum_notional = maximum_notional
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=template.template_id,
                    status=PreparationStatus.READY,
                    prepared_key=make_resolution_idempotency_key(
                        scope_id=context.scope_id,
                        template_id=template.template_id,
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
                error="polymarket_executor_not_ready",
            )
        if self._execution_started:
            return _skipped_results(
                intent_rows,
                error="polymarket_executor_already_used",
            )
        if (
            signal.source.casefold()
            != self._context.source.casefold()
            or signal.signal_id != self._context.scope_id
        ):
            return _skipped_results(
                intent_rows,
                error="polymarket_signal_scope_mismatch",
            )

        self._execution_started = True
        results: list[OrderExecutionResult | None] = [
            None
        ] * len(intent_rows)
        selected: list[_SelectedOrder] = []
        selected_template_ids: set[str] = set()
        for index, intent in enumerate(intent_rows):
            prepared = self._prepared.get(intent.template_id)
            if (
                prepared is None
                or intent
                != prepared.template.bind(
                    signal_id=signal.signal_id
                )
            ):
                results[index] = OrderExecutionResult(
                    intent=intent,
                    status=ExecutionStatus.SKIPPED,
                    attempted=False,
                    error="polymarket_intent_not_prepared",
                )
                continue
            claim = self._claims.get(intent.template_id)
            if claim is None:
                results[index] = OrderExecutionResult(
                    intent=intent,
                    status=ExecutionStatus.SKIPPED,
                    attempted=False,
                    error="resolution_execution_claim_missing",
                )
                continue
            selected_template_ids.add(intent.template_id)
            selected.append(
                _SelectedOrder(
                    index=index,
                    intent=intent,
                    prepared=prepared,
                    claim=claim,
                )
            )

        batches: dict[int, list[_SelectedOrder]] = {}
        for item in selected:
            batches.setdefault(
                id(item.prepared.client),
                [],
            ).append(item)
        for batch in batches.values():
            self._post_batch(batch, results=results)
        self._complete_selected(selected, results=results)
        self._expire_unselected(selected_template_ids)

        return tuple(
            result
            if result is not None
            else OrderExecutionResult(
                intent=intent_rows[index],
                status=ExecutionStatus.SKIPPED,
                attempted=False,
                error="polymarket_batch_result_missing",
            )
            for index, result in enumerate(results)
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        seen: set[int] = set()
        for client in self._clients.values():
            marker = id(client)
            if marker in seen:
                continue
            seen.add(marker)
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        self._clients.clear()
        self._accounts.clear()

        for dependency in (
            self._account_repository,
            self._ledger,
        ):
            close = getattr(dependency, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise PolymarketPreparedExecutionError(
                redact_exception(first_error)
            ) from None

    def _validate_global_safety(self) -> None:
        blockers: list[str] = []
        if not self._safety.trading_enabled:
            blockers.append("live_trading_disabled")
        if not self._safety.allowed_account:
            blockers.append("allowed_account_not_configured")
        if self._safety.max_order_quantity is None:
            blockers.append("max_order_qty_not_configured")
        if self._safety.max_notional is None:
            blockers.append("max_notional_not_configured")
        if self._safety.max_total_notional is None:
            blockers.append("max_total_notional_not_configured")
        if not self._safety.accounts_master_key:
            blockers.append("accounts_master_key_missing")
        if blockers:
            raise PolymarketPreparedExecutionError(
                "Live safety is not armed: " + ",".join(blockers)
            )

    def _resolve_dependencies(self) -> None:
        if self._account_repository is None:
            self._account_repository = (
                SqlAlchemyTradingAccountRepository(
                    database_url=self._database_url
                )
            )
        if self._market_gateway is None:
            self._market_gateway = PolymarketMarketGateway()
        if self._ledger is None:
            self._ledger = SqlAlchemyResolutionExecutionLedger(
                database_url=self._database_url
            )

    def _load_warm_account(
        self,
        account_name: str,
    ) -> tuple[TradingAccountRecord, Any, Decimal]:
        key = account_name.casefold()
        if key in self._accounts:
            account = self._accounts[key]
            client = self._clients[key]
            return account, client, _balance_decimal(client)

        account = self._account_repository.load_active(account_name)
        if (
            account.name.casefold()
            != self._safety.allowed_account.casefold()
        ):
            raise PolymarketPreparedExecutionError(
                "Loaded account is not the allowed live account"
            )
        private_key = self._decryptor(
            account.encrypted_private_key,
            self._safety.accounts_master_key or "",
        )
        client = self._new_client(
            private_key=private_key,
            wallet=account.wallet_address,
        )
        try:
            wallet = str(getattr(client, "wallet", "") or "")
            wallet_type = str(
                getattr(client, "wallet_type", "") or ""
            )
            if wallet.casefold() != account.wallet_address.casefold():
                raise PolymarketPreparedExecutionError(
                    "Authenticated wallet does not match the database"
                )
            if (
                signature_type_for_wallet(wallet_type)
                != account.signature_type
            ):
                raise PolymarketPreparedExecutionError(
                    "Authenticated wallet signature type does not "
                    "match the database"
                )
            balance = _balance_decimal(client)
        except Exception:
            close = getattr(client, "close", None)
            if callable(close):
                close()
            raise

        canonical_key = account.name.casefold()
        self._accounts[key] = account
        self._accounts[canonical_key] = account
        self._clients[key] = client
        self._clients[canonical_key] = client
        return account, client, balance

    def _new_client(
        self,
        *,
        private_key: str,
        wallet: str,
    ) -> Any:
        if self._client_factory is not None:
            return self._client_factory(private_key, wallet)
        try:
            from polymarket import SecureClient
        except ImportError as exc:
            raise PolymarketPreparedExecutionError(
                "Live execution requires polymarket-client"
            ) from exc
        return SecureClient.create(
            private_key=private_key,
            wallet=wallet,
        )

    @staticmethod
    def _refresh_authenticated_book(
        *,
        client: Any,
        plan: LiveOrderPlan,
    ) -> None:
        book = client.get_order_book(token_id=plan.token_id)
        if str(getattr(book, "condition_id", "") or "").casefold() != (
            plan.condition_id.casefold()
        ):
            raise PolymarketPreparedExecutionError(
                "Authenticated order book condition mismatch"
            )
        tick_size = Decimal(str(book.tick_size))
        minimum_order_size = Decimal(str(book.min_order_size))
        if plan.limit_price % tick_size != 0:
            raise PolymarketPreparedExecutionError(
                "Latest tick size rejects the prepared price"
            )
        if plan.quantity < minimum_order_size:
            raise PolymarketPreparedExecutionError(
                "Latest minimum order size rejects the quantity"
            )
        asks = tuple(
            Decimal(str(level.price))
            for level in getattr(book, "asks", ())
        )
        if (
            plan.post_only
            and asks
            and plan.limit_price >= min(asks)
        ):
            raise PolymarketPreparedExecutionError(
                "BUY would cross latest ask; post-only order skipped"
            )

    def _post_batch(
        self,
        items: Sequence[_SelectedOrder],
        *,
        results: list[OrderExecutionResult | None],
    ) -> None:
        if not items:
            return
        client = items[0].prepared.client
        try:
            responses = tuple(
                client.post_orders(
                    [
                        item.prepared.signed_order
                        for item in items
                    ]
                )
            )
            if len(responses) != len(items):
                raise PolymarketPreparedExecutionError(
                    "Polymarket batch response count mismatch"
                )
        except Exception as exc:
            error = redact_exception(exc)
            for item in items:
                results[item.index] = OrderExecutionResult(
                    intent=item.intent,
                    status=ExecutionStatus.AMBIGUOUS,
                    attempted=True,
                    error=error,
                )
            return

        for item, response in zip(items, responses, strict=True):
            ok = getattr(response, "ok", None)
            if ok is True:
                order_id = str(
                    getattr(response, "order_id", "") or ""
                ).strip()
                remote_status = str(
                    getattr(response, "status", "") or ""
                ).strip().upper()
                if (
                    not order_id
                    or remote_status not in _ACCEPTED_STATUSES
                ):
                    results[item.index] = OrderExecutionResult(
                        intent=item.intent,
                        status=ExecutionStatus.AMBIGUOUS,
                        attempted=True,
                        error=(
                            "Polymarket accepted an order without a "
                            "usable order identity"
                        ),
                    )
                    continue
                placed = PlacedOrder(
                    order_id=order_id,
                    asset_id=item.prepared.plan.token_id,
                    effective_price=(
                        item.prepared.plan.limit_price
                    ),
                    quantity=item.prepared.plan.quantity,
                )
                handle = _execution_handle(
                    item.intent,
                    placed=placed,
                )
                results[item.index] = OrderExecutionResult(
                    intent=item.intent,
                    status=ExecutionStatus.SUBMITTED,
                    attempted=True,
                    orders=(placed,),
                    handle=handle,
                )
                continue

            if ok is False:
                error = redact_sensitive_text(
                    f"{getattr(response, 'code', 'unknown')}: "
                    f"{getattr(response, 'message', 'order rejected')}"
                )
                results[item.index] = OrderExecutionResult(
                    intent=item.intent,
                    status=ExecutionStatus.REJECTED,
                    attempted=True,
                    error=error,
                )
                continue

            results[item.index] = OrderExecutionResult(
                intent=item.intent,
                status=ExecutionStatus.AMBIGUOUS,
                attempted=True,
                error="Polymarket returned an indeterminate order result",
            )

    def _complete_selected(
        self,
        items: Sequence[_SelectedOrder],
        *,
        results: list[OrderExecutionResult | None],
    ) -> None:
        for item in items:
            result = results[item.index]
            if result is None:
                continue
            if result.status == ExecutionStatus.SUBMITTED:
                ledger_status = "EXECUTED"
            elif result.status == ExecutionStatus.REJECTED:
                ledger_status = "REJECTED"
            else:
                ledger_status = "ERROR"
            try:
                self._ledger.complete(
                    item.claim.claim_id,
                    status=ledger_status,
                    result={
                        "attempted": result.attempted,
                        "accepted": (
                            result.status
                            == ExecutionStatus.SUBMITTED
                        ),
                        "order_ids": [
                            order.order_id
                            for order in result.orders
                        ],
                        "token_id": item.prepared.plan.token_id,
                        "status": result.status.value,
                    },
                    error=result.error,
                )
            except Exception as exc:
                results[item.index] = OrderExecutionResult(
                    intent=result.intent,
                    status=ExecutionStatus.AMBIGUOUS,
                    attempted=result.attempted,
                    orders=result.orders,
                    handle=result.handle,
                    error=(
                        "Order result is known locally but ledger "
                        "completion failed: "
                        f"{type(exc).__name__}"
                    ),
                )

    def _expire_unselected(
        self,
        selected_template_ids: set[str],
    ) -> None:
        for template_id, claim in self._claims.items():
            if template_id in selected_template_ids:
                continue
            try:
                self._ledger.complete(
                    claim.claim_id,
                    status="EXPIRED",
                    result={
                        "attempted": False,
                        "reason": "template_not_selected",
                    },
                )
            except Exception:
                pass


def _balance_decimal(client: Any) -> Decimal:
    balance = client.get_balance_allowance(
        asset_type="COLLATERAL"
    )
    return Decimal(int(balance.balance)) / _COLLATERAL_SCALE


def _validate_signed_order(
    signed_order: Any,
    *,
    plan: LiveOrderPlan,
) -> None:
    if (
        str(getattr(signed_order, "token_id", ""))
        != plan.token_id
        or str(getattr(signed_order, "order_type", ""))
        != "GTC"
        or bool(getattr(signed_order, "post_only", False))
        != plan.post_only
    ):
        raise PolymarketPreparedExecutionError(
            "Pre-signed order does not match the GTC order plan"
        )


def _execution_handle(
    intent: OrderIntent,
    *,
    placed: PlacedOrder,
) -> ExecutionHandle:
    digest = hashlib.sha256(
        (
            f"{intent.intent_id}|{placed.order_id}|"
            f"{placed.asset_id}"
        ).encode("utf-8")
    ).hexdigest()
    return ExecutionHandle(
        order_group_id=f"resolution:v1:{digest}",
        intent_id=intent.intent_id,
        signal_id=intent.signal_id,
        template_id=intent.template_id,
        strategy_id=intent.strategy_id,
        account_name=intent.account_name,
        condition_id=intent.condition_id,
        outcome=intent.outcome,
        side=intent.side,
        asset_id=placed.asset_id,
        desired_price=intent.desired_price,
        quantity=intent.quantity,
        notional=intent.notional,
        live_order_ids=(placed.order_id,),
    )


def _failed_summary(
    templates: Sequence[OrderTemplate],
    *,
    context: PreparationContext,
    error: str,
) -> PreparationSummary:
    safe_error = str(error or "live_preparation_failed").strip()
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
