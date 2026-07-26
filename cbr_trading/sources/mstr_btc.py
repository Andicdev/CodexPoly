from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal

from cbr_trading.domain.signals import ResolutionSignal, SignalEvidence
from cbr_trading.mstr_btc.contracts import (
    MstrBtcActivity,
    MstrBtcFactCandidate,
    MstrBtcResolutionRule,
    MstrBtcValueDerivation,
)
from cbr_trading.mstr_btc.parser import (
    HOLDINGS_CROSSCHECK_TOLERANCE_BTC,
    MSTR_CIK,
    MSTR_TICKER,
)


MSTR_BTC_SOURCE_NAME = "mstr_btc_resolution"
MSTR_BTC_ACQUIRED_METRIC = "company.mstr.bitcoin.acquired"
MSTR_BTC_SOLD_METRIC = "company.mstr.bitcoin.sold"


def mstr_btc_signal_subject(weekly_scope_id: str) -> str:
    """Return the stable source-neutral subject for one MSTR week."""

    normalized = str(weekly_scope_id or "").strip()
    if not normalized:
        raise ValueError("weekly_scope_id is required")
    return f"company:{MSTR_TICKER}:bitcoin:{normalized}"


def mstr_btc_signal_metric(activity: MstrBtcActivity) -> str:
    """Map a market activity to the metric emitted by this source."""

    if not isinstance(activity, MstrBtcActivity):
        raise TypeError("activity must be MstrBtcActivity")
    return (
        MSTR_BTC_ACQUIRED_METRIC
        if activity is MstrBtcActivity.ACQUIRED
        else MSTR_BTC_SOLD_METRIC
    )


class MstrBtcResolutionSource:
    """Fan one canonical weekly holdings fact into market-scoped signals."""

    source_name = MSTR_BTC_SOURCE_NAME

    def __init__(
        self,
        *,
        candidate_provider: Callable[
            [],
            Sequence[MstrBtcFactCandidate],
        ],
        rules: Sequence[MstrBtcResolutionRule],
    ):
        rows = tuple(rules)
        if not rows:
            raise ValueError("at least one MSTR BTC rule is required")
        signal_ids = [rule.signal_id for rule in rows]
        if len(signal_ids) != len(set(signal_ids)):
            raise ValueError("MSTR BTC signal_ids must be unique")
        self._candidate_provider = candidate_provider
        self._rules = rows
        self._emitted_signal_ids: set[str] = set()
        self._quarantine_reasons: dict[str, str] = {}

    @property
    def quarantine_reasons(self) -> Mapping[str, str]:
        return dict(self._quarantine_reasons)

    def poll_once(self) -> tuple[ResolutionSignal, ...]:
        candidates = tuple(self._candidate_provider())
        if any(
            not isinstance(candidate, MstrBtcFactCandidate)
            for candidate in candidates
        ):
            raise TypeError(
                "candidate_provider must return "
                "MstrBtcFactCandidate objects"
            )
        grouped: dict[str, list[MstrBtcFactCandidate]] = defaultdict(
            list
        )
        for candidate in candidates:
            grouped[candidate.scope_id].append(candidate)

        signals: list[ResolutionSignal] = []
        for weekly_scope_id in sorted(grouped):
            scope_rules = tuple(
                rule
                for rule in self._rules
                if rule.weekly_scope_id == weekly_scope_id
            )
            if not scope_rules:
                continue
            selected = _canonical_fact(grouped[weekly_scope_id])
            if isinstance(selected, str):
                for rule in scope_rules:
                    self._quarantine_reasons[rule.signal_id] = selected
                continue
            for rule in scope_rules:
                if rule.signal_id in self._emitted_signal_ids:
                    continue
                built = resolution_signal_from_mstr_btc_fact(
                    selected,
                    rule=rule,
                )
                if isinstance(built, str):
                    self._quarantine_reasons[rule.signal_id] = built
                    continue
                signals.append(built)
                self._emitted_signal_ids.add(rule.signal_id)
                self._quarantine_reasons.pop(rule.signal_id, None)
        return tuple(signals)

    def close(self) -> None:
        return None


