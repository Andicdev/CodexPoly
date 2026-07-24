from __future__ import annotations

from typing import Protocol, Sequence

from cbr_trading.domain.intents import OrderIntent, OrderTemplate
from cbr_trading.domain.signals import ResolutionSignal


class Strategy(Protocol):
    """A strategy exposes preparable alternatives and selects them after a signal."""

    strategy_id: str

    def order_templates(self) -> Sequence[OrderTemplate]: ...

    def evaluate(self, signal: ResolutionSignal) -> Sequence[OrderIntent]: ...
