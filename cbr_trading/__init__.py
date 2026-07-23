"""Autonomous Bank of Russia release detection package."""

from cbr_trading.client import (
    CbrClient,
    CbrClientConfig,
    DiscoveryResult,
    FetchResult,
    RequestsTransport,
)
from cbr_trading.release import (
    DEFAULT_RELEASE_TIME_SUFFIX,
    build_predicted_release_url,
    classify_change,
    extract_title,
    looks_like_key_rate_release,
    parse_datetime,
    parse_release_rate_from_title,
)
from cbr_trading.pipeline import (
    DryRunOrderExecutor,
    OrderExecutionResult,
    OrderIntent,
    PipelineOutcome,
    TradingPipeline,
    build_order_intent,
)
from cbr_trading.trading_rules import (
    RuleEvaluation,
    compare,
    evaluate_rule,
    evaluate_rules,
    resolve_order_price,
)

__all__ = [
    "CbrClient",
    "CbrClientConfig",
    "DEFAULT_RELEASE_TIME_SUFFIX",
    "DiscoveryResult",
    "DryRunOrderExecutor",
    "FetchResult",
    "OrderExecutionResult",
    "OrderIntent",
    "PipelineOutcome",
    "RequestsTransport",
    "RuleEvaluation",
    "TradingPipeline",
    "build_predicted_release_url",
    "build_order_intent",
    "classify_change",
    "compare",
    "evaluate_rule",
    "evaluate_rules",
    "extract_title",
    "looks_like_key_rate_release",
    "parse_datetime",
    "parse_release_rate_from_title",
    "resolve_order_price",
]
