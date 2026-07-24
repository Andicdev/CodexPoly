"""Pure strategies that map resolution signals to order intents."""

from cbr_trading.strategies.base import Strategy
from cbr_trading.strategies.cbr_rate_decision import (
    CBR_RATE_DECISION_STRATEGY_ID,
    CbrRateDecisionStrategy,
    CbrStrategyConfigurationError,
    CbrStrategyDecision,
)

__all__ = [
    "CBR_RATE_DECISION_STRATEGY_ID",
    "CbrRateDecisionStrategy",
    "CbrStrategyConfigurationError",
    "CbrStrategyDecision",
    "Strategy",
]
