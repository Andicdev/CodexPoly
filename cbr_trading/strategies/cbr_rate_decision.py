from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from cbr_trading.domain.intents import (
    KeepOpenPolicy,
    OrderIntent,
    OrderLifecyclePolicy,
    OrderSide,
    OrderTemplate,
    Outcome,
    RepriceOnTickChange,
)
from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.release import classify_change
from cbr_trading.sources.cbr import (
    CBR_KEY_RATE_SUBJECT,
    CBR_KEY_RATE_TARGET_METRIC,
)
from cbr_trading.trading_rules import (
    RuleEvaluation,
    evaluate_rules,
    resolve_order_price,
)


CBR_RATE_DECISION_STRATEGY_ID = "cbr.key_rate_decision.v1"


class CbrStrategyConfigurationError(ValueError):
    """A CBR subscription cannot be represented by a valid order template."""


@dataclass(frozen=True)
class CbrStrategyDecision:
    accepted: bool
    reason: str
    change_bps: Decimal | None
    direction: str | None
    evaluations: tuple[RuleEvaluation, ...]
    intents: tuple[OrderIntent, ...]


class CbrRateDecisionStrategy:
    """Preserve tested CBR rule semantics behind the universal Strategy contract."""

    strategy_id = CBR_RATE_DECISION_STRATEGY_ID

    def __init__(self, subscriptions: Sequence[Mapping[str, Any]]):
        self._subscriptions = tuple(dict(row) for row in subscriptions)
        self._templates = _build_templates(self._subscriptions)
        self._templates_by_key = {
            _template_lookup_key(template.template_id): template
            for template in self._templates
        }

    def order_templates(self) -> tuple[OrderTemplate, ...]:
        return self._templates

    def evaluate(self, signal: ResolutionSignal) -> tuple[OrderIntent, ...]:
        return self.evaluate_decision(signal).intents

    def evaluate_decision(
        self,
        signal: ResolutionSignal,
    ) -> CbrStrategyDecision:
        if (
            signal.subject != CBR_KEY_RATE_SUBJECT
            or signal.metric != CBR_KEY_RATE_TARGET_METRIC
        ):
            return CbrStrategyDecision(
                accepted=False,
                reason="unsupported_signal",
                change_bps=None,
                direction=None,
                evaluations=(),
                intents=(),
            )

        current_rate = _numeric_signal_value(signal.value)
        previous_rate = _numeric_signal_value(signal.previous_value)
        if current_rate is None:
            return CbrStrategyDecision(
                accepted=False,
                reason="invalid_signal_value",
                change_bps=None,
                direction=None,
                evaluations=(),
                intents=(),
            )
        if previous_rate is None:
            return CbrStrategyDecision(
                accepted=True,
                reason="previous_rate_unavailable",
                change_bps=None,
                direction=None,
                evaluations=(),
                intents=(),
            )
        change_bps, direction = classify_change(
            float(previous_rate),
            float(current_rate),
        )
        if change_bps is None:
            return CbrStrategyDecision(
                accepted=True,
                reason="change_unavailable",
                change_bps=None,
                direction=direction,
                evaluations=(),
                intents=(),
            )

        evaluations = tuple(
            evaluate_rules(change_bps, self._subscriptions)
        )
        intents: list[OrderIntent] = []
        for subscription, evaluation in zip(
            self._subscriptions,
            evaluations,
            strict=True,
        ):
            if not evaluation.should_trade or not evaluation.action:
                continue
            template_id = _template_id(
                subscription,
                evaluation.action,
            )
            template = self._templates_by_key.get(
                _template_lookup_key(template_id)
            )
            if template is None:
                raise CbrStrategyConfigurationError(
                    f"prepared template is missing for {template_id}"
                )
            intents.append(template.bind(signal_id=signal.signal_id))

        return CbrStrategyDecision(
            accepted=True,
            reason="evaluated",
            change_bps=Decimal(str(change_bps)),
            direction=direction,
            evaluations=evaluations,
            intents=tuple(intents),
        )


