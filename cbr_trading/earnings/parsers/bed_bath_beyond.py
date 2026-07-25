from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from cbr_trading.earnings.contracts import (
    EarningsDocumentCandidate,
    EarningsFactCandidate,
    EarningsMarketRule,
    EarningsMetric,
    EarningsParseResult,
    EpsBasis,
    ParseStatus,
    SourceAuthority,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers._common import (
    ROW_SEPARATOR,
    accounting_values,
    contains_period,
    decode_document,
    document_text,
)


BED_BATH_BEYOND_CIK = "1130713"
BED_BATH_BEYOND_TICKER = "BBBY"
BED_BATH_BEYOND_Q2_2026_CONDITION_ID = (
    "0x2a6affd160ac8d394da6a12d8ff1479e"
    "20e1f6efa22e46001d82ea99665f1045"
)
BED_BATH_BEYOND_PARSER_NAME = (
    "bed_bath_beyond_adjusted_diluted_eps"
)
BED_BATH_BEYOND_PARSER_VERSION = "1"

_RECONCILIATION_PATTERN = re.compile(
    r"reconciliation\s+of\s+diluted\s+net\s+loss\s+per\s+share"
    r"\s+to\s+adjusted\s+diluted\s+net\s+loss\s+per\s+share",
    re.IGNORECASE,
)
_NEXT_SECTION_PATTERN = re.compile(
    r"reconciliation\s+of\s+adjusted\s+ebitda",
    re.IGNORECASE,
)
_PERIOD_BLOCK_PATTERN = re.compile(
    r"three\s+months\s+ended",
    re.IGNORECASE,
)
_NET_LOSS_PER_SHARE_PATTERN = re.compile(
    r"net\s+loss\s+per\s+share\s+of\s+common\s+stock",
    re.IGNORECASE,
)
_DILUTED_ROW_PATTERN = re.compile(r"^\s*diluted\b", re.IGNORECASE)


class BedBathBeyondNonGaapEpsParser:
    """Parse BBBY's current-period adjusted diluted EPS reconciliation."""

    parser_name = BED_BATH_BEYOND_PARSER_NAME
    parser_version = BED_BATH_BEYOND_PARSER_VERSION

    def parse(
        self,
        document: str | bytes,
        *,
        source: EarningsDocumentCandidate,
        rule: EarningsMarketRule,
        detected_at: datetime,
    ) -> EarningsParseResult:
        mismatch = _validate_context(source, rule)
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
        if not contains_period(normalized_text, rule.period_end):
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="fiscal_period_not_confirmed",
            )

        matches = _extract_adjusted_diluted_eps(normalized_text)
        if not matches:
            return EarningsParseResult(
                status=ParseStatus.NO_MATCH,
                reason="bbby_adjusted_diluted_eps_row_not_found",
            )
        distinct_values = {value for value, _ in matches}
        if len(distinct_values) != 1:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="conflicting_bbby_adjusted_eps_rows",
            )
        raw_value = next(iter(distinct_values))
        if raw_value < Decimal("-100") or raw_value > Decimal("100"):
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="eps_value_out_of_range",
            )

        quantum = Decimal(1).scaleb(-rule.rounding_places)
        value = raw_value.quantize(quantum, rounding=ROUND_HALF_UP)
        return EarningsParseResult(
            status=ParseStatus.ACCEPTED,
            reason="official_bbby_adjusted_diluted_eps",
            candidate=EarningsFactCandidate(
                scope_id=rule.scope_id,
                provider=source.provider,
                provider_event_id=source.provider_event_id,
                ticker=rule.ticker,
                cik=rule.cik,
                period_end=rule.period_end,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
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
                evidence_title=(
                    "Bed Bath & Beyond official earnings release"
                ),
                excerpt=matches[0][1],
                attributes={
                    "form_type": source.form_type,
                    "document_type": source.document_type,
                    "transport_fingerprint": (
                        source.transport_fingerprint
                    ),
                },
            ),
        )


def bbby_q2_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in shadow rule using BBBY's official release date."""

    return EarningsMarketRule(
        rule_key="bbby-2026q2-nongaap-eps-neg0pt26",
        scope_id=earnings_scope_id("BBBY", 2026, 2),
        ticker="BBBY",
        cik=BED_BATH_BEYOND_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-08-04T16:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("-0.26"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "bbby-quarterly-earnings-nongaap-eps-"
            "07-27-2026-neg0pt26"
        ),
        condition_id=BED_BATH_BEYOND_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
        },
        fallback_policy={
            "non_gaap_secondary": "seeking_alpha",
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
        },
    )


def _validate_context(
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
        rule.ticker != BED_BATH_BEYOND_TICKER
        or rule.cik != BED_BATH_BEYOND_CIK
    ):
        return "unsupported_bbby_rule"
    if rule.metric is not EarningsMetric.NON_GAAP_EPS:
        return "unsupported_bbby_metric"
    return None


def _extract_adjusted_diluted_eps(
    value: str,
) -> tuple[tuple[Decimal, str], ...]:
    found: list[tuple[Decimal, str]] = []
    starts = tuple(_RECONCILIATION_PATTERN.finditer(value))
    for index, start in enumerate(starts):
        section_end = (
            starts[index + 1].start()
            if index + 1 < len(starts)
            else len(value)
        )
        next_section = _NEXT_SECTION_PATTERN.search(
            value,
            start.end(),
            section_end,
        )
        if next_section is not None:
            section_end = next_section.start()
        section = value[start.end():section_end]
        period_headers = tuple(
            _PERIOD_BLOCK_PATTERN.finditer(section)
        )
        if not period_headers:
            continue
        current_end = (
            period_headers[1].start()
            if len(period_headers) > 1
            else len(section)
        )
        current = section[
            period_headers[0].start():current_end
        ]
        if "adjusted diluted eps" not in current.casefold():
            continue
        per_share = _NET_LOSS_PER_SHARE_PATTERN.search(current)
        if per_share is None:
            continue
        rows = current[per_share.end():].split(ROW_SEPARATOR)
        for row in rows:
            if not _DILUTED_ROW_PATTERN.search(row):
                continue
            values = accounting_values(row)
            if len(values) < 2:
                continue
            found.append((values[-1], row.strip()[:400]))
            break
    return tuple(found)
