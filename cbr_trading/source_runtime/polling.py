from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class EnabledProfileStore(Protocol):
    def load_enabled(
        self,
        *,
        source_name: str | None = None,
    ) -> Sequence[object]: ...

    def load_observation_tail_scope_ids(
        self,
        *,
        source_name: str,
        tail_seconds: float,
    ) -> Sequence[str]: ...


@dataclass(frozen=True)
class PollingScopeSelection:
    active_scope_ids: frozenset[str]
    tail_scope_ids: frozenset[str]

    @property
    def scope_ids(self) -> frozenset[str]:
        return self.active_scope_ids | self.tail_scope_ids


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

    def active_scope_ids(self) -> frozenset[str]:
        """Return only scopes whose profiles are enabled and in-window."""

        profiles = tuple(
            self._profile_store.load_enabled(
                source_name=self.source_name,
            )
        )
        scopes: set[str] = set()
        for profile in profiles:
            scope_id = str(
                getattr(profile, "scope_id", "") or ""
            ).strip()
            if not scope_id:
                raise ValueError(
                    "enabled profile is missing scope_id"
                )
            scopes.add(scope_id)
        return frozenset(scopes)

    def polling_scope_selection(
        self,
        *,
        observation_tail_seconds: float = 0,
    ) -> PollingScopeSelection:
        tail_seconds = float(observation_tail_seconds)
        if tail_seconds < 0:
            raise ValueError(
                "observation_tail_seconds cannot be negative"
            )
        active = self.active_scope_ids()
        if tail_seconds == 0:
            return PollingScopeSelection(
                active_scope_ids=active,
                tail_scope_ids=frozenset(),
            )
        tail = frozenset(
            normalized
            for scope_id in (
                self._profile_store.load_observation_tail_scope_ids(
                    source_name=self.source_name,
                    tail_seconds=tail_seconds,
                )
            )
            if (normalized := str(scope_id or "").strip())
        )
        return PollingScopeSelection(
            active_scope_ids=active,
            tail_scope_ids=tail - active,
        )
