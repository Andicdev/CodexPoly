from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Sequence

from cbr_trading.client import DiscoveryResult
from cbr_trading.domain.intents import OrderIntent, OrderTemplate
from cbr_trading.domain.results import (
    ExecutionHandle,
    ExecutionStatus,
    OrderExecutionResult,
    PlacedOrder,
)
from cbr_trading.domain.signals import ResolutionSignal
from cbr_trading.execution.prepared_executor import (
    PreparationContext,
    PreparationItem,
    PreparationStatus,
    PreparationSummary,
)
from cbr_trading.live.runner_executor import (
    LivePreparationSummary,
    LivePreparedOrderSummary,
)
from cbr_trading.pipeline import (
    OrderExecutionResult as LegacyOrderExecutionResult,
)
from cbr_trading.pipeline import OrderIntent as LegacyOrderIntent
from cbr_trading.secret_guard import (
    redact_exception,
    redact_sensitive_text,
)
from cbr_trading.sources.cbr import CBR_SOURCE_NAME


class LegacyWarmExecutor(Protocol):
    def prepare(
        self,
        *,
        release_url: str,
        reserve_claims: bool = True,
    ) -> LivePreparationSummary: ...

    def execute(
        self,
        intents: Sequence[LegacyOrderIntent],
        *,
        release: DiscoveryResult,
    ) -> Sequence[LegacyOrderExecutionResult]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class _PreparedTemplate:
    template: OrderTemplate
    legacy: LivePreparedOrderSummary
    prepared_key: str


class CbrWarmPreparedExecutorAdapter:
    """Expose the working CBR warm executor through the universal contract."""

    def __init__(
        self,
        legacy_executor: LegacyWarmExecutor,
        *,
        reserve_claims: bool = True,
    ):
        self._legacy_executor = legacy_executor
        self._reserve_claims = bool(reserve_claims)
        self._context: PreparationContext | None = None
        self._prepared: dict[str, _PreparedTemplate] = {}
        self._prepared_ok = False
        self._execution_started = False
        self._closed = False

    def prepare(
        self,
        templates: Sequence[OrderTemplate],
        *,
        context: PreparationContext,
    ) -> PreparationSummary:
        template_rows = tuple(templates)
        if self._context is not None:
            return _failed_summary(
                template_rows,
                context=context,
                error="adapter_already_prepared",
            )
        self._context = context

        context_error = _validate_context(context)
        if context_error is not None:
            return _failed_summary(
                template_rows,
                context=context,
                error=context_error,
            )
        if not template_rows:
            return PreparationSummary(items=(), context=context)

        try:
            legacy_summary = self._legacy_executor.prepare(
                release_url=context.source_reference,
                reserve_claims=self._reserve_claims,
            )
            prepared = _match_prepared_templates(
                template_rows,
                legacy_summary=legacy_summary,
                context=context,
            )
        except Exception as exc:
            return _failed_summary(
                template_rows,
                context=context,
                error=redact_exception(exc),
            )

        self._prepared = {
            row.template.template_id: row
            for row in prepared
        }
        self._prepared_ok = True
        return PreparationSummary(
            items=tuple(
                PreparationItem(
                    template_id=row.template.template_id,
                    status=PreparationStatus.READY,
                    prepared_key=row.prepared_key,
                )
                for row in prepared
            ),
            context=context,
        )

    def execute(
        self,
        intents: Sequence[OrderIntent],
        *,
        signal: ResolutionSignal,
    ) -> tuple[OrderExecutionResult, ...]:
        intent_rows = tuple(intents)
        if not self._prepared_ok or self._context is None:
            return _skipped_results(intent_rows, "adapter_not_prepared")
        if self._execution_started:
            return _skipped_results(intent_rows, "adapter_already_used")

        signal_error = _validate_signal_scope(
            signal,
            context=self._context,
        )
        if signal_error is not None:
            return _skipped_results(intent_rows, signal_error)

        results: list[OrderExecutionResult | None] = [None] * len(intent_rows)
        selected: list[tuple[int, OrderIntent, _PreparedTemplate]] = []
        legacy_intents: list[LegacyOrderIntent] = []
        for index, intent in enumerate(intent_rows):
            prepared, error = self._match_intent(intent, signal=signal)
            if error is not None or prepared is None:
                results[index] = _skipped_result(
                    intent,
                    error or "prepared_template_missing",
                )
                continue
            selected.append((index, intent, prepared))
            legacy_intents.append(_to_legacy_intent(intent))

        self._execution_started = True
        try:
            legacy_results = tuple(
                self._legacy_executor.execute(
                    legacy_intents,
                    release=_legacy_release(
                        signal,
                        context=self._context,
                    ),
                )
            )
        except Exception as exc:
            error = redact_exception(exc)
            for index, intent, _ in selected:
                results[index] = OrderExecutionResult(
                    intent=intent,
                    status=ExecutionStatus.AMBIGUOUS,
                    attempted=True,
                    error=error,
                )
            return _complete_results(intent_rows, results)

        if len(legacy_results) != len(selected):
            for index, intent, _ in selected:
                results[index] = OrderExecutionResult(
                    intent=intent,
                    status=ExecutionStatus.AMBIGUOUS,
                    attempted=True,
                    error="legacy_batch_result_count_mismatch",
                )
            return _complete_results(intent_rows, results)

        for result_index, (index, intent, prepared) in enumerate(selected):
            results[index] = _from_legacy_result(
                legacy_results[result_index],
                intent=intent,
                prepared=prepared,
                context=self._context,
            )
        return _complete_results(intent_rows, results)

    def _match_intent(
        self,
        intent: OrderIntent,
        *,
        signal: ResolutionSignal,
    ) -> tuple[_PreparedTemplate | None, str | None]:
        if intent.signal_id != signal.signal_id:
            return None, "intent_signal_mismatch"
        prepared = self._prepared.get(intent.template_id)
        if prepared is None:
            return None, "prepared_template_missing"
        template = prepared.template
        if (
            intent.strategy_id != template.strategy_id
            or intent.account_name.casefold()
            != template.account_name.casefold()
            or intent.condition_id.casefold()
            != template.condition_id.casefold()
            or intent.outcome != template.outcome
            or intent.side != template.side
            or intent.quantity != template.quantity
            or intent.notional != template.notional
            or intent.desired_price != template.desired_price
            or intent.time_in_force != template.time_in_force
            or intent.lifecycle_policy != template.lifecycle_policy
        ):
            return None, "prepared_intent_parameters_mismatch"
        return prepared, None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._legacy_executor.close()


