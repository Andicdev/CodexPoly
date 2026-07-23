"""Autonomous Bank of Russia release detection package."""

from cbr_trading.client import (
    CbrClient,
    CbrClientConfig,
    DiscoveryResult,
    FetchResult,
    RequestsTransport,
)
from cbr_trading.db_config import (
    DatabaseSelection,
    resolve_admin_database_selection,
    resolve_database_selection,
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
from cbr_trading.rule_repository import (
    CBR_CHANGE_METRIC,
    CBR_EXECUTION_PATH,
    CBR_TICKER,
    RuleLoadError,
    SqlAlchemyRuleRepository,
    normalize_rule_rows,
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
    "CBR_CHANGE_METRIC",
    "CBR_EXECUTION_PATH",
    "CBR_TICKER",
    "DEFAULT_RELEASE_TIME_SUFFIX",
    "DatabaseSelection",
    "DiscoveryResult",
    "DryRunOrderExecutor",
    "FetchResult",
    "OrderExecutionResult",
    "OrderIntent",
    "PipelineOutcome",
    "RequestsTransport",
    "RuleLoadError",
    "RuleEvaluation",
    "SqlAlchemyRuleRepository",
    "TradingPipeline",
    "build_predicted_release_url",
    "build_order_intent",
    "classify_change",
    "compare",
    "evaluate_rule",
    "evaluate_rules",
    "extract_title",
    "looks_like_key_rate_release",
    "normalize_rule_rows",
    "parse_datetime",
    "parse_release_rate_from_title",
    "resolve_order_price",
    "resolve_admin_database_selection",
    "resolve_database_selection",
]