def resolution_signal_from_mstr_btc_fact(
    candidate: MstrBtcFactCandidate,
    *,
    rule: MstrBtcResolutionRule,
) -> ResolutionSignal | str:
    if candidate.scope_id != rule.weekly_scope_id:
        raise ValueError("MSTR BTC candidate does not match rule scope")
    if not _eligible_fact(candidate):
        raise ValueError("MSTR BTC candidate is not eligible")
    activity = _activity_value(candidate, rule=rule)
    if isinstance(activity, str):
        return activity
    value, derivation = activity
    metric = mstr_btc_signal_metric(rule.activity)
    excerpt = (
        candidate.evidence_excerpts[0]
        if candidate.evidence_excerpts
        else None
    )
    return ResolutionSignal(
        signal_id=rule.signal_id,
        source=MSTR_BTC_SOURCE_NAME,
        subject=mstr_btc_signal_subject(candidate.scope_id),
        metric=metric,
        value=Decimal(value),
        unit="BTC",
        confidence=Decimal("1"),
        detected_at=candidate.detected_at,
        published_at=candidate.published_at,
        evidence=(
            SignalEvidence(
                source_url=candidate.source_url,
                title="Strategy BTC Update",
                fingerprint=candidate.document_fingerprint,
                excerpt=excerpt,
            ),
        ),
        attributes={
            "ticker": MSTR_TICKER,
            "cik": MSTR_CIK,
            "weekly_scope_id": candidate.scope_id,
            "rule_key": rule.rule_key,
            "activity": rule.activity.value,
            "comparison_op": rule.comparison_op,
            "threshold_btc": str(rule.threshold_btc),
            "derivation": derivation,
            "explicit_boundary_tolerance_btc": (
                rule.explicit_boundary_tolerance_btc
            ),
            "provider": candidate.provider.value,
            "provider_event_id": candidate.provider_event_id,
            "baseline_state_id": candidate.baseline_state_id,
            "holdings_before_btc": candidate.holdings_before_btc,
            "holdings_after_btc": candidate.holdings_after_btc,
            "net_change_btc": candidate.net_change_btc,
            "filing_url": candidate.filing_url,
            "parser_name": candidate.parser_name,
            "parser_version": candidate.parser_version,
        },
    )


def _canonical_fact(
    candidates: Sequence[MstrBtcFactCandidate],
) -> MstrBtcFactCandidate | str:
    eligible = tuple(
        candidate
        for candidate in candidates
        if _eligible_fact(candidate)
    )
    if not eligible:
        return "no_eligible_official_candidate"
    signatures = {
        (
            candidate.baseline_state_id,
            candidate.holdings_before_btc,
            candidate.holdings_after_btc,
            candidate.acquired_btc,
            candidate.sold_btc,
        )
        for candidate in eligible
    }
    if len(signatures) != 1:
        return "conflicting_official_candidates"
    return min(
        eligible,
        key=lambda item: (
            item.published_at,
            item.provider.value,
            item.provider_event_id,
        ),
    )


def _eligible_fact(candidate: MstrBtcFactCandidate) -> bool:
    return (
        candidate.attributes.get("ticker") == MSTR_TICKER
        and candidate.attributes.get("cik") == MSTR_CIK
        and candidate.holdings_before_btc >= 0
        and candidate.holdings_after_btc >= 0
    )


def _activity_value(
    candidate: MstrBtcFactCandidate,
    *,
    rule: MstrBtcResolutionRule,
) -> tuple[int, str] | str:
    if rule.activity is MstrBtcActivity.ACQUIRED:
        value = candidate.acquired_btc
        derivation = candidate.acquired_derivation
        if value is None and candidate.sold_btc is not None:
            inferred = candidate.net_change_btc + candidate.sold_btc
            if abs(inferred) <= HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
                value = 0
                derivation_name = "crosscheck_zero"
            else:
                return "acquired_quantity_not_confirmed"
        else:
            derivation_name = derivation.value
        if value is None:
            return "acquired_quantity_not_confirmed"
        tolerance = rule.explicit_boundary_tolerance_btc
        if (
            tolerance is not None
            and derivation is not MstrBtcValueDerivation.EXPLICIT
            and abs(Decimal(value) - rule.threshold_btc)
            <= Decimal(tolerance)
        ):
            return "explicit_acquisition_required_near_boundary"
        return value, derivation_name

    value = candidate.sold_btc
    derivation = candidate.sold_derivation
    if value is None and candidate.acquired_btc is not None:
        inferred = candidate.acquired_btc - candidate.net_change_btc
        if abs(inferred) <= HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
            value = 0
            derivation_name = "crosscheck_zero"
        else:
            return "sold_quantity_not_confirmed"
    else:
        derivation_name = derivation.value
    if value is None:
        return "sold_quantity_not_confirmed"
    return value, derivation_name
