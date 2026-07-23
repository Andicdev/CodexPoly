from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Mapping

from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.market import MarketSnapshot


@dataclass(frozen=True)
class LiveSafetySettings:
    trading_enabled: bool = False
    post_only: bool = True
    allowed_account: str = ""
    max_order_quantity: Decimal | None = None
    max_notional: Decimal | None = None
    max_total_notional: Decimal | None = None
    accounts_master_key: str | None = field(
        default=None,
        repr=False,
    )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "LiveSafetySettings":
        env = environ if environ is not None else os.environ
        return cls(
            trading_enabled=_parse_bool(
                env.get("CBR_LIVE_TRADING_ENABLED"),
                default=False,
            ),
            post_only=_parse_bool(
                env.get("CBR_LIVE_POST_ONLY"),
                default=True,
            ),
            allowed_account=_clean(
                env.get("CBR_LIVE_ALLOWED_ACCOUNT")
            ),
            max_order_quantity=_optional_decimal(
                env.get("CBR_LIVE_MAX_ORDER_QTY")
            ),
            max_notional=_optional_decimal(
                env.get("CBR_LIVE_MAX_NOTIONAL")
            ),
            max_total_notional=_optional_decimal(
                env.get("CBR_LIVE_MAX_TOTAL_NOTIONAL")
            ),
            accounts_master_key=(
                _clean(env.get("ACCOUNTS_MASTER_KEY")) or None
            ),
        )


@dataclass(frozen=True)
class LiveOrderPlan:
    account_name: str
    wallet_masked: str
    signature_type: int
    rule_id: int | str | None
    rule_key: str
    condition_id: str
    question: str
    side: str
    outcome: str
    token_id: str
    quantity: Decimal
    limit_price: Decimal
    notional: Decimal
    best_bid: Decimal | None
    best_ask: Decimal | None
    last_trade_price: Decimal | None
    tick_size: Decimal
    minimum_order_size: Decimal
    post_only: bool
    time_in_force: str
    blockers: tuple[str, ...]

    @property
    def ready_to_apply(self) -> bool:
        return not self.blockers


def build_live_order_plan(
    *,
    account: TradingAccountRecord,
    rule_id: int | str | None,
    rule_key: str,
    quantity: Decimal,
    limit_price: Decimal,
    snapshot: MarketSnapshot,
    settings: LiveSafetySettings,
) -> LiveOrderPlan:
    qty = Decimal(str(quantity))
    price = Decimal(str(limit_price))
    notional = qty * price
    blockers: list[str] = []

    if not settings.trading_enabled:
        blockers.append("live_trading_disabled")
    if not settings.post_only:
        blockers.append("post_only_must_be_enabled")
    if not settings.allowed_account:
        blockers.append("allowed_account_not_configured")
    elif (
        settings.allowed_account.casefold()
        != account.name.casefold()
    ):
        blockers.append("account_not_allowed")
    if settings.max_order_quantity is None:
        blockers.append("max_order_qty_not_configured")
    elif qty > settings.max_order_quantity:
        blockers.append("max_order_qty_exceeded")
    if settings.max_notional is None:
        blockers.append("max_notional_not_configured")
    elif notional > settings.max_notional:
        blockers.append("max_notional_exceeded")
    if not settings.accounts_master_key:
        blockers.append("accounts_master_key_missing")
    if qty <= 0:
        blockers.append("invalid_order_quantity")
    elif qty < snapshot.minimum_order_size:
        blockers.append("below_market_minimum_order_size")
    if price <= 0 or price >= 1:
        blockers.append("invalid_limit_price")
    elif not _is_tick_aligned(price, snapshot.tick_size):
        blockers.append("limit_price_not_tick_aligned")
    if snapshot.would_cross_buy(price):
        blockers.append("buy_would_cross_current_ask")

    return LiveOrderPlan(
        account_name=account.name,
        wallet_masked=account.wallet_masked,
        signature_type=account.signature_type,
        rule_id=rule_id,
        rule_key=str(rule_key or ""),
        condition_id=snapshot.condition_id,
        question=snapshot.question,
        side="BUY",
        outcome=snapshot.outcome,
        token_id=snapshot.token_id,
        quantity=qty,
        limit_price=price,
        notional=notional,
        best_bid=snapshot.best_bid,
        best_ask=snapshot.best_ask,
        last_trade_price=snapshot.last_trade_price,
        tick_size=snapshot.tick_size,
        minimum_order_size=snapshot.minimum_order_size,
        post_only=True,
        time_in_force="GTC",
        blockers=tuple(blockers),
    )


def _is_tick_aligned(price: Decimal, tick_size: Decimal) -> bool:
    if tick_size <= 0:
        return False
    return price % tick_size == 0


def _parse_bool(value: str | None, *, default: bool) -> bool:
    normalized = _clean(value).lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _optional_decimal(value: str | None) -> Decimal | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc
    return parsed


def _clean(value: str | None) -> str:
    cleaned = str(value or "").strip().rstrip("\\").strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned
