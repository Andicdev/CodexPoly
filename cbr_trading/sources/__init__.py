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
from cbr_trading.sources.mstr_btc import (
    MSTR_BTC_ACQUIRED_METRIC,
    MSTR_BTC_SOLD_METRIC,
    MSTR_BTC_SOURCE_NAME,
    MstrBtcResolutionSource,
    resolution_signal_from_mstr_btc_fact,
)

__all__ = [
    "CBR_KEY_RATE_SUBJECT",
    "CBR_KEY_RATE_TARGET_METRIC",
    "CBR_SOURCE_NAME",
    "CbrResolutionSource",
    "EARNINGS_NON_GAAP_EPS_METRIC",
    "EARNINGS_SOURCE_NAME",
    "EarningsResolutionSource",
    "ManualResolutionSource",
    "MSTR_BTC_ACQUIRED_METRIC",
    "MSTR_BTC_SOLD_METRIC",
    "MSTR_BTC_SOURCE_NAME",
    "MstrBtcResolutionSource",
    "Source",
    "cbr_signal_id_for_url",
    "resolution_signal_from_discovery",
    "resolution_signal_from_earnings_fact",
    "resolution_signal_from_mstr_btc_fact",
]
