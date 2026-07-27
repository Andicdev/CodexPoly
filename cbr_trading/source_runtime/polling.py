from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EnabledProfileStore(Protocol):
    def load_enabled(
        self,
        *,
        source_name: str | None = None,
    ) -> Sequence[object]: ...


class ProfileWindowPollingGate:
    """Enable an external poller only while a trading profile is active."""

    def __init__(
        self,
        *,
        profile_store: EnabledProfileStore,
        source_name: str,
    ):
        normalized_source = str(source_name or "").strip()
        if not normalized_source:
            raise ValueError("source_name is required")
        self._profile_store = profile_store
        self.source_name = normalized_source

    def active_profile_count(self) -> int:
        return len(
            tuple(
                self._profile_store.load_enabled(
                    source_name=self.source_name,
                )
            )
        )

    def is_active(self) -> bool:
        return self.active_profile_count() > 0
