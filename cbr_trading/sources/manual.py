from __future__ import annotations

from typing import Sequence

from cbr_trading.domain.signals import ResolutionSignal


class ManualResolutionSource:
    """Emit an explicitly supplied signal once for controlled verification."""

    def __init__(
        self,
        *,
        source_name: str,
        signals: Sequence[ResolutionSignal],
    ):
        normalized_source = str(source_name or "").strip()
        if not normalized_source:
            raise ValueError("source_name is required")
        normalized_signals = tuple(signals)
        if any(
            not isinstance(signal, ResolutionSignal)
            for signal in normalized_signals
        ):
            raise TypeError(
                "signals must contain only ResolutionSignal objects"
            )
        if any(
            signal.source.casefold()
            != normalized_source.casefold()
            for signal in normalized_signals
        ):
            raise ValueError("manual signal source mismatch")
        signal_ids = [signal.signal_id for signal in normalized_signals]
        if len(signal_ids) != len(set(signal_ids)):
            raise ValueError("manual signal ids must be unique")

        self.source_name = normalized_source
        self._signals = normalized_signals
        self._emitted = False

    def poll_once(self) -> tuple[ResolutionSignal, ...]:
        if self._emitted:
            return ()
        self._emitted = True
        return self._signals
