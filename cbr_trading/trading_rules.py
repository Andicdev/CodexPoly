from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class RuleEvaluation:
    rule_id: int | str | None
    rule_key: str
    value: float
    threshold: float | None
    operator: str
    passed: bool | None
    decision_mode: str
    should_trade: bool
    action: str | None
    order_price: float | None
    reason: str


def compare(value: float, threshold: float, operator: str) -> bool:
    """Apply the legacy comparison aliases; unknown operators mean >=."""
    normalized = str(operator or ">=").strip().lower()
    if normalized in {">", "gt"}:
        return value > threshold
    if normalized in {">=", "ge"}:
        return value >= threshold
    if normalized in {"<", "lt"}:
        return value < threshold
    if normalized in {"<=", "le"}:
        return value <= threshold
    if normalized in {"==", "eq"}:
        return value == threshold
    if normalized in {"!=", "ne"}:
        return value != threshold
    return value >= threshold


def evaluate_rule(
    value: float,
    subscription: Mapping[str, Any],
) -> RuleEvaluation:
    """Evaluate one legacy monitored_news-style subscription."""
    numeric_value = float(value)
    params = subscription.get("params")
    if not isinstance(params, Mapping):
        params = {}

    rule_id = subscription.get("id")
    rule_key = str(subscription.get("rule_key") or "default")
    operator = str(params.get("cmp") or ">=").strip()
    decision_mode = str(
        params.get("decision_mode") or "binary_yes_no"
    ).strip().lower()

    threshold_raw = params.get("threshold")
    if threshold_raw is None:
        return _skipped(
            rule_id=rule_id,
            rule_key=rule_key,
            value=numeric_value,
            threshold=None,
            operator=operator,
            decision_mode=decision_mode,
            reason="missing_threshold",
        )

    try:
        threshold = float(threshold_raw)
    except (TypeError, ValueError):
        return _skipped(
            rule_id=rule_id,
            rule_key=rule_key,
            value=numeric_value,
            threshold=None,
            operator=operator,
            decision_mode=decision_mode,
            reason="bad_threshold",
        )

    passed = compare(numeric_value, threshold, operator)
    action, reason = _resolve_action(
        passed=passed,
        decision_mode=decision_mode,
    )
    if action is None:
        return RuleEvaluation(
            rule_id=rule_id,
            rule_key=rule_key,
            value=numeric_value,
            threshold=threshold,
            operator=operator,
            passed=passed,
            decision_mode=decision_mode,
            should_trade=False,
            action=None,
            order_price=None,
            reason=reason,
        )

    order_price = resolve_order_price(subscription, action)
    return RuleEvaluation(
        rule_id=rule_id,
        rule_key=rule_key,
        value=numeric_value,
        threshold=threshold,
        operator=operator,
        passed=passed,
        decision_mode=decision_mode,
        should_trade=True,
        action=action,
        order_price=order_price,
        reason="decision_ready",
    )


def evaluate_rules(
    value: float,
    subscriptions: Sequence[Mapping[str, Any]],
) -> list[RuleEvaluation]:
    """Evaluate rules in their supplied priority order."""
    return [
        evaluate_rule(value, subscription)
        for subscription in subscriptions
    ]


def resolve_order_price(
    subscription: Mapping[str, Any],
    action: str,
) -> float | None:
    """Use action-specific price first, then the legacy base order_price."""
    params = subscription.get("params")
    if not isinstance(params, Mapping):
        params = {}

    normalized_action = str(action or "").strip().upper()
    action_key = (
        "order_price_yes"
        if normalized_action == "YES"
        else "order_price_no"
    )
    action_price = _float_or_none(params.get(action_key))
    if action_price is not None:
        return action_price
    return _float_or_none(subscription.get("order_price"))


def _resolve_action(
    *,
    passed: bool,
    decision_mode: str,
) -> tuple[str | None, str]:
    if decision_mode == "yes_only":
        if not passed:
            return None, "yes_only_not_passed"
        return "YES", "decision_ready"

    if decision_mode == "no_only":
        if not passed:
            return None, "no_only_not_passed"
        return "NO", "decision_ready"

    if decision_mode == "no_only_on_not_passed":
        if passed:
            return None, "no_only_on_not_passed_but_passed"
        return "NO", "decision_ready"

    if decision_mode == "binary_no_yes":
        return ("NO" if passed else "YES"), "decision_ready"

    return ("YES" if passed else "NO"), "decision_ready"


def _skipped(
    *,
    rule_id: int | str | None,
    rule_key: str,
    value: float,
    threshold: float | None,
    operator: str,
    decision_mode: str,
    reason: str,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id,
        rule_key=rule_key,
        value=value,
        threshold=threshold,
        operator=operator,
        passed=None,
        decision_mode=decision_mode,
        should_trade=False,
        action=None,
        order_price=None,
        reason=reason,
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
