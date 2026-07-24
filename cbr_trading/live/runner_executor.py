from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Sequence

from cbr_trading.client import DiscoveryResult
from cbr_trading.live.account_repository import (
    SqlAlchemyTradingAccountRepository,
    TradingAccountRecord,
)
from cbr_trading.live.executor import (
    decrypt_private_key,
    signature_type_for_wallet,
)
from cbr_trading.live.idempotency import SqlAlchemyExecutionLedger
from cbr_trading.live.market import (
    PolymarketMarketGateway,
)
from cbr_trading.live.safety import (
    LiveSafetySettings,
    build_live_order_plan,
)
from cbr_trading.pipeline import (
    OrderExecutionResult,
    OrderIntent,
)
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)
from cbr_trading.trading_rules import resolve_order_price


_COLLATERAL_SCALE = Decimal("1000000")


class LivePreparationError(RuntimeError):
    """Fail-closed error while warming the automatic live executor."""


@dataclass(frozen=True)
class LivePreparedOrderSummary:
    rule_id: int | str | None
    rule_key: str
    account_name: str
    condition_id: str
    outcome: str
    token_id: str
    quantity: Decimal
    limit_price: Decimal


@dataclass(frozen=True)
class LivePreparationSummary:
    rule_count: int
    account_count: int
    outcome_count: int
    maximum_notional: Decimal
    prepared_orders: tuple[LivePreparedOrderSummary, ...] = ()


@dataclass(frozen=True)
class _PreparedOutcome:
    account: TradingAccountRecord
    client: Any
    rule_id: int | str | None
    rule_key: str
    condition_id: str
    question: str
    outcome: str
    token_id: str
    quantity: Decimal
    limit_price: Decimal
    signed_order: Any


@dataclass(frozen=True)
class _ReservedOrder:
    index: int
    intent: OrderIntent
    prepared: _PreparedOutcome
    claim: Any


