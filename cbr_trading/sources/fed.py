from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING

from cbr_trading.domain.signals import ResolutionSignal, SignalEvidence
from cbr_trading.fed.contracts import (
    FedDecisionSpec,
    FedRateBucket,
)
from cbr_trading.fed.http_source import FedOfficialObservation


FED_SOURCE_NAME = "fed_fomc"
FED_RATE_CHANGE_METRIC = "central_bank.policy_rate.change_bps"


class FedResolutionSource:
    """Expose one shared official FED observation to a coordinator."""

    source_name = FED_SOURCE_NAME

    def __init__(
        self,
        signal_provider: Callable[[], ResolutionSignal | None],
        *,
        scope_id: str | None = None,
    ):
        self._signal_provider = signal_provider
        self._scope_id = str(scope_id or "").strip() or None

    def poll_once(self) -> tuple[ResolutionSignal, ...]:
        signal = self._signal_provider()
        if signal is None:
            return ()
        if self._scope_id is not None:
            signal = replace(signal, signal_id=self._scope_id)
        return (signal,)


def resolution_signal_from_fed_observation(
    observation: FedOfficialObservation,
    *,
    spec: FedDecisionSpec,
) -> ResolutionSignal:
    raw_delta_bps = (
        observation.decision.upper - spec.previous_upper
    ) * Decimal("100")
    normalized_delta_bps = normalize_fed_delta_bps(raw_delta_bps)
    bucket = fed_rate_bucket(normalized_delta_bps)
    direction = (
        "increase"
        if normalized_delta_bps > 0
        else "decrease"
        if normalized_delta_bps < 0
        else "no_change"
    )
    return ResolutionSignal(
        signal_id=(
            f"{spec.decision_id}:change:"
            f"{_decimal_id(normalized_delta_bps)}"
        ),
        source=FED_SOURCE_NAME,
        subject=fed_signal_subject(spec),
        metric=FED_RATE_CHANGE_METRIC,
        value=normalized_delta_bps,
        unit="basis_points",
        direction=direction,
        confidence=Decimal("1"),
        detected_at=observation.detected_at,
        published_at=spec.release_at,
        evidence=(
            SignalEvidence(
                source_url=observation.source_url,
                title="Federal Reserve issues FOMC statement",
                fingerprint=observation.document_fingerprint,
                excerpt=observation.excerpt,
            ),
        ),
        attributes={
            "decision_id": spec.decision_id,
            "provider": observation.provider,
            "previous_lower_percent": str(spec.previous_lower),
            "previous_upper_percent": str(spec.previous_upper),
            "current_lower_percent": str(observation.decision.lower),
            "current_upper_percent": str(observation.decision.upper),
            "raw_delta_bps": str(raw_delta_bps),
            "normalized_delta_bps": str(normalized_delta_bps),
            "bucket": bucket.value,
            "parser_name": "fed_fomc_target_range",
            "parser_version": "1",
        },
    )


def fed_signal_subject(spec: FedDecisionSpec) -> str:
    return f"central_bank:FED:policy_rate:{spec.release_at.date()}"


def normalize_fed_delta_bps(value: Decimal) -> Decimal:
    delta = Decimal(str(value))
    if not delta.is_finite():
        raise ValueError("FED rate delta must be finite")
    if delta == 0:
        return Decimal("0")
    magnitude = abs(delta)
    steps = (magnitude / Decimal("25")).to_integral_value(
        rounding=ROUND_CEILING
    )
    normalized = steps * Decimal("25")
    return normalized if delta > 0 else -normalized


def fed_rate_bucket(delta_bps: Decimal) -> FedRateBucket:
    delta = Decimal(str(delta_bps))
    if delta == 0:
        return FedRateBucket.NO_CHANGE
    if delta == Decimal("25"):
        return FedRateBucket.INCREASE_25
    if delta >= Decimal("50"):
        return FedRateBucket.INCREASE_50_PLUS
    if delta == Decimal("-25"):
        return FedRateBucket.DECREASE_25
    if delta <= Decimal("-50"):
        return FedRateBucket.DECREASE_50_PLUS
    raise ValueError("normalized FED rate delta has no market bucket")


def _decimal_id(value: Decimal) -> str:
    normalized = Decimal(str(value)).normalize()
    return format(normalized, "f").replace("-", "m")
