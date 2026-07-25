from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping

from cbr_trading.domain.intents import (
    KeepOpenPolicy,
    OrderSide,
    OrderTemplate,
    Outcome,
    RepriceOnTickChange,
)


@dataclass(frozen=True)
class ResolutionExecutionProfile:
    """Source-neutral configuration for two prepared market outcomes."""

    profile_key: str
    scope_id: str
    source_name: str
    source_reference: str
    account_name: str
    condition_id: str
    yes_desired_price: Decimal
    no_desired_price: Decimal
    quantity: Decimal
    prepare_from: datetime
    expires_at: datetime
    lifecycle_policy: KeepOpenPolicy | RepriceOnTickChange = field(
        default_factory=KeepOpenPolicy
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "profile_key",
            "scope_id",
            "source_name",
            "source_reference",
            "account_name",
            "condition_id",
        ):
            normalized = str(getattr(self, name) or "").strip()
            if not normalized:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, normalized)
        if not self.source_reference.lower().startswith("https://"):
            raise ValueError("source_reference must use https")
        for name in ("yes_desired_price", "no_desired_price"):
            price = Decimal(str(getattr(self, name)))
            if not price.is_finite() or price <= 0 or price >= 1:
                raise ValueError(
                    f"{name} must be finite and between 0 and 1"
                )
            object.__setattr__(self, name, price)
        quantity = Decimal(str(self.quantity))
        if not quantity.is_finite() or quantity <= 0:
            raise ValueError("quantity must be finite and positive")
        object.__setattr__(self, "quantity", quantity)
        prepare_from = _as_utc(self.prepare_from, "prepare_from")
        expires_at = _as_utc(self.expires_at, "expires_at")
        if expires_at <= prepare_from:
            raise ValueError("expires_at must be after prepare_from")
        object.__setattr__(self, "prepare_from", prepare_from)
        object.__setattr__(self, "expires_at", expires_at)
        if not isinstance(
            self.lifecycle_policy,
            (KeepOpenPolicy, RepriceOnTickChange),
        ):
            raise TypeError("unsupported lifecycle_policy")
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


def _as_utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def order_templates_from_profile(
    profile: ResolutionExecutionProfile,
    *,
    strategy_id: str,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[OrderTemplate, OrderTemplate]:
    """Build the alternatives that must both be ready before publication."""

    if not isinstance(profile, ResolutionExecutionProfile):
        raise TypeError(
            "profile must be a ResolutionExecutionProfile"
        )
    normalized_strategy = str(strategy_id or "").strip()
    if not normalized_strategy:
        raise ValueError("strategy_id is required")
    common_metadata = {
        **profile.metadata,
        **dict(metadata or {}),
        "profile_key": profile.profile_key,
        "production_scope_id": profile.scope_id,
    }
    common = {
        "strategy_id": normalized_strategy,
        "account_name": profile.account_name,
        "condition_id": profile.condition_id,
        "side": OrderSide.BUY,
        "quantity": profile.quantity,
        "lifecycle_policy": profile.lifecycle_policy,
        "metadata": common_metadata,
    }
    prefix = f"{normalized_strategy}:{profile.profile_key}"
    return (
        OrderTemplate(
            template_id=f"{prefix}:YES",
            outcome=Outcome.YES,
            desired_price=profile.yes_desired_price,
            **common,
        ),
        OrderTemplate(
            template_id=f"{prefix}:NO",
            outcome=Outcome.NO,
            desired_price=profile.no_desired_price,
            **common,
        ),
    )