class WarmLiveOrderExecutor:
    """Pre-sign before polling and batch-post orders after publication."""

    def __init__(
        self,
        *,
        subscriptions: Sequence[Mapping[str, Any]],
        database_url: str,
        safety: LiveSafetySettings,
        account_repository: Any | None = None,
        market_gateway: Any | None = None,
        ledger: Any | None = None,
        client_factory: Callable[[str, str], Any] | None = None,
        decryptor: Callable[[bytes, str], str] | None = None,
    ):
        self._subscriptions = tuple(dict(item) for item in subscriptions)
        self._database_url = str(database_url or "").strip()
        self._safety = safety
        self._account_repository = account_repository
        self._market_gateway = market_gateway
        self._ledger = ledger
        self._client_factory = client_factory
        self._decryptor = decryptor or decrypt_private_key
        self._prepared: dict[tuple[str, str], _PreparedOutcome] = {}
        self._claims: dict[tuple[str, str], Any] = {}
        self._clients: dict[str, Any] = {}
        self._accounts: dict[str, TradingAccountRecord] = {}
        self._reserved_release_url = ""
        self._prepared_ok = False
        self._execution_started = False

    def prepare(
        self,
        *,
        release_url: str,
        reserve_claims: bool = True,
    ) -> LivePreparationSummary:
        if self._prepared_ok:
            raise LivePreparationError(
                "Live executor has already been prepared"
            )
        if not self._subscriptions:
            raise LivePreparationError(
                "No active CBR rules are available for live execution"
            )
        if not self._database_url:
            raise LivePreparationError(
                "Primary database URL is not configured"
            )
        normalized_release_url = str(release_url or "").strip()
        if not normalized_release_url:
            raise LivePreparationError(
                "Predicted release URL is required before polling"
            )
        self._validate_global_safety()
        self._resolve_dependencies()
        self._ledger.ensure_ready()

        maximum_by_account: dict[str, Decimal] = {}
        rule_count = 0
        for subscription in self._subscriptions:
            rule_id = subscription.get("id")
            rule_key = str(
                subscription.get("rule_key") or "default"
            ).strip()
            account_name = str(
                subscription.get("account_name") or ""
            ).strip()
            condition_id = str(
                subscription.get("condition_id") or ""
            ).strip()
            quantity = _required_decimal(
                subscription.get("order_qty"),
                name="order_qty",
            )
            if not account_name or not condition_id:
                raise LivePreparationError(
                    f"Rule {rule_id!r} is missing account or condition"
                )

            account, client, balance = self._load_warm_account(
                account_name
            )
            action_notionals: list[Decimal] = []
            for action in ("YES", "NO"):
                price = _required_decimal(
                    resolve_order_price(subscription, action),
                    name=f"{action} order price",
                )
                snapshot = self._market_gateway.load_snapshot(
                    condition_id=condition_id,
                    outcome=action,
                )
                plan = build_live_order_plan(
                    account=account,
                    rule_id=rule_id,
                    rule_key=rule_key,
                    quantity=quantity,
                    limit_price=price,
                    snapshot=snapshot,
                    settings=self._safety,
                )
                permanent_blockers = tuple(
                    blocker
                    for blocker in plan.blockers
                    if blocker != "buy_would_cross_current_ask"
                )
                if permanent_blockers:
                    raise LivePreparationError(
                        f"Rule {rule_id!r} {action} is blocked: "
                        + ",".join(permanent_blockers)
                    )
                try:
                    signed_order = client.create_limit_order(
                        token_id=plan.token_id,
                        price=str(plan.limit_price),
                        size=str(plan.quantity),
                        side="BUY",
                        post_only=plan.post_only,
                    )
                except Exception as exc:
                    raise LivePreparationError(
                        f"Failed to pre-sign rule {rule_id!r} {action}: "
                        f"{type(exc).__name__}"
                    ) from exc
                if (
                    str(getattr(signed_order, "token_id", ""))
                    != plan.token_id
                    or str(getattr(signed_order, "order_type", ""))
                    != "GTC"
                    or bool(getattr(signed_order, "post_only", False))
                    != plan.post_only
                ):
                    raise LivePreparationError(
                        f"Pre-signed rule {rule_id!r} {action} "
                        "does not match the GTC order plan"
                    )

                key = (_rule_key(rule_id), action)
                if key in self._prepared:
                    raise LivePreparationError(
                        f"Duplicate prepared rule outcome: {key!r}"
                    )
                self._prepared[key] = _PreparedOutcome(
                    account=account,
                    client=client,
                    rule_id=rule_id,
                    rule_key=rule_key,
                    condition_id=snapshot.condition_id,
                    question=snapshot.question,
                    outcome=action,
                    token_id=snapshot.token_id,
                    quantity=plan.quantity,
                    limit_price=plan.limit_price,
                    signed_order=signed_order,
                )
                action_notionals.append(plan.notional)

            account_key = account.name.casefold()
            maximum_by_account[account_key] = (
                maximum_by_account.get(account_key, Decimal("0"))
                + max(action_notionals)
            )
            if balance < maximum_by_account[account_key]:
                raise LivePreparationError(
                    f"Insufficient collateral for prepared account "
                    f"{account.name!r}"
                )
            rule_count += 1

        maximum_total_notional = sum(
            maximum_by_account.values(),
            Decimal("0"),
        )
        if (
            self._safety.max_total_notional is None
            or maximum_total_notional
            > self._safety.max_total_notional
        ):
            raise LivePreparationError(
                "Prepared rules exceed the configured aggregate "
                "notional cap"
            )
        if reserve_claims:
            reservation_items = tuple(self._prepared.items())
            reservation_intents = tuple(
                _intent_from_prepared(prepared)
                for _, prepared in reservation_items
            )
            try:
                claims = tuple(
                    self._ledger.reserve_many(
                        release_url=normalized_release_url,
                        intents=reservation_intents,
                    )
                )
            except Exception as exc:
                raise LivePreparationError(
                    "Failed to reserve all live orders before polling: "
                    f"{type(exc).__name__}"
                ) from exc
            if len(claims) != len(reservation_items):
                raise LivePreparationError(
                    "Execution ledger reservation count mismatch"
                )
            self._claims = {
                key: claim
                for (key, _), claim in zip(
                    reservation_items,
                    claims,
                    strict=True,
                )
            }
        self._reserved_release_url = normalized_release_url

        self._prepared_ok = True
        return LivePreparationSummary(
            rule_count=rule_count,
            account_count=len(
                {id(client) for client in self._clients.values()}
            ),
            outcome_count=len(self._prepared),
            maximum_notional=maximum_total_notional,
            prepared_orders=tuple(
                LivePreparedOrderSummary(
                    rule_id=prepared.rule_id,
                    rule_key=prepared.rule_key,
                    account_name=prepared.account.name,
                    condition_id=prepared.condition_id,
                    outcome=prepared.outcome,
                    token_id=prepared.token_id,
                    quantity=prepared.quantity,
                    limit_price=prepared.limit_price,
                )
                for prepared in self._prepared.values()
            ),
        )

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        release: DiscoveryResult,
    ) -> list[OrderExecutionResult]:
        if not self._prepared_ok:
            return [
                OrderExecutionResult(
                    intent=intent,
                    status="SKIPPED",
                    attempted=False,
                    success=None,
                    error="live_executor_not_prepared",
                )
                for intent in intents
            ]
        if self._execution_started:
            return [
                OrderExecutionResult(
                    intent=intent,
                    status="SKIPPED",
                    attempted=False,
                    success=None,
                    error="live_executor_already_used",
                )
                for intent in intents
            ]
        if (
            str(release.url or "").strip()
            != self._reserved_release_url
        ):
            return [
                OrderExecutionResult(
                    intent=intent,
                    status="SKIPPED",
                    attempted=False,
                    success=None,
                    error="reserved_release_url_mismatch",
                )
                for intent in intents
            ]
        self._execution_started = True

        results: list[OrderExecutionResult | None] = [None] * len(intents)
        reserved: list[_ReservedOrder] = []
        selected_keys: set[tuple[str, str]] = set()
        for index, intent in enumerate(intents):
            prepared, error = self._match_prepared(intent)
            if error is not None:
                results[index] = OrderExecutionResult(
                    intent=intent,
                    status="SKIPPED",
                    attempted=False,
                    success=None,
                    error=error,
                )
                continue
            if prepared is None:
                results[index] = OrderExecutionResult(
                    intent=intent,
                    status="SKIPPED",
                    attempted=False,
                    success=None,
                    error="prepared_order_missing",
                )
                continue
            key = (
                _rule_key(intent.rule_id),
                intent.action.upper(),
            )
            claim = self._claims.get(key)
            if claim is None:
                results[index] = OrderExecutionResult(
                    intent=intent,
                    status="SKIPPED",
                    attempted=False,
                    success=None,
                    error="live_reservation_missing",
                )
                continue
            selected_keys.add(key)
            reserved.append(
                _ReservedOrder(
                    index=index,
                    intent=intent,
                    prepared=prepared,
                    claim=claim,
                )
            )

        groups: dict[int, list[_ReservedOrder]] = {}
        for item in reserved:
            groups.setdefault(id(item.prepared.client), []).append(item)
        for items in groups.values():
            self._post_batch(items, results=results)
        self._persist_selected_results(reserved, results=results)
        self._expire_unselected_reservations(selected_keys)

        return [
            result
            if result is not None
            else OrderExecutionResult(
                intent=intents[index],
                status="SKIPPED",
                attempted=False,
                success=None,
                error="live_batch_result_missing",
            )
            for index, result in enumerate(results)
        ]

    def _match_prepared(
        self,
        intent: OrderIntent,
    ) -> tuple[_PreparedOutcome | None, str | None]:
        if not intent.ready:
            return None, intent.reason
        prepared = self._prepared.get(
            (_rule_key(intent.rule_id), intent.action.upper())
        )
        if prepared is None:
            return None, "prepared_rule_outcome_not_found"
        if (
            prepared.condition_id.casefold()
            != intent.condition_id.casefold()
            or prepared.account.name.casefold()
            != intent.account_name.casefold()
        ):
            return None, "prepared_order_identity_mismatch"
        try:
            quantity = _required_decimal(
                intent.quantity,
                name="intent quantity",
            )
            limit_price = _required_decimal(
                intent.limit_price,
                name="intent limit price",
            )
        except LivePreparationError as exc:
            return None, str(exc)
        if (
            quantity != prepared.quantity
            or limit_price != prepared.limit_price
        ):
            return None, "prepared_order_parameters_mismatch"
        return prepared, None

    def _post_batch(
        self,
        items: Sequence[_ReservedOrder],
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
                raise LivePreparationError(
                    "Polymarket batch response count mismatch"
                )
        except Exception as exc:
            error = _safe_exception(exc)
            for item in items:
                results[item.index] = OrderExecutionResult(
                    intent=item.intent,
                    status="AMBIGUOUS",
                    attempted=True,
                    success=None,
                    error=error,
                )
            return

        for item, response in zip(items, responses, strict=True):
            if response.ok:
                order_id = str(response.order_id)
                status = str(response.status).upper()
                results[item.index] = OrderExecutionResult(
                    intent=item.intent,
                    status=status,
                    attempted=True,
                    success=True,
                    order_id=order_id,
                )
                continue

            error = redact_sensitive_text(
                f"{str(response.code)}: "
                f"{str(response.message)}"
            )
            results[item.index] = OrderExecutionResult(
                intent=item.intent,
                status="REJECTED",
                attempted=True,
                success=False,
                error=error,
            )

    def _persist_selected_results(
        self,
        items: Sequence[_ReservedOrder],
        *,
        results: list[OrderExecutionResult | None],
    ) -> None:
        """Persist only after every selected account batch was submitted."""
        for item in items:
            order_result = results[item.index]
            if order_result is None:
                continue
            if order_result.success is True:
                ledger_status = "EXECUTED"
            elif order_result.success is False:
                ledger_status = "REJECTED"
            else:
                ledger_status = "ERROR"
            ledger_warning = self._complete_claim(
                claim_id=item.claim.claim_id,
                status=ledger_status,
                result={
                    "attempted": order_result.attempted,
                    "accepted": order_result.success,
                    "order_id": order_result.order_id,
                    "status": order_result.status,
                    "token_id": item.prepared.token_id,
                },
                error=order_result.error,
            )
            if ledger_warning is None:
                continue
            results[item.index] = OrderExecutionResult(
                intent=order_result.intent,
                status=order_result.status,
                attempted=order_result.attempted,
                success=order_result.success,
                order_id=order_result.order_id,
                error=ledger_warning,
            )

    def _expire_unselected_reservations(
        self,
        selected_keys: set[tuple[str, str]],
    ) -> None:
        for key, claim in self._claims.items():
            if key in selected_keys:
                continue
            self._complete_claim(
                claim_id=claim.claim_id,
                status="EXPIRED",
                result={
                    "attempted": False,
                    "reason": "outcome_not_selected",
                },
            )

    def _complete_claim(
        self,
        *,
        claim_id: int,
        status: str,
        result: Mapping[str, Any],
        error: str | None = None,
    ) -> str | None:
        try:
            self._ledger.complete(
                claim_id=claim_id,
                status=status,
                result=result,
                error=error,
            )
        except Exception as exc:
            return (
                "order result recorded locally but ledger update failed: "
                f"{type(exc).__name__}"
            )
        return None

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
            raise LivePreparationError(
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
            self._ledger = SqlAlchemyExecutionLedger(
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
            balance = _balance_decimal(client)
            return account, client, balance

        account = self._account_repository.load_active(account_name)
        if (
            account.name.casefold()
            != self._safety.allowed_account.casefold()
        ):
            raise LivePreparationError(
                f"Account {account.name!r} is not the allowed live account"
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
                raise LivePreparationError(
                    "Authenticated wallet does not match the database"
                )
            if (
                signature_type_for_wallet(wallet_type)
                != account.signature_type
            ):
                raise LivePreparationError(
                    "Authenticated wallet signature type does not "
                    "match the database"
                )
            balance = _balance_decimal(client)
        except Exception:
            close = getattr(client, "close", None)
            if callable(close):
                close()
            raise

        stored_key = account.name.casefold()
        self._accounts[stored_key] = account
        self._clients[stored_key] = client
        if stored_key != key:
            self._accounts[key] = account
            self._clients[key] = client
        return account, client, balance

    def _new_client(self, *, private_key: str, wallet: str) -> Any:
        if self._client_factory is not None:
            return self._client_factory(private_key, wallet)
        try:
            from polymarket import SecureClient
        except ImportError as exc:
            raise LivePreparationError(
                "Automatic live execution requires polymarket-client"
            ) from exc
        return SecureClient.create(
            private_key=private_key,
            wallet=wallet,
        )

    def close(self) -> None:
        seen: set[int] = set()
        for client in self._clients.values():
            marker = id(client)
            if marker in seen:
                continue
            seen.add(marker)
            close = getattr(client, "close", None)
            if callable(close):
                close()
        self._clients.clear()
        self._accounts.clear()

        for dependency in (
            self._account_repository,
            self._ledger,
        ):
            close = getattr(dependency, "close", None)
            if callable(close):
                close()


class UnavailableLiveOrderExecutor:
    """Report a startup failure per intent while monitoring still continues."""

    def __init__(self, error: str):
        self.error = " ".join(str(error or "").split())[:240]

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        release: DiscoveryResult,
    ) -> list[OrderExecutionResult]:
        return [
            OrderExecutionResult(
                intent=intent,
                status="SKIPPED",
                attempted=False,
                success=None,
                error=f"live_preparation_failed: {self.error}",
            )
            for intent in intents
        ]


def _balance_decimal(client: Any) -> Decimal:
    balance = client.get_balance_allowance(
        asset_type="COLLATERAL"
    )
    return Decimal(int(balance.balance)) / _COLLATERAL_SCALE


def _required_decimal(value: Any, *, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LivePreparationError(f"Invalid {name}") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise LivePreparationError(f"Invalid {name}")
    return parsed


def _intent_from_prepared(
    prepared: _PreparedOutcome,
) -> OrderIntent:
    return OrderIntent(
        rule_id=prepared.rule_id,
        rule_key=prepared.rule_key,
        account_name=prepared.account.name,
        condition_id=prepared.condition_id,
        action=prepared.outcome,
        quantity=prepared.quantity,
        limit_price=prepared.limit_price,
        ready=True,
        reason="reserved_before_polling",
    )


def _rule_key(rule_id: int | str | None) -> str:
    return str(rule_id)


def _safe_exception(exc: Exception) -> str:
    return redact_exception(exc, max_length=220)
