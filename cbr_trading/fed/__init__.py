"""Federal Reserve FOMC decision source configuration and parsing."""

from cbr_trading.fed.contracts import (
    FedDecisionSpec,
    FedMarketBinding,
    FedRateBucket,
    FedRateDecision,
)
from cbr_trading.fed.july_2026 import (
    FED_JULY_2026_DECISION_ID,
    FED_JULY_2026_EVENT_SLUG,
    FED_JULY_2026_EVENT_URL,
    fed_july_2026_decision_spec,
    fed_july_2026_market_bindings,
)
from cbr_trading.fed.http_source import (
    FedDocumentKind,
    FedDocumentRoute,
    FedOfficialDocumentPoller,
    FedOfficialObservation,
    FedOfficialSourceError,
    FedRouteResponse,
    FedRouteTelemetry,
    FedRouteTransport,
    RequestsFedRouteTransport,
)
from cbr_trading.fed.parser import (
    FED_PARSER_NAME,
    FED_PARSER_VERSION,
    FedDecisionParseError,
    html_visible_text,
    parse_fomc_target_range,
)

__all__ = [
    "FED_JULY_2026_DECISION_ID",
    "FED_JULY_2026_EVENT_SLUG",
    "FED_JULY_2026_EVENT_URL",
    "FED_PARSER_NAME",
    "FED_PARSER_VERSION",
    "FedDecisionParseError",
    "FedDecisionSpec",
    "FedMarketBinding",
    "FedRateBucket",
    "FedRateDecision",
    "FedDocumentKind",
    "FedDocumentRoute",
    "FedOfficialDocumentPoller",
    "FedOfficialObservation",
    "FedOfficialSourceError",
    "FedRouteResponse",
    "FedRouteTelemetry",
    "FedRouteTransport",
    "RequestsFedRouteTransport",
    "fed_july_2026_decision_spec",
    "fed_july_2026_market_bindings",
    "html_visible_text",
    "parse_fomc_target_range",
]
