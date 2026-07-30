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
from cbr_trading.domain.signals import ResolutionSignal, SignalValue


FIXED_OUTCOME_STRATEGY_ID = "fixed_outcome"


class FixedOutcomeConfigurationError(ValueError):
    """Invalid source-neutral fixed-outcome rule configuration."""


@dataclass(frozen=True)
class _FixedRule:
    source: str
    subject: str
    metric: str
    expected_value: SignalValue
    template: OrderTemplate


class FixedOutcomeStrategy:
    """Bind one configured BUY outcome when an exact signal fact matches."""

    strategy_id = FIXED_OUTCOME_STRATEGY_ID

    def __init__(self, rules: Sequence[Mapping[str, Any]]):
        self._rules = tuple(_parse_rule(rule) for rule in rules)
        if not self._rules:
            raise FixedOutcomeConfigurationError(
                "At least one fixed-outcome rule is required"
            )
        template_ids = [
            rule.template.template_id
            for rule in self._rules
        ]
        if len(template_ids) != len(set(template_ids)):
            raise FixedOutcomeConfigurationError(
                "Fixed-outcome template ids must be unique"
            )

    def order_templates(self) -> tuple[OrderTemplate, ...]:
        return tuple(rule.template for rule in self._rules)

    def evaluate(
        self,
        signal: ResolutionSignal,
    ) -> tuple[OrderIntent, ...]:
        selected: list[OrderIntent] = []
        for rule in self._rules:
            if not _matches_signal(rule, signal):
                continue
            selected.append(
                rule.template.bind(signal_id=signal.signal_id)
            )
        return tuple(selected)


def _parse_rule(rule: Mapping[str, Any]) -> _FixedRule:
    params = rule.get("params")
    if not isinstance(params, Mapping):
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} has invalid params"
        )
    if (
        str(params.get("decision_mode") or "").strip().lower()
        != FIXED_OUTCOME_STRATEGY_ID
    ):
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} is not fixed_outcome"
        )

    source = _required_text(params.get("source"), "source", rule)
    subject = _required_text(params.get("subject"), "subject", rule)
    metric = _required_text(params.get("metric"), "metric", rule)
    if "signal_value" not in params:
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} is missing signal_value"
        )
    expected_value = _signal_value(
        params["signal_value"],
        rule=rule,
    )
    try:
        outcome = Outcome(
            str(params.get("action") or "").strip().upper()
        )
    except ValueError as exc:
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} has invalid action"
        ) from exc

    price_key = f"order_price_{outcome.value.lower()}"
    desired_price = _required_decimal(
        params.get(price_key, rule.get("order_price")),
        name=price_key,
        rule=rule,
    )
    quantity = _required_decimal(
        rule.get("order_qty"),
        name="order_qty",
        rule=rule,
    )
    rule_id = _rule_identity(rule)
    rule_key = str(rule.get("rule_key") or "default").strip()
    try:
        template = OrderTemplate(
            template_id=(
                f"fixed-outcome-rule:{rule_id}:{outcome.value}"
            ),
            strategy_id=FIXED_OUTCOME_STRATEGY_ID,
            account_name=_required_text(
                rule.get("account_name"),
                "account_name",
                rule,
            ),
            condition_id=_required_text(
                rule.get("condition_id"),
                "condition_id",
                rule,
            ),
            outcome=outcome,
            side=OrderSide.BUY,
            desired_price=desired_price,
            quantity=quantity,
            lifecycle_policy=_lifecycle_policy(params, rule=rule),
            metadata={
                "rule_id": rule.get("id"),
                "rule_key": rule_key,
                "type": str(rule.get("type") or ""),
                "ticker": str(rule.get("ticker") or ""),
            },
        )
    except (TypeError, ValueError) as exc:
        raise FixedOutcomeConfigurationError(
            f"Rule {rule_id} has an invalid order template: {exc}"
        ) from exc
    return _FixedRule(
        source=source,
        subject=subject,
        metric=metric,
        expected_value=expected_value,
        template=template,
    )


def _lifecycle_policy(
    params: Mapping[str, Any],
    *,
    rule: Mapping[str, Any],
) -> OrderLifecyclePolicy:
    raw = params.get("order_lifecycle")
    if raw is None:
        return KeepOpenPolicy()
    if not isinstance(raw, Mapping):
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} has invalid order_lifecycle"
        )
    kind = str(raw.get("kind") or "keep_open").strip().lower()
    if kind == "keep_open":
        return KeepOpenPolicy()
    if kind != "reprice_on_tick_change":
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} has unsupported lifecycle"
        )
    try:
        return RepriceOnTickChange(
            old_tick=_required_decimal(
                raw.get("old_tick"),
                name="old_tick",
                rule=rule,
            ),
            new_tick=_required_decimal(
                raw.get("new_tick"),
                name="new_tick",
                rule=rule,
            ),
            max_reprices=int(raw.get("max_reprices") or 1),
            submit_first=_optional_bool(
                raw.get("submit_first"),
                default=True,
                name="submit_first",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} has invalid tick lifecycle"
        ) from exc


def _optional_bool(
    value: object,
    *,
    default: bool,
    name: str,
) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a bool")
    return value


def _matches_signal(
    rule: _FixedRule,
    signal: ResolutionSignal,
) -> bool:
    return (
        signal.source.casefold() == rule.source.casefold()
        and signal.subject.casefold() == rule.subject.casefold()
        and signal.metric.casefold() == rule.metric.casefold()
        and _signal_values_equal(signal.value, rule.expected_value)
    )


def _signal_values_equal(
    actual: SignalValue,
    expected: SignalValue,
) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(expected, Decimal):
        return (
            isinstance(actual, Decimal)
            and actual == expected
        )
    return (
        isinstance(actual, str)
        and actual.strip().casefold()
        == str(expected).strip().casefold()
    )


def _signal_value(
    value: Any,
    *,
    rule: Mapping[str, Any],
) -> SignalValue:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    if isinstance(value, (int, float, Decimal)):
        parsed = Decimal(str(value))
        if parsed.is_finite():
            return parsed
    raise FixedOutcomeConfigurationError(
        f"Rule {_rule_identity(rule)} has invalid signal_value"
    )


def _required_text(
    value: Any,
    name: str,
    rule: Mapping[str, Any],
) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} is missing {name}"
        )
    return normalized


def _required_decimal(
    value: Any,
    *,
    name: str,
    rule: Mapping[str, Any],
) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} has invalid {name}"
        ) from exc
    if not parsed.is_finite() or parsed <= 0:
        raise FixedOutcomeConfigurationError(
            f"Rule {_rule_identity(rule)} has invalid {name}"
        )
    return parsed


def _rule_identity(rule: Mapping[str, Any]) -> str:
    value = rule.get("id")
    if value is not None and str(value).strip():
        return str(value).strip()
    value = str(rule.get("rule_key") or "").strip()
    if value:
        return value
    return "<unknown>"
