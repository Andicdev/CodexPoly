from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Pattern

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EarningsParseResult,
    EpsBasis,
    ParseStatus,
    SourceAuthority,
)
from cbr_trading.earnings.parsers._common import (
    ROW_SEPARATOR,
    accounting_values,
    contains_fiscal_period,
    decode_document,
    document_text,
)


@dataclass(frozen=True)
class LabelledEpsParserConfig:
    ticker: str
    cik: str
    metric: EarningsMetric
    basis: EpsBasis
    label_patterns: tuple[Pattern[str], ...]
    parser_name: str
    parser_version: str
    accepted_reason: str
    missing_reason: str
    conflicting_reason: str
    evidence_title: str
    resolution_basis: str
    forbidden_prefixes: tuple[str, ...] = ()
    forbidden_prefix_lookback: int = 48
    forbidden_tails: tuple[str, ...] = ()


class LabelledEpsParser:
    """Fail-closed parser for a company's explicitly labelled EPS field."""

    def __init__(self, config: LabelledEpsParserConfig):
        self._config = config
        self.parser_name = config.parser_name
        self.parser_version = config.parser_version

    def parse(
        self,
        document: str | bytes,
        *,
        source: EarningsDocumentCandidate,
        rule: EarningsMarketRule,
        detected_at: datetime,
    ) -> EarningsParseResult:
        mismatch = self._validate_context(source, rule)
        if mismatch:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason=mismatch,
            )
        if source.authority is not SourceAuthority.OFFICIAL_COMPANY:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="source_is_not_official_company",
            )
        try:
            raw_document = decode_document(document)
        except ValueError:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="document_encoding_invalid",
            )
        normalized_text = document_text(raw_document)
        if not normalized_text:
            return EarningsParseResult(
                status=ParseStatus.NO_MATCH,
                reason="document_is_empty",
            )
        if not contains_fiscal_period(
            normalized_text,
            period_end=rule.period_end,
            fiscal_year=rule.fiscal_year,
            fiscal_quarter=rule.fiscal_quarter,
        ):
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="fiscal_period_not_confirmed",
            )

        matches = self._preferred_matches(
            normalized_text,
            rule=rule,
        )
        if not matches:
            matches = self._extract_values(normalized_text)
        if not matches:
            return EarningsParseResult(
                status=ParseStatus.NO_MATCH,
                reason=self._config.missing_reason,
            )
        distinct_values = {value for value, _ in matches}
        if len(distinct_values) != 1:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason=self._config.conflicting_reason,
            )
        raw_value = next(iter(distinct_values))
        if raw_value < Decimal("-100") or raw_value > Decimal("100"):
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="eps_value_out_of_range",
            )

        quantum = Decimal(1).scaleb(-rule.rounding_places)
        value = raw_value.quantize(quantum, rounding=ROUND_HALF_UP)
        candidate = EarningsFactCandidate(
            scope_id=rule.scope_id,
            provider=source.provider,
            provider_event_id=source.provider_event_id,
            ticker=rule.ticker,
            cik=rule.cik,
            period_end=rule.period_end,
            metric=self._config.metric,
            basis=self._config.basis,
            currency=rule.currency,
            raw_value=raw_value,
            value=value,
            authority=source.authority,
            source_url=source.source_url,
            filing_url=source.filing_url,
            published_at=source.filed_at,
            detected_at=detected_at,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            confidence=Decimal("1"),
            document_fingerprint=hashlib.sha256(
                raw_document.encode("utf-8")
            ).hexdigest(),
            evidence_title=self._config.evidence_title,
            excerpt=matches[0][1],
            attributes={
                "form_type": source.form_type,
                "document_type": source.document_type,
                "transport_fingerprint": (
                    source.transport_fingerprint
                ),
                "resolution_basis": (
                    self._config.resolution_basis
                ),
            },
        )
        return EarningsParseResult(
            status=ParseStatus.ACCEPTED,
            reason=self._config.accepted_reason,
            candidate=candidate,
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        """Return company-specific current-period matches when available."""

        return ()

    def _validate_context(
        self,
        source: EarningsDocumentCandidate,
        rule: EarningsMarketRule,
    ) -> str | None:
        if source.scope_id != rule.scope_id:
            return "source_scope_mismatch"
        if source.ticker != rule.ticker:
            return "source_ticker_mismatch"
        if source.cik != rule.cik:
            return "source_cik_mismatch"
        if (
            rule.ticker != self._config.ticker
            or rule.cik != self._config.cik
        ):
            return "unsupported_company_rule"
        if rule.metric is not self._config.metric:
            return "unsupported_company_metric"
        if rule.primary_basis is not self._config.basis:
            return "unsupported_company_primary_basis"
        return None

    def _extract_values(
        self,
        value: str,
    ) -> tuple[tuple[Decimal, str], ...]:
        found: list[tuple[Decimal, str]] = []
        for pattern in self._config.label_patterns:
            for label in pattern.finditer(value):
                prefix = value[
                    max(
                        0,
                        label.start()
                        - self._config.forbidden_prefix_lookback,
                    ):
                    label.start()
                ]
                if any(
                    forbidden.casefold() in prefix.casefold()
                    for forbidden in self._config.forbidden_prefixes
                ):
                    continue
                row_end = value.find(ROW_SEPARATOR, label.end())
                tail_end = (
                    row_end
                    if row_end >= 0
                    else min(len(value), label.end() + 96)
                )
                tail = value[label.end():tail_end]
                if any(
                    forbidden.casefold() in tail[:240].casefold()
                    for forbidden in self._config.forbidden_tails
                ):
                    continue
                values = accounting_values(tail)
                if not values:
                    continue
                excerpt = value[label.start():tail_end].strip()[:400]
                found.append((values[0], excerpt))
        return tuple(found)


def eps_label(pattern: str) -> Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)