def cbr_preparation_context(release_url: str) -> PreparationContext:
    """Build the event scope used by both preparation and the future signal."""

    from cbr_trading.sources.cbr import cbr_signal_id_for_url

    normalized_url = str(release_url or "").strip()
    return PreparationContext(
        scope_id=cbr_signal_id_for_url(normalized_url),
        source=CBR_SOURCE_NAME,
        source_reference=normalized_url,
    )


def _validate_context(context: PreparationContext) -> str | None:
    if context.source.casefold() != CBR_SOURCE_NAME:
        return "unsupported_preparation_source"
    try:
        expected = cbr_preparation_context(context.source_reference)
    except ValueError:
        return "invalid_cbr_source_reference"
    if expected.scope_id != context.scope_id:
        return "preparation_scope_mismatch"
    return None


def _validate_signal_scope(
    signal: ResolutionSignal,
    *,
    context: PreparationContext,
) -> str | None:
    if signal.source.casefold() != CBR_SOURCE_NAME:
        return "prepared_signal_source_mismatch"
    if signal.signal_id != context.scope_id:
        return "prepared_signal_scope_mismatch"
    evidence_urls = {
        item.source_url.strip()
        for item in signal.evidence
    }
    if context.source_reference not in evidence_urls:
        return "prepared_signal_reference_mismatch"
    return None


def _match_prepared_templates(
    templates: Sequence[OrderTemplate],
    *,
    legacy_summary: LivePreparationSummary,
    context: PreparationContext,
) -> tuple[_PreparedTemplate, ...]:
    if legacy_summary.outcome_count != len(templates):
        raise ValueError("legacy preparation outcome count mismatch")
    legacy_by_key: dict[tuple[str, str], LivePreparedOrderSummary] = {}
    for item in legacy_summary.prepared_orders:
        key = (str(item.rule_id), item.outcome.upper())
        if key in legacy_by_key:
            raise ValueError("legacy preparation contains duplicate outcomes")
        legacy_by_key[key] = item
    if len(legacy_by_key) != len(templates):
        raise ValueError("legacy preparation details are incomplete")

    prepared_rows: list[_PreparedTemplate] = []
    for template in templates:
        legacy_rule_id = template.metadata.get("legacy_rule_id")
        key = (str(legacy_rule_id), template.outcome.value)
        legacy = legacy_by_key.get(key)
        if legacy is None:
            raise ValueError(
                f"legacy preparation missing template {template.template_id}"
            )
        if (
            legacy.account_name.casefold()
            != template.account_name.casefold()
            or legacy.condition_id.casefold()
            != template.condition_id.casefold()
            or legacy.outcome.upper() != template.outcome.value
            or legacy.quantity != template.quantity
            or legacy.limit_price != template.desired_price
        ):
            raise ValueError(
                f"legacy preparation mismatch for {template.template_id}"
            )
        prepared_rows.append(
            _PreparedTemplate(
                template=template,
                legacy=legacy,
                prepared_key=(
                    f"{context.scope_id}/{template.template_id}"
                ),
            )
        )
    return tuple(prepared_rows)


