from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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
from cbr_trading.live.idempotency import (
    ExecutionLedgerError,
    SqlAlchemyExecutionLedger,
)
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
class LivePreparationSummary:
    rule_count: int
    account_count: int
    outcome_count: int
    maximum_notional: Decimal


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
class _ClaimedOrder:
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
        self._clients: dict[str, Any] = {}
        self._accounts: dict[str, TradingAccountRecord] = {}
        self._prepared_ok = False

    def prepare(self) -> LivePreparationSummary:
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
        warm_claim_capacity = getattr(
            self._ledger,
            "warm_claim_capacity",
            None,
        )
        if callable(warm_claim_capacity):
            warm_claim_capacity(rule_count)

        self._prepared_ok = True
        return LivePreparationSummary(
            rule_count=rule_count,
            account_count=len(
                {id(client) for client in self._clients.values()}
            ),
            outcome_count=len(self._prepared),
            maximum_notional=maximum_total_notional,
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

        results: list[OrderExecutionResult | None] = [None] * len(intents)
        candidates: list[
            tuple[int, OrderIntent, _PreparedOutcome]
        ] = []
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
            candidates.append((index, intent, prepared))

        claimed = self._claim_candidates(
            candidates,
            release=release,
            results=results,
        )
        groups: dict[int, list[_ClaimedOrder]] = {}
        for item in claimed:
            groups.setdefault(id(item.prepared.client), []).append(item)
        for items in groups.values():
            self._post_batch(items, results=results)

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

    def _claim_candidates(
        self,
        candidates: Sequence[
            tuple[int, OrderIntent, _PreparedOutcome]
        ],
        *,
        release: DiscoveryResult,
        results: list[OrderExecutionResult | None],
    ) -> list[_ClaimedOrder]:
        if not candidates:
            return []
        workers = min(len(candidates), 8)
        claimed: list[_ClaimedOrder] = []
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="cbr-idempotency",
        ) as pool:
            futures = {
                pool.submit(
                    self._ledger.claim,
                    release_url=release.url,
                    intent=intent,
                ): (index, intent, prepared)
                for index, intent, prepared in candidates
            }
            for future in as_completed(futures):
                index, intent, prepared = futures[future]
                try:
                    claim = future.result()
                except ExecutionLedgerError as exc:
                    results[index] = OrderExecutionResult(
                        intent=intent,
                        status="SKIPPED",
                        attempted=False,
                        success=None,
                        error=redact_sensitive_text(exc),
                    )
                    continue
                except Exception as exc:
                    results[index] = OrderExecutionResult(
                        intent=intent,
                        status="SKIPPED",
                        attempted=False,
                        success=None,
                        error=_safe_exception(exc),
                    )
                    continue
                if not claim.acquired:
                    detail = (
                        "idempotency="
                        f"{claim.existing_status or 'UNKNOWN'}"
                    )
                    if claim.existing_error:
                        detail += (
                            " error="
                            + redact_sensitive_text(
                                claim.existing_error
                            )
                        )
                    results[index] = OrderExecutionResult(
                        intent=intent,
                        status="DUPLICATE_SKIPPED",
                        attempted=False,
                        success=None,
                        order_id=claim.existing_order_id,
                        error=detail,
                    )
                    continue
                claimed.append(
                    _ClaimedOrder(
                        index=index,
                        intent=intent,
                        prepared=prepared,
                        claim=claim,
                    )
                )
        claimed.sort(key=lambda item: item.index)
        return claimed

    def _post_batch(
        self,
        items: Sequence[_ClaimedOrder],
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
                ledger_warning = self._complete_claim(
                    claim_id=item.claim.claim_id,
                    status="FAILED",
                    result={
                        "attempted": True,
                        "accepted": None,
                    },
                    error=error,
                )
                results[item.index] = OrderExecutionResult(
                    intent=item.intent,
                    status="AMBIGUOUS",
                    attempted=True,
                    success=None,
                    error=ledger_warning or error,
                )
            return

        for item, response in zip(items, responses, strict=True):
            if response.ok:
                order_id = str(response.order_id)
                status = str(response.status).upper()
                ledger_warning = self._complete_claim(
                    claim_id=item.claim.claim_id,
                    status="EXECUTED",
                    result={
                        "attempted": True,
                        "accepted": True,
                        "order_id": order_id,
                        "status": status,
                        "token_id": item.prepared.token_id,
                    },
                )
                results[item.index] = OrderExecutionResult(
                    intent=item.intent,
                    status=status,
                    attempted=True,
                    success=True,
                    order_id=order_id,
                    error=ledger_warning,
                )
                continue

            error = redact_sensitive_text(
                f"{str(response.code)}: "
                f"{str(response.message)}"
            )
            ledger_warning = self._complete_claim(
                claim_id=item.claim.claim_id,
                status="REJECTED",
                result={
                    "attempted": True,
                    "accepted": False,
                    "error_code": str(response.code),
                },
                error=error,
            )
            results[item.index] = OrderExecutionResult(
                intent=item.intent,
                status="REJECTED",
                attempted=True,
                success=False,
                error=ledger_warning or error,
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


def _rule_key(rule_id: int | str | None) -> str:
    return str(rule_id)


def _safe_exception(exc: Exception) -> str:
    return redact_exception(exc, max_length=220)
