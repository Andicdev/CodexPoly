from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ProfileAutomationMode(str, Enum):
    MANUAL = "MANUAL"
    AUTO_PREFLIGHT = "AUTO_PREFLIGHT"
    AUTO_LIVE = "AUTO_LIVE"


class ProfileScheduleState(str, Enum):
    PENDING = "PENDING"
    PREFLIGHTING = "PREFLIGHTING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ResolutionProfileSchedule:
    schedule_key: str
    profile_key: str
    automation_mode: ProfileAutomationMode
    preflight_at: datetime
    activate_at: datetime
    deactivate_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("schedule_key", "profile_key"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        if not isinstance(self.automation_mode, ProfileAutomationMode):
            object.__setattr__(
                self,
                "automation_mode",
                ProfileAutomationMode(str(self.automation_mode).upper()),
            )
        preflight_at = _as_utc(self.preflight_at, "preflight_at")
        activate_at = _as_utc(self.activate_at, "activate_at")
        deactivate_at = _as_utc(self.deactivate_at, "deactivate_at")
        if preflight_at > activate_at:
            raise ValueError("preflight_at cannot be after activate_at")
        if deactivate_at <= activate_at:
            raise ValueError("deactivate_at must be after activate_at")
        object.__setattr__(self, "preflight_at", preflight_at)
        object.__setattr__(self, "activate_at", activate_at)
        object.__setattr__(self, "deactivate_at", deactivate_at)
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )


@dataclass(frozen=True)
class ProfileScheduleTransition:
    event_id: int
    event_key: str
    schedule_key: str
    profile_key: str
    scope_id: str
    source_reference: str
    automation_mode: ProfileAutomationMode
    previous_state: ProfileScheduleState | None
    next_state: ProfileScheduleState
    event_kind: str
    reason_code: str | None
    activate_at: datetime
    deactivate_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "event_key",
            "schedule_key",
            "profile_key",
            "scope_id",
            "event_kind",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        source_reference = str(self.source_reference or "").strip()
        if not source_reference.lower().startswith("https://"):
            raise ValueError("source_reference must use HTTPS")
        object.__setattr__(
            self,
            "source_reference",
            source_reference,
        )
        object.__setattr__(
            self,
            "activate_at",
            _as_utc(self.activate_at, "activate_at"),
        )
        object.__setattr__(
            self,
            "deactivate_at",
            _as_utc(self.deactivate_at, "deactivate_at"),
        )


@dataclass(frozen=True)
class ProfilePreflightClaim:
    schedule_key: str
    profile_key: str
    request_id: str
    activate_at: datetime
    deactivate_at: datetime

    def __post_init__(self) -> None:
        for name in ("schedule_key", "profile_key", "request_id"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "activate_at",
            _as_utc(self.activate_at, "activate_at"),
        )
        object.__setattr__(
            self,
            "deactivate_at",
            _as_utc(self.deactivate_at, "deactivate_at"),
        )


def _as_utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)
