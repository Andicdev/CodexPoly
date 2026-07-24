"""Source adapters that emit source-neutral resolution signals."""

from cbr_trading.sources.base import Source
from cbr_trading.sources.cbr import (
    CBR_KEY_RATE_SUBJECT,
    CBR_KEY_RATE_TARGET_METRIC,
    CBR_SOURCE_NAME,
    CbrResolutionSource,
    resolution_signal_from_discovery,
)

__all__ = [
    "CBR_KEY_RATE_SUBJECT",
    "CBR_KEY_RATE_TARGET_METRIC",
    "CBR_SOURCE_NAME",
    "CbrResolutionSource",
    "Source",
    "resolution_signal_from_discovery",
]
