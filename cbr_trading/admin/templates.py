from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from cbr_trading.admin.market_resolver import EventMarketSet
from cbr_trading.rule_repository import CBR_CHANGE_METRIC


@dataclass(frozen=True)
class RuleTemplateConfig:
    account_name: str
    order_qty: float
    order_price_yes: float = 0.99
    order_price_no: float = 0.99
    increase_price_yes: float | None = None
    increase_price_no: float | None = None
    telegram_chat_id: str | None = None
    status: str = "active"

    def validate(self) -> None:
        if not self.account_name.strip():
            raise ValueError("account_name is required")
        if self.order_qty <= 0:
            raise ValueError("order_qty must be positive")
        for name, price in (
            ("order_price_yes", self.order_price_yes),
            ("order_price_no", self.order_price_no),
            ("increase_price_yes", self.increase_price_yes),
            ("increase_price_no", self.increase_price_no),
        ):
            if price is not None and not 0 < float(price) < 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.status not in {"active", "inactive"}:
            raise ValueError("status must be active or inactive")


@dataclass(frozen=True)
class RuleDraft:
    type: str
    ticker: str
    rule_key: str
    status: str
    priority: int
    tg_chat_id: str | None
    account_name: str
    condition_id: str
    question: str
    order_qty: float
    order_price: float
    params: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


def build_three_way_rule_drafts(
    markets: EventMarketSet,
    config: RuleTemplateConfig,
) -> list[RuleDraft]:
    config.validate()
    by_direction = markets.by_direction()

    specs = (
        ("decrease", "<", 0.0, 300),
        ("no_change", "==", 0.0, 301),
        ("increase", ">", 0.0, 302),
    )
    drafts: list[RuleDraft] = []
    for direction, operator, threshold, priority in specs:
        market = by_direction[direction]
        yes_price, no_price = _prices_for_direction(
            direction,
            config,
        )
        drafts.append(
            RuleDraft(
                type="cbr_key_rate",
                ticker="CBR",
                rule_key=f"cbr_{direction}_fast",
                status=config.status,
                priority=priority,
                tg_chat_id=config.telegram_chat_id,
                account_name=config.account_name.strip(),
                condition_id=market.condition_id,
                question=market.question,
                order_qty=float(config.order_qty),
                order_price=yes_price,
                params={
                    "metric_key": CBR_CHANGE_METRIC,
                    "cmp": operator,
                    "threshold": threshold,
                    "execution_path": "fast",
                    "decision_mode": "binary_yes_no",
                    "order_price_yes": yes_price,
                    "order_price_no": no_price,
                    "event_slug": markets.event_slug,
                    "market_slug": market.slug,
                },
            )
        )
    return drafts


def _prices_for_direction(
    direction: str,
    config: RuleTemplateConfig,
) -> tuple[float, float]:
    yes_price = float(config.order_price_yes)
    no_price = float(config.order_price_no)
    if direction == "increase":
        if config.increase_price_yes is not None:
            yes_price = float(config.increase_price_yes)
        if config.increase_price_no is not None:
            no_price = float(config.increase_price_no)
    return yes_price, no_price
