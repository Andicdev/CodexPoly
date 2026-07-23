from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Any, Callable

from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.safety import LiveOrderPlan, LiveSafetySettings


_COLLATERAL_SCALE = Decimal("1000000")
_SIGNATURE_TYPE_BY_WALLET = {
    "EOA": 0,
    "POLY_PROXY": 1,
    "GNOSIS_SAFE": 2,
    "DEPOSIT_WALLET": 3,
}


class LiveOrderError(RuntimeError):
    """Fail-closed live order setup or execution error."""


@dataclass(frozen=True)
class LivePlacementResult:
    attempted: bool
    accepted: bool
    order_id: str | None
    status: str
    error_code: str | None
    message: str | None
    wallet_type: str
    collateral_balance: Decimal


class LiveOrderExecutor:
    """Submit one post-only BUY through the official Polymarket SDK."""

    def __init__(
        self,
        *,
        client_factory: Callable[[str, str], Any] | None = None,
        decryptor: Callable[[bytes, str], str] | None = None,
    ):
        self._client_factory = client_factory
        self._decryptor = decryptor or decrypt_private_key

    def place(
        self,
        *,
        plan: LiveOrderPlan,
        account: TradingAccountRecord,
        settings: LiveSafetySettings,
    ) -> LivePlacementResult:
        if not plan.ready_to_apply:
            raise LiveOrderError(
                "Live order plan is blocked: "
                + ",".join(plan.blockers)
            )
        if not settings.accounts_master_key:
            raise LiveOrderError("ACCOUNTS_MASTER_KEY is not configured")
        if plan.account_name.casefold() != account.name.casefold():
            raise LiveOrderError(
                "Order plan account does not match loaded account"
            )

        private_key = self._decryptor(
            account.encrypted_private_key,
            settings.accounts_master_key,
        )
        client = self._new_client(
            private_key=private_key,
            wallet=account.wallet_address,
        )
        try:
            wallet = str(getattr(client, "wallet", "") or "")
            if wallet.casefold() != account.wallet_address.casefold():
                raise LiveOrderError(
                    "Authenticated wallet does not match the database"
                )

            wallet_type = str(
                getattr(client, "wallet_type", "") or ""
            )
            detected_signature_type = _SIGNATURE_TYPE_BY_WALLET.get(
                wallet_type
            )
            if detected_signature_type != account.signature_type:
                raise LiveOrderError(
                    "Detected wallet signature type does not match "
                    "the database"
                )

            self._refresh_book_guard(client, plan)
            balance = client.get_balance_allowance(
                asset_type="COLLATERAL"
            )
            collateral_balance = (
                Decimal(int(balance.balance)) / _COLLATERAL_SCALE
            )
            required_raw = int(
                (plan.notional * _COLLATERAL_SCALE).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
            if int(balance.balance) < required_raw:
                raise LiveOrderError(
                    "Insufficient collateral balance for the order"
                )

            response = client.place_limit_order(
                token_id=plan.token_id,
                price=str(plan.limit_price),
                size=str(plan.quantity),
                side="BUY",
                post_only=True,
            )
            if response.ok:
                return LivePlacementResult(
                    attempted=True,
                    accepted=True,
                    order_id=str(response.order_id),
                    status=str(response.status),
                    error_code=None,
                    message=None,
                    wallet_type=wallet_type,
                    collateral_balance=collateral_balance,
                )
            return LivePlacementResult(
                attempted=True,
                accepted=False,
                order_id=None,
                status="rejected",
                error_code=str(response.code),
                message=str(response.message),
                wallet_type=wallet_type,
                collateral_balance=collateral_balance,
            )
        except LiveOrderError:
            raise
        except Exception as exc:
            raise LiveOrderError(
                "Polymarket live order failed: "
                f"{type(exc).__name__}"
            ) from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def _new_client(self, *, private_key: str, wallet: str) -> Any:
        if self._client_factory is not None:
            return self._client_factory(private_key, wallet)
        try:
            from polymarket import SecureClient
        except ImportError as exc:
            raise LiveOrderError(
                "Live execution requires polymarket-client"
            ) from exc
        return SecureClient.create(
            private_key=private_key,
            wallet=wallet,
        )

    @staticmethod
    def _refresh_book_guard(client: Any, plan: LiveOrderPlan) -> None:
        book = client.get_order_book(token_id=plan.token_id)
        if str(book.condition_id).casefold() != (
            plan.condition_id.casefold()
        ):
            raise LiveOrderError(
                "Latest order book does not match the rule condition"
            )

        tick_size = Decimal(str(book.tick_size))
        minimum_order_size = Decimal(str(book.min_order_size))
        if plan.limit_price % tick_size != 0:
            raise LiveOrderError(
                "Latest tick size rejects the configured price"
            )
        if plan.quantity < minimum_order_size:
            raise LiveOrderError(
                "Latest minimum order size rejects the quantity"
            )

        asks = [Decimal(str(level.price)) for level in book.asks]
        best_ask = min(asks) if asks else None
        if best_ask is not None and plan.limit_price >= best_ask:
            raise LiveOrderError(
                "BUY would cross the latest ask; post-only order skipped"
            )


def decrypt_private_key(
    encrypted_private_key: bytes,
    accounts_master_key: str,
) -> str:
    if not encrypted_private_key:
        raise LiveOrderError("Encrypted private key is empty")
    master_key = str(accounts_master_key or "").strip()
    if not master_key:
        raise LiveOrderError("ACCOUNTS_MASTER_KEY is not configured")
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as exc:
        raise LiveOrderError(
            "Private-key decryption requires cryptography"
        ) from exc

    try:
        private_key = Fernet(
            master_key.encode("utf-8")
        ).decrypt(encrypted_private_key).decode("utf-8").strip()
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise LiveOrderError(
            "Failed to decrypt trading account private key"
        ) from exc
    if not private_key:
        raise LiveOrderError("Decrypted private key is empty")
    return private_key