def _to_legacy_intent(intent: OrderIntent) -> LegacyOrderIntent:
    return LegacyOrderIntent(
        rule_id=intent.metadata.get("legacy_rule_id"),
        rule_key=str(intent.metadata.get("rule_key") or "default"),
        account_name=intent.account_name,
        condition_id=intent.condition_id,
        action=intent.outcome.value,
        quantity=intent.quantity,
        limit_price=intent.desired_price,
        ready=True,
        reason="selected_from_prepared_template",
    )


def _legacy_release(
    signal: ResolutionSignal,
    *,
    context: PreparationContext,
) -> DiscoveryResult:
    evidence = signal.evidence[0] if signal.evidence else None
    try:
        new_rate = float(Decimal(str(signal.value)))
    except (ArithmeticError, TypeError, ValueError):
        new_rate = None
    return DiscoveryResult(
        ok=True,
        reason="published",
        url=context.source_reference,
        request_url=context.source_reference,
        title=evidence.title if evidence and evidence.title else "",
        new_rate=new_rate,
        raw_preview=evidence.excerpt if evidence and evidence.excerpt else "",
        detected_from="resolution_signal_adapter",
        published_at=(
            signal.published_at.isoformat()
            if signal.published_at is not None
            else None
        ),
    )


def _from_legacy_result(
    legacy: LegacyOrderExecutionResult,
    *,
    intent: OrderIntent,
    prepared: _PreparedTemplate,
    context: PreparationContext,
) -> OrderExecutionResult:
    error = (
        redact_sensitive_text(legacy.error)
        if legacy.error
        else None
    )
    if legacy.success is True and legacy.order_id:
        order = PlacedOrder(
            order_id=str(legacy.order_id),
            asset_id=prepared.legacy.token_id,
            effective_price=prepared.legacy.limit_price,
            quantity=prepared.legacy.quantity,
        )
        handle = ExecutionHandle(
            order_group_id=_order_group_id(
                context.scope_id,
                intent.intent_id,
            ),
            intent_id=intent.intent_id,
            account_name=intent.account_name,
            condition_id=intent.condition_id,
            outcome=intent.outcome,
            asset_id=prepared.legacy.token_id,
            live_order_ids=(order.order_id,),
        )
        return OrderExecutionResult(
            intent=intent,
            status=ExecutionStatus.SUBMITTED,
            attempted=True,
            orders=(order,),
            handle=handle,
            error=error,
        )
    if legacy.success is True:
        return OrderExecutionResult(
            intent=intent,
            status=ExecutionStatus.AMBIGUOUS,
            attempted=True,
            error=error or "accepted_order_id_missing",
        )
    if legacy.attempted and legacy.success is False:
        return OrderExecutionResult(
            intent=intent,
            status=ExecutionStatus.REJECTED,
            attempted=True,
            error=error or "legacy_order_rejected",
        )
    if legacy.attempted:
        return OrderExecutionResult(
            intent=intent,
            status=ExecutionStatus.AMBIGUOUS,
            attempted=True,
            error=error or "legacy_order_result_ambiguous",
        )
    return _skipped_result(
        intent,
        error or str(legacy.status or "legacy_order_skipped").lower(),
    )


def _order_group_id(scope_id: str, intent_id: str) -> str:
    value = f"{scope_id}|{intent_id}".encode("utf-8")
    return f"order-group:{hashlib.sha256(value).hexdigest()}"


def _failed_summary(
    templates: Sequence[OrderTemplate],
    *,
    context: PreparationContext,
    error: str,
) -> PreparationSummary:
    safe_error = redact_sensitive_text(error)
    return PreparationSummary(
        items=tuple(
            PreparationItem(
                template_id=template.template_id,
                status=PreparationStatus.FAILED,
                error=safe_error,
            )
            for template in templates
        ),
        context=context,
    )


def _skipped_result(
    intent: OrderIntent,
    error: str,
) -> OrderExecutionResult:
    return OrderExecutionResult(
        intent=intent,
        status=ExecutionStatus.SKIPPED,
        attempted=False,
        error=redact_sensitive_text(error),
    )


def _skipped_results(
    intents: Sequence[OrderIntent],
    error: str,
) -> tuple[OrderExecutionResult, ...]:
    return tuple(
        _skipped_result(intent, error)
        for intent in intents
    )


def _complete_results(
    intents: Sequence[OrderIntent],
    results: Sequence[OrderExecutionResult | None],
) -> tuple[OrderExecutionResult, ...]:
    return tuple(
        result
        if result is not None
        else _skipped_result(
            intents[index],
            "adapter_result_missing",
        )
        for index, result in enumerate(results)
    )
