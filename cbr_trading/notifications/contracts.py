from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsMarketRule,
)
from cbr_trading.mstr_btc.contracts import MstrBtcFactCandidate
from cbr_trading.profile_lifecycle.contracts import (
    ProfileScheduleState,
    ProfileScheduleTransition,
)
from cbr_trading.secret_guard import redact_sensitive_text


@dataclass(frozen=True)
class SourceEventNotification:
    """One idempotent message emitted after a canonical source event."""

    notification_key: str
    source_name: str
    scope_id: str
    event_kind: str
    message_text: str
    source_url: str

    def __post_init__(self) -> None:
        for name in (
            "notification_key",
            "source_name",
            "scope_id",
            "event_kind",
            "message_text",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        source_url = str(self.source_url or "").strip()
        if not source_url.lower().startswith("https://"):
            raise ValueError("source_url must use HTTPS")
        object.__setattr__(self, "source_url", source_url)


def source_event_notification_from_earnings(
    *,
    candidate: EarningsDocumentCandidate,
    signal: ResolutionSignal,
    rule: EarningsMarketRule,
) -> SourceEventNotification:
    ticker = str(signal.attributes.get("ticker") or candidate.ticker)
    fiscal_year = signal.attributes.get("fiscal_year")
    fiscal_quarter = signal.attributes.get("fiscal_quarter")
    period = (
        f"{fiscal_year}Q{fiscal_quarter}"
        if fiscal_year is not None and fiscal_quarter is not None
        else candidate.scope_id
    )
    # The signal may canonically select an earlier provider. This message
    # describes the transport event that just arrived.
    provider = candidate.provider.value
    outcome = _numeric_outcome(
        signal.value,
        operator=rule.comparison_op,
        threshold=rule.strike,
    )
    lines = [
        "CodexPoly: earnings event confirmed",
        f"Company: {ticker}",
        f"Period: {period}",
        f"Provider: {provider}",
        *_source_document_lines(
            source_url=candidate.source_url,
            filing_url=candidate.filing_url,
        ),
        f"Metric: {signal.metric}",
        f"Value: {signal.value} {signal.unit or ''}".rstrip(),
        (
            f"Rule: value {rule.comparison_op} {rule.strike} "
            f"-> {'YES' if outcome else 'NO'}"
        ),
        f"Scope: {candidate.scope_id}",
        "Trading path and Telegram delivery are decoupled.",
    ]
    message = "\n".join(lines)
    return SourceEventNotification(
        notification_key=(
            f"earnings:{candidate.provider.value}:"
            f"{candidate.provider_event_id}:{candidate.scope_id}"
        ),
        source_name=signal.source,
        scope_id=candidate.scope_id,
        event_kind="earnings",
        message_text=_redact_notification_text(message),
        source_url=candidate.source_url,
    )


def source_event_notification_from_mstr(
    *,
    fact: MstrBtcFactCandidate,
    signals: Sequence[ResolutionSignal],
) -> SourceEventNotification:
    signal_rows = tuple(signals)
    if not signal_rows:
        raise ValueError("at least one signal is required")
    lines = [
        "CodexPoly: MSTR Bitcoin event confirmed",
        f"Provider: {fact.provider.value}",
        *_source_document_lines(
            source_url=fact.source_url,
            filing_url=fact.filing_url,
        ),
        f"Holdings before: {fact.holdings_before_btc:,} BTC",
        f"Holdings after: {fact.holdings_after_btc:,} BTC",
        f"Net change: {fact.net_change_btc:+,} BTC",
        f"Acquired: {_optional_btc(fact.acquired_btc)}",
        f"Sold: {_optional_btc(fact.sold_btc)}",
        f"Market rules evaluated: {len(signal_rows)}",
    ]
    for signal in sorted(
        signal_rows,
        key=lambda item: item.signal_id,
    ):
        operator = str(signal.attributes.get("comparison_op") or "")
        threshold = Decimal(
            str(signal.attributes.get("threshold_btc"))
        )
        outcome = _numeric_outcome(
            signal.value,
            operator=operator,
            threshold=threshold,
        )
        activity = str(
            signal.attributes.get("activity") or signal.metric
        )
        lines.append(
            f"- {activity}: {signal.value} {operator} {threshold} "
            f"-> {'YES' if outcome else 'NO'}"
        )
    lines.extend(
        (
            f"Scope: {fact.scope_id}",
            "Trading path and Telegram delivery are decoupled.",
        )
    )
    message = "\n".join(lines)
    return SourceEventNotification(
        notification_key=(
            f"mstr-btc:{fact.provider.value}:"
            f"{fact.provider_event_id}:{fact.scope_id}"
        ),
        source_name="mstr_btc_resolution",
        scope_id=fact.scope_id,
        event_kind="mstr_btc",
        message_text=_redact_notification_text(message),
        source_url=fact.source_url,
    )


def source_event_notification_from_profile_lifecycle(
    transition: ProfileScheduleTransition,
) -> SourceEventNotification:
    """Describe scheduler eligibility without claiming an order was sent."""

    state_messages = {
        ProfileScheduleState.PREFLIGHTING: (
            "Authenticated preflight requested",
            "Profile status remains DISABLED.",
        ),
        ProfileScheduleState.READY: (
            "Authenticated preflight passed",
            (
                "Profile status remains DISABLED."
                if transition.automation_mode.value == "AUTO_PREFLIGHT"
                else "Profile is ready for its activation window."
            ),
        ),
        ProfileScheduleState.ACTIVE: (
            "Profile enabled",
            (
                "Profile status is ENABLED; the resolution worker may "
                "now accept a matching source signal."
            ),
        ),
        ProfileScheduleState.BLOCKED: (
            "Profile activation blocked",
            "Profile status remains DISABLED.",
        ),
        ProfileScheduleState.EXPIRED: (
            "Profile window finished",
            "Profile status is DISABLED for new signals.",
        ),
    }
    title, eligibility = state_messages[transition.next_state]
    lines = [
        f"CodexPoly: {title}",
        f"Profile: {transition.profile_key}",
        f"Schedule: {transition.schedule_key}",
        f"Mode: {transition.automation_mode.value}",
        f"State: {transition.next_state.value}",
        f"Window opens: {transition.activate_at.isoformat()}",
        f"Window closes: {transition.deactivate_at.isoformat()}",
    ]
    if transition.reason_code:
        lines.append(f"Reason: {transition.reason_code}")
    lines.extend(
        (
            eligibility,
            f"Market: {transition.source_reference}",
        )
    )
    return SourceEventNotification(
        notification_key=transition.event_key,
        source_name="profile_lifecycle",
        scope_id=transition.scope_id,
        event_kind="profile_lifecycle",
        message_text=_redact_notification_text("\n".join(lines)),
        source_url=transition.source_reference,
    )


def _optional_btc(value: int | None) -> str:
    return "not confirmed" if value is None else f"{value:,} BTC"


def _source_document_lines(
    *,
    source_url: str,
    filing_url: str,
) -> tuple[str, ...]:
    lines = [f"Source document: {source_url}"]
    if filing_url != source_url:
        lines.append(f"Filing: {filing_url}")
    return tuple(lines)


def _redact_notification_text(message: str) -> str:
    # Telegram accepts up to 4096 characters. Keep a small safety margin while
    # preserving the line layout and clickable HTTPS URLs.
    return redact_sensitive_text(
        message,
        max_length=4_000,
        preserve_newlines=True,
    )


def _numeric_outcome(
    value: object,
    *,
    operator: str,
    threshold: Decimal,
) -> bool:
    numeric_value = Decimal(str(value))
    comparisons = {
        ">": numeric_value > threshold,
        ">=": numeric_value >= threshold,
        "<": numeric_value < threshold,
        "<=": numeric_value <= threshold,
        "==": numeric_value == threshold,
    }
    try:
        return comparisons[operator]
    except KeyError:
        raise ValueError("unsupported notification comparison") from None
