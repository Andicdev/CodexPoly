from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from cbr_trading.domain.intents import OrderTemplate


def template_selection_group(template: OrderTemplate) -> str:
    """Return the mutually-exclusive preparation group for a template."""

    configured = str(
        template.metadata.get("production_scope_id") or ""
    ).strip()
    return configured or template.template_id


def maximum_selected_notional(
    rows: Iterable[tuple[OrderTemplate, Decimal]],
) -> Decimal:
    """Calculate worst selected notional, not all prepared alternatives."""

    maxima: dict[tuple[str, str], Decimal] = {}
    for template, raw_notional in rows:
        notional = Decimal(str(raw_notional))
        if notional < 0 or not notional.is_finite():
            raise ValueError(
                "prepared notional must be finite and nonnegative"
            )
        key = (
            template.account_name.casefold(),
            template_selection_group(template).casefold(),
        )
        maxima[key] = max(
            maxima.get(key, Decimal("0")),
            notional,
        )
    return sum(maxima.values(), Decimal("0"))
