from __future__ import annotations

import unittest
from decimal import Decimal

from cbr_trading.domain import (
    OrderSide,
    OrderTemplate,
    Outcome,
)
from cbr_trading.execution.selection_safety import (
    maximum_selected_notional,
)


def _template(
    template_id: str,
    *,
    scope_id: str | None,
) -> OrderTemplate:
    metadata = (
        {"production_scope_id": scope_id}
        if scope_id is not None
        else {}
    )
    return OrderTemplate(
        template_id=template_id,
        strategy_id="test",
        account_name="account",
        condition_id="0x" + ("1" * 64),
        outcome=(
            Outcome.YES if template_id.endswith("YES") else Outcome.NO
        ),
        side=OrderSide.BUY,
        desired_price=Decimal("0.9"),
        quantity=Decimal("5"),
        metadata=metadata,
    )


class PreparedSelectionSafetyTests(unittest.TestCase):
    def test_uses_maximum_of_mutually_exclusive_outcomes(self) -> None:
        rows = (
            (_template("a:YES", scope_id="scope-a"), Decimal("4.5")),
            (_template("a:NO", scope_id="scope-a"), Decimal("4.0")),
            (_template("b:YES", scope_id="scope-b"), Decimal("3.0")),
            (_template("b:NO", scope_id="scope-b"), Decimal("4.5")),
        )

        self.assertEqual(
            maximum_selected_notional(rows),
            Decimal("9.0"),
        )

    def test_templates_without_group_remain_additive(self) -> None:
        rows = (
            (_template("a:YES", scope_id=None), Decimal("4.5")),
            (_template("a:NO", scope_id=None), Decimal("4.0")),
        )

        self.assertEqual(
            maximum_selected_notional(rows),
            Decimal("8.5"),
        )


if __name__ == "__main__":
    unittest.main()
