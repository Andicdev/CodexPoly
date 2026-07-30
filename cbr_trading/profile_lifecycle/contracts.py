from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


class ProfileTimingBasis(str, Enum):
    OFFICIAL_EXACT = "OFFICIAL_EXACT"
    OFFICIAL_WINDOW = "OFFICIAL_WINDOW"
    HISTORICAL_PATTERN = "HISTORICAL_PATTERN"
    SESSION_FLOOR = "SESSION_FLOOR"


@dataclass(frozen=True)
class ResolutionProfileSchedule:
    schedule_key: str
    profile_key: str
    automation_mode: ProfileAutomationMode
    preflight_at: datetime
    activate_at: datetime
    deactivate_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)
    earliest_signal_at: datetime | None = None
    activation_safety_lead_seconds: int | None = None
    timing_basis: ProfileTimingBasis | None = None
    timing_source_url: str | None = None
    timing_contract_version: int = 0

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
        version = self.timing_contract_version
        if isinstance(version, bool) or version not in (0, 1):
            raise ValueError("timing_contract_version must be 0 or 1")
        object.__setattr__(self, "timing_contract_version", int(version))
        if version == 0:
            if any(
                value is not None
                for value in (
                    self.earliest_signal_at,
                    self.activation_safety_lead_seconds,
                    self.timing_basis,
                    self.timing_source_url,
                )
            ):
                raise ValueError(
                    "timing fields require timing_contract_version=1"
                )
            if self.automation_mode is ProfileAutomationMode.AUTO_LIVE:
                raise ValueError(
                    "AUTO_LIVE requires a versioned timing contract"
                )
        else:
            earliest_signal_at = _as_utc(
                self.earliest_signal_at,
                "earliest_signal_at",
            )
            lead = self.activation_safety_lead_seconds
            if (
                isinstance(lead, bool)
                or not isinstance(lead, int)
                or not 0 <= lead <= 86400
            ):
                raise ValueError(
                    "activation_safety_lead_seconds must be 0..86400"
                )
            if not isinstance(self.timing_basis, ProfileTimingBasis):
                raise TypeError(
                    "timing_basis must be ProfileTimingBasis"
                )
            timing_source_url = str(
                self.timing_source_url or ""
            ).strip()
            if not timing_source_url.startswith("https://"):
                raise ValueError("timing_source_url must use HTTPS")
            latest_activation = earliest_signal_at - timedelta(
                seconds=lead
            )
            if activate_at > latest_activation:
                raise ValueError(
                    "activate_at is later than the earliest-signal "
                    "safety boundary"
                )
            object.__setattr__(
                self,
                "earliest_signal_at",
                earliest_signal_at,
            )
            object.__setattr__(
                self,
                "timing_source_url",
                timing_source_url,
            )
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
