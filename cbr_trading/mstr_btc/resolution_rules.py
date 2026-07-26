from __future__ import annotations

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
