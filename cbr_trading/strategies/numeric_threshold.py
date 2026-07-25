from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from cbr_trading.domain.intents import OrderIntent, OrderTemplate, Outcome
from cbr_trading.domain.signals import ResolutionSignal


NUMERIC_THRESHOLD_STRATEGY_ID = "numeric_threshold"


class NumericThresholdConfigurationError(ValueError):
    """Invalid source-neutral numeric threshold strategy configuration."""


@dataclass(frozen=True)
class NumericThresholdRule:
    rule_key: str
    source: str
    subject: str
    metric: str
    comparison_op: str
    strike: Decimal
    rounding_places: int
    yes_template: OrderTemplate
    no_template: OrderTemplate

    def __post_init__(self) -> None:
        for name in ("rule_key", "source", "subject", "metric"):
            normalized = str(getattr(self, name) or "").strip()
            if not normalized:
                raise NumericThresholdConfigurationError(
                    f"{name} is required"
                )
            object.__setattr__(self, name, normalized)
        if self.comparison_op not in {">", ">=", "<", "<=", "=="}:
            raise NumericThresholdConfigurationError(
                "unsupported comparison_op"
            )
        strike = Decimal(str(self.strike))
        if not strike.is_finite():
            raise NumericThresholdConfigurationError(
                "strike must be finite"
            )
        object.__setattr__(self, "strike", strike)
        places = int(self.rounding_places)
        if not 0 <= places <= 6:
            raise NumericThresholdConfigurationError(
                "rounding_places must be between 0 and 6"
            )
        object.__setattr__(self, "rounding_places", places)
        _validate_template(
            self.yes_template,
            expected_outcome=Outcome.YES,
        )
        _validate_template(
            self.no_template,
            expected_outcome=Outcome.NO,
        )
        if (
            self.yes_template.template_id
            == self.no_template.template_id
        ):
            raise NumericThresholdConfigurationError(
                "YES and NO template ids must be different"
            )


class NumericThresholdStrategy:
    """Choose YES or NO after comparing a rounded numeric resolution fact."""

    strategy_id = NUMERIC_THRESHOLD_STRATEGY_ID

    def __init__(self, rules: Sequence[NumericThresholdRule]):
        self._rules = tuple(rules)
        if not self._rules:
            raise NumericThresholdConfigurationError(
                "at least one numeric threshold rule is required"
            )
        if any(
            not isinstance(rule, NumericThresholdRule)
            for rule in self._rules
        ):
            raise TypeError(
                "rules must contain only NumericThresholdRule objects"
            )
        keys = [rule.rule_key for rule in self._rules]
        if len(keys) != len(set(keys)):
            raise NumericThresholdConfigurationError(
                "numeric threshold rule keys must be unique"
            )
        template_ids = [
            template.template_id
            for rule in self._rules
            for template in (rule.yes_template, rule.no_template)
        ]
        if len(template_ids) != len(set(template_ids)):
            raise NumericThresholdConfigurationError(
                "numeric threshold template ids must be unique"
            )

    def order_templates(self) -> tuple[OrderTemplate, ...]:
        return tuple(
            template
            for rule in self._rules
            for template in (rule.yes_template, rule.no_template)
        )

    def evaluate(
        self,
        signal: ResolutionSignal,
    ) -> tuple[OrderIntent, ...]:
        selected: list[OrderIntent] = []
        for rule in self._rules:
            if not _matches_signal(rule, signal):
                continue
            value = _numeric_signal_value(signal.value)
            if value is None:
                continue
            rounded_value = _round(value, rule.rounding_places)
            rounded_strike = _round(
                rule.strike,
                rule.rounding_places,
            )
            template = (
                rule.yes_template
                if _compare(
                    rounded_value,
                    rule.comparison_op,
                    rounded_strike,
                )
                else rule.no_template
            )
            selected.append(
                template.bind(signal_id=signal.signal_id)
            )
        return tuple(selected)


def _validate_template(
    template: OrderTemplate,
    *,
    expected_outcome: Outcome,
) -> None:
    if not isinstance(template, OrderTemplate):
        raise TypeError("threshold templates must be OrderTemplate objects")
    if template.strategy_id != NUMERIC_THRESHOLD_STRATEGY_ID:
        raise NumericThresholdConfigurationError(
            "threshold template strategy_id is invalid"
        )
    if template.outcome is not expected_outcome:
        raise NumericThresholdConfigurationError(
            f"threshold template must target {expected_outcome.value}"
        )


def _matches_signal(
    rule: NumericThresholdRule,
    signal: ResolutionSignal,
) -> bool:
    return (
        signal.source.casefold() == rule.source.casefold()
        and signal.subject.casefold() == rule.subject.casefold()
        and signal.metric.casefold() == rule.metric.casefold()
    )


def _numeric_signal_value(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = Decimal(str(value))
    else:
        return None
    return parsed if parsed.is_finite() else None


def _round(value: Decimal, places: int) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _compare(
    value: Decimal,
    operation: str,
    strike: Decimal,
) -> bool:
    if operation == ">":
        return value > strike
    if operation == ">=":
        return value >= strike
    if operation == "<":
        return value < strike
    if operation == "<=":
        return value <= strike
    if operation == "==":
        return value == strike
    raise NumericThresholdConfigurationError(
        "unsupported comparison_op"
    )
