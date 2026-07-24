"""Typed earnings ingestion, parsing, and shadow resolution components."""

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EarningsParseResult,
    EarningsProvider,
    EpsBasis,
    ParseStatus,
    SourceAuthority,
    earnings_scope_id,
)
from cbr_trading.earnings.repository import (
    EarningsStoreError,
    SqlAlchemyEarningsStore,
    StoredEarningsRecord,
)
from cbr_trading.earnings.settings import EarningsWorkerSettings

__all__ = [
    "EarningsDocumentCandidate",
    "EarningsFactCandidate",
    "EarningsMarketRule",
    "EarningsMetric",
    "EarningsParseResult",
    "EarningsProvider",
    "EarningsStoreError",
    "EarningsWorkerSettings",
    "EpsBasis",
    "ParseStatus",
    "SourceAuthority",
    "SqlAlchemyEarningsStore",
    "StoredEarningsRecord",
    "earnings_scope_id",
]
