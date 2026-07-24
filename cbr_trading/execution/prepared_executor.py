from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from cbr_trading.domain.intents import OrderIntent, OrderTemplate
from cbr_trading.domain.results import OrderExecutionResult
from cbr_trading.domain.signals import ResolutionSignal


class PreparationStatus(str, Enum):
    READY = "READY"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PreparationContext:
    """Stable scope known before publication and shared with idempotency."""

    scope_id: str
    source: str
    source_reference: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("scope_id", "source", "source_reference"):
            normalized = str(getattr(self, name) or "").strip()
            if not normalized:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, normalized)
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(self.attributes)),
        )


@dataclass(frozen=True)
class PreparationItem:
    template_id: str
    status: PreparationStatus
    prepared_key: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        template_id = self.template_id.strip()
        if not template_id:
            raise ValueError("template_id is required")
        object.__setattr__(self, "template_id", template_id)
        if not isinstance(self.status, PreparationStatus):
            object.__setattr__(
                self,
                "status",
                PreparationStatus(str(self.status).upper()),
            )

        prepared_key = str(self.prepared_key or "").strip() or None
        error = str(self.error or "").strip() or None
        if self.status == PreparationStatus.READY and not prepared_key:
            raise ValueError("ready preparation requires prepared_key")
        if self.status == PreparationStatus.FAILED and not error:
            raise ValueError("failed preparation requires error")
        object.__setattr__(self, "prepared_key", prepared_key)
        object.__setattr__(self, "error", error)


@dataclass(frozen=True)
class PreparationSummary:
    items: tuple[PreparationItem, ...]
    context: PreparationContext | None = None

    def __post_init__(self) -> None:
        items = tuple(self.items)
        template_ids = [item.template_id for item in items]
        if len(template_ids) != len(set(template_ids)):
            raise ValueError("preparation summary contains duplicate template ids")
        object.__setattr__(self, "items", items)

    @property
    def ready(self) -> bool:
        return bool(self.items) and all(
            item.status == PreparationStatus.READY
            for item in self.items
        )


class PreparedExecutor(Protocol):
    """Prepare static alternatives first, then submit only selected intents."""

    def prepare(
        self,
        templates: Sequence[OrderTemplate],
        *,
        context: PreparationContext,
    ) -> PreparationSummary: ...

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        signal: ResolutionSignal,
    ) -> Sequence[OrderExecutionResult]: ...

    def close(self) -> None: ...
