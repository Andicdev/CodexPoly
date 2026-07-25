"""Pure strategies that map resolution signals to order intents."""

from cbr_trading.strategies.base import Strategy
from cbr_trading.strategies.cbr_rate_decision import (
    CBR_RATE_DECISION_STRATEGY_ID,
    CbrRateDecisionStrategy,
    CbrStrategyConfigurationError,
    CbrStrategyDecision,
)
from cbr_trading.strategies.fixed_outcome import (
    FIXED_OUTCOME_STRATEGY_ID,
    FixedOutcomeConfigurationError,
    FixedOutcomeStrategy,
)
from cbr_trading.strategies.numeric_threshold import (
    NUMERIC_THRESHOLD_STRATEGY_ID,
    NumericThresholdConfigurationError,
    NumericThresholdRule,
    NumericThresholdStrategy,
)

__all__ = [
    "CBR_RATE_DECISION_STRATEGY_ID",
    "CbrRateDecisionStrategy",
    "CbrStrategyConfigurationError",
    "CbrStrategyDecision",
    "FIXED_OUTCOME_STRATEGY_ID",
    "FixedOutcomeConfigurationError",
    "FixedOutcomeStrategy",
    "NUMERIC_THRESHOLD_STRATEGY_ID",
    "NumericThresholdConfigurationError",
    "NumericThresholdRule",
    "NumericThresholdStrategy",
    "Strategy",
]
