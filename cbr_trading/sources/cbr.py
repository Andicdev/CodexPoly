from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Protocol

from cbr_trading.client import DiscoveryResult
from cbr_trading.domain.signals import ResolutionSignal, SignalEvidence
from cbr_trading.release import classify_change, parse_datetime


CBR_SOURCE_NAME = "cbr"
CBR_KEY_RATE_SUBJECT = "central_bank:CBR:key_rate"
CBR_KEY_RATE_TARGET_METRIC = "central_bank.policy_rate.target"


class CbrDiscoveryClient(Protocol):
    def run_once(self) -> DiscoveryResult: ...


class CbrResolutionSource:
    """Adapt the tested CBR poller to the source-neutral Source contract."""

    source_name = CBR_SOURCE_NAME

    def __init__(
        self,
        discovery_client: CbrDiscoveryClient,
        *,
        previous_rate_provider: Callable[[], Decimal | float | None],
        clock: Callable[[], datetime] | None = None,
    ):
        self._discovery_client = discovery_client
        self._previous_rate_provider = previous_rate_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def poll_once(self) -> tuple[ResolutionSignal, ...]:
        discovery = self._discovery_client.run_once()
        if not discovery.ok or discovery.new_rate is None:
            return ()
        signal = resolution_signal_from_discovery(
            discovery,
            previous_rate=self._previous_rate_provider(),
            detected_at=self._clock(),
        )
        return (signal,) if signal is not None else ()


def resolution_signal_from_discovery(
    discovery: DiscoveryResult,
    *,
    previous_rate: Decimal | float | None,
    detected_at: datetime,
) -> ResolutionSignal | None:
    """Convert only a final, parseable CBR publication into a domain signal."""

    if not discovery.ok or discovery.new_rate is None:
        return None

    canonical_url = str(discovery.url or "").strip()
    if not canonical_url:
        raise ValueError("published CBR discovery result has no canonical URL")

    current_rate = Decimal(str(discovery.new_rate))
    previous = (
        Decimal(str(previous_rate))
        if previous_rate is not None
        else None
    )
    _, direction = classify_change(
        float(previous) if previous is not None else None,
        float(current_rate),
    )
    title = str(discovery.title or "").strip()
    preview = str(discovery.raw_preview or "").strip()

    return ResolutionSignal(
        signal_id=_signal_id(canonical_url),
        source=CBR_SOURCE_NAME,
        subject=CBR_KEY_RATE_SUBJECT,
        metric=CBR_KEY_RATE_TARGET_METRIC,
        value=current_rate,
        previous_value=previous,
        unit="percent",
        direction=direction,
        confidence=Decimal("1"),
        detected_at=detected_at,
        published_at=parse_datetime(discovery.published_at),
        evidence=(
            SignalEvidence(
                source_url=canonical_url,
                title=title or None,
                fingerprint=_evidence_fingerprint(title or preview),
                excerpt=preview or title or None,
            ),
        ),
        attributes={
            "discovery_reason": discovery.reason,
            "detected_from": discovery.detected_from,
            "status_code": discovery.status_code,
            "content_type": discovery.content_type,
        },
    )


def _signal_id(canonical_url: str) -> str:
    digest = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    return f"cbr:key_rate:{digest}"


def _evidence_fingerprint(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