def _build_templates(
    subscriptions: Sequence[Mapping[str, Any]],
) -> tuple[OrderTemplate, ...]:
    templates: list[OrderTemplate] = []
    seen_ids: set[str] = set()
    for subscription in subscriptions:
        account_name = str(
            subscription.get("account_name") or ""
        ).strip()
        condition_id = str(
            subscription.get("condition_id") or ""
        ).strip()
        quantity = _required_decimal(
            subscription.get("order_qty"),
            name="order_qty",
            subscription=subscription,
        )
        lifecycle_policy = _lifecycle_policy(subscription)

        for action in ("YES", "NO"):
            template_id = _template_id(subscription, action)
            if template_id.casefold() in seen_ids:
                raise CbrStrategyConfigurationError(
                    f"duplicate CBR template id: {template_id}"
                )
            seen_ids.add(template_id.casefold())

            price = _required_decimal(
                resolve_order_price(subscription, action),
                name=f"{action} order price",
                subscription=subscription,
            )
            try:
                templates.append(
                    OrderTemplate(
                        template_id=template_id,
                        strategy_id=CBR_RATE_DECISION_STRATEGY_ID,
                        account_name=account_name,
                        condition_id=condition_id,
                        outcome=Outcome(action),
                        side=OrderSide.BUY,
                        desired_price=price,
                        quantity=quantity,
                        lifecycle_policy=lifecycle_policy,
                        metadata={
                            "legacy_rule_id": subscription.get("id"),
                            "rule_key": str(
                                subscription.get("rule_key") or "default"
                            ),
                        },
                    )
                )
            except (TypeError, ValueError) as exc:
                raise CbrStrategyConfigurationError(
                    f"invalid CBR rule {_rule_identity(subscription)}: {exc}"
                ) from exc

    return tuple(templates)


def _lifecycle_policy(
    subscription: Mapping[str, Any],
) -> OrderLifecyclePolicy:
    params = subscription.get("params")
    if not isinstance(params, Mapping):
        return KeepOpenPolicy()
    raw_policy = params.get("order_lifecycle")
    if raw_policy is None:
        return KeepOpenPolicy()
    if not isinstance(raw_policy, Mapping):
        raise CbrStrategyConfigurationError(
            f"invalid order_lifecycle for rule {_rule_identity(subscription)}"
        )

    kind = str(raw_policy.get("kind") or "keep_open").strip().lower()
    if kind == "keep_open":
        return KeepOpenPolicy()
    if kind != "reprice_on_tick_change":
        raise CbrStrategyConfigurationError(
            f"unsupported order_lifecycle kind: {kind}"
        )
    try:
        return RepriceOnTickChange(
            old_tick=Decimal(str(raw_policy.get("old_tick"))),
            new_tick=Decimal(str(raw_policy.get("new_tick"))),
            max_reprices=int(raw_policy.get("max_reprices") or 1),
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CbrStrategyConfigurationError(
            f"invalid tick lifecycle for rule {_rule_identity(subscription)}"
        ) from exc


def _template_id(
    subscription: Mapping[str, Any],
    action: str,
) -> str:
    return f"cbr-rule:{_rule_identity(subscription)}:{action.upper()}"


def _template_lookup_key(template_id: str) -> str:
    return template_id.casefold()


def _rule_identity(subscription: Mapping[str, Any]) -> str:
    rule_id = subscription.get("id")
    if rule_id is not None and str(rule_id).strip():
        return str(rule_id).strip()
    rule_key = str(subscription.get("rule_key") or "").strip()
    if rule_key:
        return rule_key
    raise CbrStrategyConfigurationError(
        "CBR subscription requires id or rule_key"
    )


def _required_decimal(
    value: Any,
    *,
    name: str,
    subscription: Mapping[str, Any],
) -> Decimal:
    try:
        result = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CbrStrategyConfigurationError(
            f"invalid {name} for rule {_rule_identity(subscription)}"
        ) from exc
    if result <= 0:
        raise CbrStrategyConfigurationError(
            f"invalid {name} for rule {_rule_identity(subscription)}"
        )
    return result


def _numeric_signal_value(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
