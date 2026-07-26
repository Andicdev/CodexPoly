from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cbr_trading.mstr_btc.contracts import (
    MstrBtcActivity,
    MstrBtcResolutionRule,
)
from cbr_trading.mstr_btc.sec_router import MSTR_JUL21_27_SCOPE_ID


MSTR_PURCHASE_ANY_SIGNAL_ID = (
    f"{MSTR_JUL21_27_SCOPE_ID}:purchase-any"
)
MSTR_PURCHASE_OVER_1000_SIGNAL_ID = (
    f"{MSTR_JUL21_27_SCOPE_ID}:purchase-over-1000"
)
MSTR_SALE_ANY_SIGNAL_ID = f"{MSTR_JUL21_27_SCOPE_ID}:sale-any"


@dataclass(frozen=True)
class MstrBtcMarketBinding:
    """Checked-in Polymarket identity for one MSTR resolution rule."""

    rule_key: str
    signal_id: str
    market_slug: str
    condition_id: str

    def __post_init__(self) -> None:
        for name in ("rule_key", "signal_id", "market_slug"):
            normalized = str(getattr(self, name) or "").strip()
            if not normalized:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, normalized)
        condition_id = str(self.condition_id or "").strip().lower()
        if (
            len(condition_id) != 66
            or not condition_id.startswith("0x")
            or any(
                character not in "0123456789abcdef"
                for character in condition_id[2:]
            )
        ):
            raise ValueError("condition_id must be a 32-byte hex value")
        object.__setattr__(self, "condition_id", condition_id)

    @property
    def source_reference(self) -> str:
        return f"https://polymarket.com/event/{self.market_slug}"


def mstr_jul21_27_resolution_rules(
) -> tuple[MstrBtcResolutionRule, ...]:
    return (
        MstrBtcResolutionRule(
            rule_key="mstr-btc-jul21-27-purchase-any",
            signal_id=MSTR_PURCHASE_ANY_SIGNAL_ID,
            weekly_scope_id=MSTR_JUL21_27_SCOPE_ID,
            activity=MstrBtcActivity.ACQUIRED,
            comparison_op=">",
            threshold_btc=Decimal("0"),
        ),
        MstrBtcResolutionRule(
            rule_key="mstr-btc-jul21-27-purchase-over-1000",
            signal_id=MSTR_PURCHASE_OVER_1000_SIGNAL_ID,
            weekly_scope_id=MSTR_JUL21_27_SCOPE_ID,
            activity=MstrBtcActivity.ACQUIRED,
            comparison_op=">",
            threshold_btc=Decimal("1000"),
            explicit_boundary_tolerance_btc=1,
        ),
        MstrBtcResolutionRule(
            rule_key="mstr-btc-jul21-27-sale-any",
            signal_id=MSTR_SALE_ANY_SIGNAL_ID,
            weekly_scope_id=MSTR_JUL21_27_SCOPE_ID,
            activity=MstrBtcActivity.SOLD,
            comparison_op=">",
            threshold_btc=Decimal("0"),
        ),
    )


def mstr_jul21_27_market_bindings(
) -> tuple[MstrBtcMarketBinding, ...]:
    return (
        MstrBtcMarketBinding(
            rule_key="mstr-btc-jul21-27-purchase-any",
            signal_id=MSTR_PURCHASE_ANY_SIGNAL_ID,
            market_slug=(
                "will-microstrategy-announce-a-bitcoin-purchase-"
                "july-21-27"
            ),
            condition_id=(
                "0xa17d770b4962398a55d4b1d87e083ba986ab8fff4e8ca0c7"
                "94fc3a4d1f18051a"
            ),
        ),
        MstrBtcMarketBinding(
            rule_key="mstr-btc-jul21-27-purchase-over-1000",
            signal_id=MSTR_PURCHASE_OVER_1000_SIGNAL_ID,
            market_slug=(
                "microstrategy-announces-1000-btc-purchase-"
                "july-21-27"
            ),
            condition_id=(
                "0x53e75dd47cd2e9076955ca4e8e8827c5718dd1e9566d49d7"
                "4a831b0465501ec1"
            ),
        ),
        MstrBtcMarketBinding(
            rule_key="mstr-btc-jul21-27-sale-any",
            signal_id=MSTR_SALE_ANY_SIGNAL_ID,
            market_slug=(
                "will-microstrategy-announce-selling-any-bitcoin-"
                "july-21-27"
            ),
            condition_id=(
                "0xc937afbe3ce062c934d2922c313a8990907f1d382a55e8ee5"
                "6d36a5b0359500b"
            ),
        ),
    )
