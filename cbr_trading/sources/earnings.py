from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from cbr_trading.domain.signals import ResolutionSignal, SignalEvidence
from cbr_trading.earnings.contracts import (
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EpsBasis,
    SourceAuthority,
)


EARNINGS_SOURCE_NAME = "earnings_resolution"
EARNINGS_NON_GAAP_EPS_METRIC = "company.earnings.eps.non_gaap"


class EarningsResolutionSource:
    """Promote validated facts into one event-scoped shadow signal."""

    source_name = EARNINGS_SOURCE_NAME

    def __init__(
        self,
        *,
        candidate_provider: Callable[
            [],
            Sequence[EarningsFactCandidate],
        ],
        rules: Sequence[EarningsMarketRule],
    ):
        rule_rows = tuple(rules)
        if not rule_rows:
            raise ValueError("at least one earnings rule is required")
        scope_ids = [rule.scope_id for rule in rule_rows]
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("earnings rule scope_ids must be unique")
        self._candidate_provider = candidate_provider
        self._rules: Mapping[str, EarningsMarketRule] = {
            rule.scope_id: rule
            for rule in rule_rows
        }
        self._emitted_scopes: set[str] = set()
        self._quarantine_reasons: dict[str, str] = {}

    @property
    def quarantine_reasons(self) -> Mapping[str, str]:
        return dict(self._quarantine_reasons)

    def poll_once(self) -> tuple[ResolutionSignal, ...]:
        candidates = tuple(self._candidate_provider())
        if any(
            not isinstance(candidate, EarningsFactCandidate)
            for candidate in candidates
        ):
            raise TypeError(
                "candidate_provider must return EarningsFactCandidate objects"
            )
        grouped: dict[str, list[EarningsFactCandidate]] = defaultdict(list)
        for candidate in candidates:
            if candidate.scope_id in self._emitted_scopes:
                continue
            grouped[candidate.scope_id].append(candidate)

        signals: list[ResolutionSignal] = []
        for scope_id in sorted(grouped):
            rule = self._rules.get(scope_id)
            if rule is None:
                self._quarantine_reasons[scope_id] = "unknown_scope"
                continue
            accepted = [
                candidate
                for candidate in grouped[scope_id]
                if _candidate_matches_rule(candidate, rule)
            ]
            if not accepted:
                self._quarantine_reasons[
                    scope_id
                ] = "no_eligible_official_candidate"
                continue
            values = {candidate.value for candidate in accepted}
            if len(values) != 1:
                self._quarantine_reasons[
                    scope_id
                ] = "conflicting_official_candidates"
                continue
            selected = min(
                accepted,
                key=lambda item: (
                    item.published_at,
                    item.provider.value,
                    item.provider_event_id,
                ),
            )
            signals.append(
                resolution_signal_from_earnings_fact(
                    selected,
                    rule=rule,
                )
            )
            self._emitted_scopes.add(scope_id)
            self._quarantine_reasons.pop(scope_id, None)
        return tuple(signals)

    def close(self) -> None:
        return None


def resolution_signal_from_earnings_fact(
    candidate: EarningsFactCandidate,
    *,
    rule: EarningsMarketRule,
) -> ResolutionSignal:
    if not _candidate_matches_rule(candidate, rule):
        raise ValueError("earnings candidate does not match rule")
    metric = (
        EARNINGS_NON_GAAP_EPS_METRIC
        if candidate.metric is EarningsMetric.NON_GAAP_EPS
        else "company.earnings.eps.gaap"
    )
    return ResolutionSignal(
        signal_id=rule.scope_id,
        source=EARNINGS_SOURCE_NAME,
        subject=(
            f"company:{rule.ticker}:earnings:"
            f"{rule.fiscal_year}Q{rule.fiscal_quarter}"
        ),
        metric=metric,
        value=candidate.value,
        unit=rule.currency,
        confidence=Decimal("1"),
        detected_at=candidate.detected_at,
        published_at=candidate.published_at,
        evidence=(
            SignalEvidence(
                source_url=candidate.source_url,
                title=candidate.evidence_title,
                fingerprint=candidate.document_fingerprint,
                excerpt=candidate.excerpt,
            ),
        ),
        attributes={
            "ticker": candidate.ticker,
            "cik": candidate.cik,
            "fiscal_year": rule.fiscal_year,
            "fiscal_quarter": rule.fiscal_quarter,
            "period_end": candidate.period_end.isoformat(),
            "eps_basis": candidate.basis.value,
            "currency": candidate.currency,
            "authority": candidate.authority.value,
            "provider": candidate.provider.value,
            "provider_event_id": candidate.provider_event_id,
            "filing_url": candidate.filing_url,
            "parser_name": candidate.parser_name,
            "parser_version": candidate.parser_version,
            "raw_value": str(candidate.raw_value),
        },
    )


def _candidate_matches_rule(
    candidate: EarningsFactCandidate,
    rule: EarningsMarketRule,
) -> bool:
    if candidate.scope_id != rule.scope_id:
        return False
    if candidate.ticker != rule.ticker or candidate.cik != rule.cik:
        return False
    if candidate.period_end != rule.period_end:
        return False
    if candidate.metric is not rule.metric:
        return False
    if candidate.currency != rule.currency:
        return False
    if candidate.authority is not SourceAuthority.OFFICIAL_COMPANY:
        return False
    if candidate.confidence != Decimal("1"):
        return False
    return _basis_is_eligible(candidate.basis, rule.primary_basis)


def _basis_is_eligible(candidate: EpsBasis, required: EpsBasis) -> bool:
    if candidate is required:
        return True
    return (
        required is EpsBasis.DILUTED
        and candidate is EpsBasis.BASIC_AND_DILUTED
    )
