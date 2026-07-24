"""Source adapters that emit source-neutral resolution signals."""

from cbr_trading.sources.base import Source
from cbr_trading.sources.cbr import (
    CBR_KEY_RATE_SUBJECT,
    CBR_KEY_RATE_TARGET_METRIC,
    CBR_SOURCE_NAME,
    CbrResolutionSource,
    cbr_signal_id_for_url,
    resolution_signal_from_discovery,
)
from cbr_trading.sources.earnings import (
    EARNINGS_NON_GAAP_EPS_METRIC,
    EARNINGS_SOURCE_NAME,
    EarningsResolutionSource,
    resolution_signal_from_earnings_fact,
)
from cbr_trading.sources.manual import ManualResolutionSource

__all__ = [
    "CBR_KEY_RATE_SUBJECT",
    "CBR_KEY_RATE_TARGET_METRIC",
    "CBR_SOURCE_NAME",
    "CbrResolutionSource",
    "EARNINGS_NON_GAAP_EPS_METRIC",
    "EARNINGS_SOURCE_NAME",
    "EarningsResolutionSource",
    "ManualResolutionSource",
    "Source",
    "cbr_signal_id_for_url",
    "resolution_signal_from_discovery",
    "resolution_signal_from_earnings_fact",
]
