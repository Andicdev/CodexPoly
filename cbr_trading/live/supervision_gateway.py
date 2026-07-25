from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Sequence

from cbr_trading.domain.results import PlacedOrder
from cbr_trading.execution.supervision_gateway import (
    CancellationResult,
    OrderInspectionResult,
    RemoteOrderSnapshot,
    RemoteOrderState,
    ReplacementOrderRequest,
)
from cbr_trading.live.account_repository import (
    TradingAccountRecord,
    build_trading_account_repository,
)
from cbr_trading.live.executor import (
    decrypt_private_key,
    signature_type_for_wallet,
)
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)


class PolymarketSupervisionGatewayError(RuntimeError):
    """Sanitized failure at the live cancel/replace boundary."""


class PolymarketSupervisionOrderGateway:
    """Exact-order cancellation and GTC replacement through SecureClient."""

    def __init__(
        self,
        *,
        database_url: str = "",
        safety: LiveSafetySettings,
        account_repository: Any | None = None,
        client_factory: Callable[[str, str], Any] | None = None,
        decryptor: Callable[[bytes, str], str] | None = None,
    ):
        self._database_url = str(database_url or "").strip()
        self._safety = safety
        self._account_repository = account_repository
        self._client_factory = client_factory
        self._decryptor = decryptor or decrypt_private_key
        self._clients: dict[str, Any] = {}
        self._closed = False

    def inspect_orders(
        self,
        *,
        account_name: str,
        order_ids: Sequence[str],
    ) -> OrderInspectionResult:
        self._require_open()
        requested = _normalized_order_ids(order_ids)
        client = self._client_for(account_name)
        observed_at = datetime.now(timezone.utc)
        snapshots: list[RemoteOrderSnapshot] = []
        failed: list[str] = []
        failure_types: list[str] = []
        for order_id in requested:
            try:
                remote_order = client.get_order(
                    order_id=order_id
                )
                snapshots.append(
                    _remote_order_snapshot(
                        remote_order,
                        expected_order_id=order_id,
                        observed_at=observed_at,
                    )
                )
            except Exception as exc:
                failed.append(order_id)
                failure_types.append(type(exc).__name__)
        error = None
        if failed:
            error = (
                "Polymarket order inspection failed: "
                + ",".join(dict.fromkeys(failure_types))
            )
        return OrderInspectionResult(
            requested_order_ids=requested,
            snapshots=tuple(snapshots),
            failed_order_ids=tuple(failed),
            error=error,
        )

    def cancel_orders(
        self,
        *,
        account_name: str,
        order_ids: Sequence[str],
    ) -> CancellationResult:
        self._require_open()
        requested = _normalized_order_ids(order_ids)
        client = self._client_for(account_name)
        try:
            response = client.cancel_orders(
                order_ids=requested,
            )
        except Exception as exc:
            raise PolymarketSupervisionGatewayError(
                "Polymarket exact-order cancellation failed: "
                f"{type(exc).__name__}"
            ) from exc
        return _cancellation_result(
            response,
            requested=requested,
        )

    def place_replacement(
        self,
        request: ReplacementOrderRequest,
    ) -> tuple[PlacedOrder, ...]:
        self._require_open()
        if not isinstance(request, ReplacementOrderRequest):
            raise TypeError(
                "request must be a ReplacementOrderRequest"
            )
        client = self._client_for(request.account_name)
        try:
            book = client.get_order_book(
                token_id=request.asset_id,
            )
        except Exception as exc:
            raise PolymarketSupervisionGatewayError(
                "Failed to refresh the replacement order book: "
                f"{type(exc).__name__}"
            ) from exc

        quantity = _replacement_quantity(request)
        _validate_replacement_market(
            request,
            book=book,
            quantity=quantity,
            safety=self._safety,
        )
        try:
            response = client.place_limit_order(
                token_id=request.asset_id,
                price=_decimal_text(request.limit_price),
                size=_decimal_text(quantity),
                side=request.side.value,
                post_only=self._safety.post_only,
            )
        except Exception as exc:
            raise PolymarketSupervisionGatewayError(
                "Polymarket replacement submission failed: "
                f"{type(exc).__name__}"
            ) from exc

        if getattr(response, "ok", None) is not True:
            code = redact_sensitive_text(
                getattr(response, "code", "unknown")
            )
            message = redact_sensitive_text(
                getattr(response, "message", "order rejected")
            )
            raise PolymarketSupervisionGatewayError(
                f"Polymarket replacement rejected: {code}: {message}"
            )
        order_id = str(
            getattr(response, "order_id", "") or ""
        ).strip()
        status = str(
            getattr(response, "status", "") or ""
        ).strip().lower()
        if not order_id:
            raise PolymarketSupervisionGatewayError(
                "Polymarket accepted replacement without an order ID"
            )
        if status not in {"live", "matched", "delayed"}:
            raise PolymarketSupervisionGatewayError(
                "Polymarket accepted replacement with an invalid status"
            )
        return (
            PlacedOrder(
                order_id=order_id,
                asset_id=request.asset_id,
                effective_price=request.limit_price,
                quantity=quantity,
            ),
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
            if not callable(close):
                continue
            try:
                close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        self._clients.clear()

        close_repository = getattr(
            self._account_repository,
            "close",
            None,
        )
        if callable(close_repository):
            try:
                close_repository()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise PolymarketSupervisionGatewayError(
                redact_exception(first_error)
            ) from None

    def _client_for(self, account_name: str) -> Any:
        requested = str(account_name or "").strip()
        self._require_armed_account(requested)
        key = requested.casefold()
        cached = self._clients.get(key)
        if cached is not None:
            return cached

        if self._account_repository is None:
            if not self._database_url:
                raise PolymarketSupervisionGatewayError(
                    "Trading database URL is not configured"
                )
            self._account_repository = build_trading_account_repository(
                database_url=self._database_url
            )
        try:
            account: TradingAccountRecord = (
                self._account_repository.load_active(
                    requested
                )
            )
        except Exception as exc:
            raise PolymarketSupervisionGatewayError(
                "Failed to load the supervision account: "
                f"{type(exc).__name__}"
            ) from exc
        if (
            account.name.casefold()
            != self._safety.allowed_account.casefold()
        ):
            raise PolymarketSupervisionGatewayError(
                "Loaded account is not allowed for live supervision"
            )

        try:
            private_key = self._decryptor(
                account.encrypted_private_key,
                self._safety.accounts_master_key or "",
            )
            client = self._new_client(
                private_key=private_key,
                wallet=account.wallet_address,
            )
        except Exception as exc:
            raise PolymarketSupervisionGatewayError(
                "Failed to open the supervision client: "
                f"{type(exc).__name__}"
            ) from exc
        try:
            wallet = str(
                getattr(client, "wallet", "") or ""
            ).strip()
            wallet_type = str(
                getattr(client, "wallet_type", "") or ""
            ).strip()
            if (
                wallet.casefold()
                != account.wallet_address.casefold()
            ):
                raise PolymarketSupervisionGatewayError(
                    "Authenticated wallet does not match the database"
                )
            if (
                signature_type_for_wallet(wallet_type)
                != account.signature_type
            ):
                raise PolymarketSupervisionGatewayError(
                    "Authenticated wallet signature type does not "
                    "match the database"
                )
        except Exception as exc:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            if isinstance(
                exc,
                PolymarketSupervisionGatewayError,
            ):
                raise
            raise PolymarketSupervisionGatewayError(
                "Failed to validate the supervision client: "
                f"{type(exc).__name__}"
            ) from exc

        canonical_key = account.name.casefold()
        self._clients[key] = client
        self._clients[canonical_key] = client
        return client

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
            raise PolymarketSupervisionGatewayError(
                "Live supervision requires polymarket-client"
            ) from exc
        return SecureClient.create(
            private_key=private_key,
            wallet=wallet,
        )

    def _require_armed_account(self, account_name: str) -> None:
        blockers: list[str] = []
        if not self._safety.trading_enabled:
            blockers.append("live_trading_disabled")
        if not self._safety.allowed_account:
            blockers.append("allowed_account_not_configured")
        elif (
            account_name.casefold()
            != self._safety.allowed_account.casefold()
        ):
            blockers.append("account_not_allowed")
        if not self._safety.accounts_master_key:
            blockers.append("accounts_master_key_missing")
        if blockers:
            raise PolymarketSupervisionGatewayError(
                "Live supervision is not armed: "
                + ",".join(blockers)
            )

    def _require_open(self) -> None:
        if self._closed:
            raise PolymarketSupervisionGatewayError(
                "Polymarket supervision gateway is closed"
            )


def _normalized_order_ids(
    values: Sequence[str],
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(
            "order_ids must be a sequence, not a string"
        )
    normalized = tuple(
        str(value or "").strip()
        for value in values
    )
    if not normalized or any(not value for value in normalized):
        raise ValueError(
            "order_ids must contain non-empty order IDs"
        )
    if len(normalized) != len(set(normalized)):
        raise ValueError("order_ids must be unique")
    return normalized


def _cancellation_result(
    response: object,
    *,
    requested: tuple[str, ...],
) -> CancellationResult:
    raw_cancelled = getattr(response, "canceled", None)
    raw_failed = getattr(response, "not_canceled", None)
    if (
        isinstance(raw_cancelled, (str, bytes))
        or not isinstance(raw_cancelled, Sequence)
        or not isinstance(raw_failed, Mapping)
    ):
        raise PolymarketSupervisionGatewayError(
            "Polymarket cancellation response is malformed"
        )

    cancelled_set = {
        str(value or "").strip()
        for value in raw_cancelled
    }
    failed_reasons = {
        str(order_id or "").strip(): redact_sensitive_text(reason)
        for order_id, reason in raw_failed.items()
    }
    if (
        "" in cancelled_set
        or "" in failed_reasons
        or cancelled_set & set(failed_reasons)
    ):
        raise PolymarketSupervisionGatewayError(
            "Polymarket cancellation response is inconsistent"
        )
    requested_set = set(requested)
    reported = cancelled_set | set(failed_reasons)
    if reported - requested_set:
        raise PolymarketSupervisionGatewayError(
            "Polymarket cancellation response expanded the requested scope"
        )

    cancelled = tuple(
        order_id
        for order_id in requested
        if order_id in cancelled_set
    )
    failed = tuple(
        order_id
        for order_id in requested
        if order_id not in cancelled_set
    )
    error = None
    if failed:
        reasons = tuple(
            dict.fromkeys(
                failed_reasons[order_id]
                for order_id in failed
                if failed_reasons.get(order_id)
            )
        )
        error = redact_sensitive_text(
            "Polymarket cancellation failed: "
            + "; ".join(reasons)
            if reasons
            else (
                "Polymarket cancellation response did not confirm "
                "every requested order"
            ),
            max_length=500,
        )
    return CancellationResult(
        requested_order_ids=requested,
        cancelled_order_ids=cancelled,
        failed_order_ids=failed,
        error=error,
    )


def _replacement_quantity(
    request: ReplacementOrderRequest,
) -> Decimal:
    if request.quantity is not None:
        return request.quantity
    if request.notional is None:
        raise ValueError("replacement sizing is missing")
    try:
        quantity = request.notional / request.limit_price
    except (ArithmeticError, InvalidOperation) as exc:
        raise ValueError(
            "replacement notional cannot be converted to quantity"
        ) from exc
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError("replacement quantity must be positive")
    return quantity


def _remote_order_snapshot(
    remote_order: object,
    *,
    expected_order_id: str,
    observed_at: datetime,
) -> RemoteOrderSnapshot:
    order_id = str(
        getattr(remote_order, "id", "") or ""
    ).strip()
    if order_id != expected_order_id:
        raise ValueError("remote order ID mismatch")
    condition_id = str(
        getattr(remote_order, "condition_id", "") or ""
    ).strip()
    asset_id = str(
        getattr(remote_order, "token_id", "") or ""
    ).strip()
    side = str(
        getattr(remote_order, "side", "") or ""
    ).strip().upper()
    raw_remote_status = str(
        getattr(remote_order, "status", "") or ""
    ).strip().upper()
    remote_status = _normalized_remote_status(raw_remote_status)
    try:
        limit_price = Decimal(
            str(getattr(remote_order, "price", None))
        )
        original = Decimal(
            str(getattr(remote_order, "original_size", None))
        )
        matched = Decimal(
            str(getattr(remote_order, "size_matched", None))
        )
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("remote order quantities are invalid") from exc
    remaining = original - matched
    if remaining == 0:
        state = RemoteOrderState.FILLED
    elif remote_status in {
        "ACTIVE",
        "DELAYED",
        "LIVE",
        "OPEN",
        "PARTIALLY_FILLED",
    }:
        state = RemoteOrderState.OPEN
    elif remote_status in {
        "CANCELED",
        "CANCELLED",
        "CLOSED",
        "EXPIRED",
    }:
        state = RemoteOrderState.CANCELLED
    else:
        state = RemoteOrderState.UNKNOWN
    return RemoteOrderSnapshot(
        order_id=order_id,
        condition_id=condition_id,
        asset_id=asset_id,
        side=side,
        limit_price=limit_price,
        original_quantity=original,
        matched_quantity=matched,
        state=state,
        remote_status=raw_remote_status,
        observed_at=observed_at,
    )


def _normalized_remote_status(value: str) -> str:
    prefix = "ORDER_STATUS_"
    if value.startswith(prefix):
        return value[len(prefix):]
    return value


def _validate_replacement_market(
    request: ReplacementOrderRequest,
    *,
    book: object,
    quantity: Decimal,
    safety: LiveSafetySettings,
) -> None:
    condition_id = str(
        getattr(book, "condition_id", "") or ""
    ).strip()
    token_id = str(
        getattr(book, "token_id", "") or ""
    ).strip()
    if condition_id.casefold() != request.condition_id.casefold():
        raise PolymarketSupervisionGatewayError(
            "Replacement order book condition mismatch"
        )
    if token_id != request.asset_id:
        raise PolymarketSupervisionGatewayError(
            "Replacement order book asset mismatch"
        )
    try:
        tick_size = Decimal(
            str(getattr(book, "tick_size", None))
        )
        minimum_order_size = Decimal(
            str(getattr(book, "min_order_size", None))
        )
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as exc:
        raise PolymarketSupervisionGatewayError(
            "Replacement order book metadata is invalid"
        ) from exc
    if tick_size != request.tick_size:
        raise PolymarketSupervisionGatewayError(
            "Replacement order book tick does not match the event"
        )
    if minimum_order_size <= 0:
        raise PolymarketSupervisionGatewayError(
            "Replacement minimum order size is invalid"
        )

    notional = quantity * request.limit_price
    blockers: list[str] = []
    if safety.max_order_quantity is None:
        blockers.append("max_order_qty_not_configured")
    elif quantity > safety.max_order_quantity:
        blockers.append("max_order_qty_exceeded")
    if safety.max_notional is None:
        blockers.append("max_notional_not_configured")
    elif notional > safety.max_notional:
        blockers.append("max_notional_exceeded")
    if safety.max_total_notional is None:
        blockers.append("max_total_notional_not_configured")
    elif notional > safety.max_total_notional:
        blockers.append("max_total_notional_exceeded")
    if quantity < minimum_order_size:
        blockers.append("below_market_minimum_order_size")
    if safety.post_only:
        bids = _book_prices(getattr(book, "bids", ()))
        asks = _book_prices(getattr(book, "asks", ()))
        best_bid = max(bids) if bids else None
        best_ask = min(asks) if asks else None
        if (
            request.side.value == "BUY"
            and best_ask is not None
            and request.limit_price >= best_ask
        ):
            blockers.append("post_only_buy_would_cross")
        if (
            request.side.value == "SELL"
            and best_bid is not None
            and request.limit_price <= best_bid
        ):
            blockers.append("post_only_sell_would_cross")
    if blockers:
        raise PolymarketSupervisionGatewayError(
            "Replacement order is blocked: " + ",".join(blockers)
        )


def _book_prices(levels: object) -> tuple[Decimal, ...]:
    if isinstance(levels, (str, bytes)) or not isinstance(
        levels,
        Sequence,
    ):
        raise PolymarketSupervisionGatewayError(
            "Replacement order book levels are invalid"
        )
    try:
        return tuple(
            Decimal(str(getattr(level, "price", None)))
            for level in levels
        )
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as exc:
        raise PolymarketSupervisionGatewayError(
            "Replacement order book levels are invalid"
        ) from exc


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
