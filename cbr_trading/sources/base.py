from __future__ import annotations

from typing import Protocol, Sequence

from cbr_trading.domain.signals import ResolutionSignal


class Source(Protocol):
    """One polling iteration may emit zero, one, or multiple deduplicated signals."""

    source_name: str

    def poll_once(self) -> Sequence[ResolutionSignal]: ...
