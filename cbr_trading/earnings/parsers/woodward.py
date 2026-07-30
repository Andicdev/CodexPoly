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


WOODWARD_CIK = "108312"
WOODWARD_TICKER = "WWD"
WOODWARD_Q3_2026_CONDITION_ID = (
    "0x4e84af80ebdd0c2e658c9b29f7a84728"
    "9c758117d9d47382f3bfc5fb0df157ff"
)
WOODWARD_PARSER_NAME = "woodward_gaap_diluted_eps"
WOODWARD_PARSER_VERSION = "2"

_EPS_LABEL_PATTERN = re.compile(
    r"\bearnings\s+per\s+share\s*\(\s*eps\s*\)",
    re.IGNORECASE,
)
_DILUTED_BASIS_PATTERN = re.compile(
    r"all\s+per\s+share\s+amounts\s+are\s+presented\s+"
    r"on\s+a\s+fully\s+diluted\s+basis",
    re.IGNORECASE,
)


class WoodwardGaapEpsParser:
    """Parse Woodward's headline as-reported diluted GAAP EPS row."""

    parser_name = WOODWARD_PARSER_NAME
    parser_version = WOODWARD_PARSER_VERSION

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
        if not _DILUTED_BASIS_PATTERN.search(normalized_text):
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="diluted_basis_not_confirmed",
            )

        matches = _extract_gaap_eps(normalized_text, rule=rule)
        if not matches:
            return EarningsParseResult(
                status=ParseStatus.NO_MATCH,
                reason="woodward_gaap_eps_row_not_found",
            )
        distinct_values = {value for value, _ in matches}
        if len(distinct_values) != 1:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="conflicting_woodward_gaap_eps_rows",
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
            reason="official_woodward_gaap_diluted_eps",
            candidate=EarningsFactCandidate(
                scope_id=rule.scope_id,
                provider=source.provider,
                provider_event_id=source.provider_event_id,
                ticker=rule.ticker,
                cik=rule.cik,
                period_end=rule.period_end,
                metric=EarningsMetric.GAAP_EPS,
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
                    "Woodward official quarterly earnings release"
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


def wwd_q3_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in shadow rule using Woodward's official release date."""

    return EarningsMarketRule(
        rule_key="wwd-2026q3-gaap-eps-2pt42",
        scope_id=earnings_scope_id("WWD", 2026, 3),
        ticker="WWD",
        cik=WOODWARD_CIK,
        fiscal_year=2026,
        fiscal_quarter=3,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-29T16:00:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("2.42"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "wwd-quarterly-earnings-gaap-eps-"
            "07-27-2026-2pt42"
        ),
        condition_id=WOODWARD_Q3_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
            "company_ir": {
                "kind": "wordpress_rest",
                "provider": "company_ir",
                "feed_url": (
                    "https://www.woodward.com/wp-json/wp/v2/"
                    "press-release?per_page=10&orderby=date&"
                    "order=desc&_fields=id,date_gmt,modified_gmt,"
                    "link,slug,title"
                ),
                "allowed_document_hosts": [
                    "www.woodward.com",
                ],
                "title_all": [
                    "Woodward",
                    "Third Quarter",
                    "Fiscal Year 2026",
                    "Results",
                ],
                "title_none": [
                    "conference call",
                    "to report",
                ],
            },
            "press_wire": {
                "kind": "rss",
                "provider": "globenewswire",
                "feed_url": (
                    "https://www.globenewswire.com/RssFeed/"
                    "subjectcode/13-Earnings%20Releases%20And%20"
                    "Operating%20Results/feedTitle/GlobeNewswire%20"
                    "-%20Earnings%20Releases%20And%20Operating%20"
                    "Results"
                ),
                "allowed_document_hosts": [
                    "www.globenewswire.com",
                ],
                "title_all": [
                    "Woodward",
                    "Third Quarter",
                    "Fiscal Year 2026",
                    "Results",
                ],
                "title_none": [
                    "conference call",
                    "to report",
                ],
            },
        },
        fallback_policy={
            "gaap_secondary": "seeking_alpha",
            "secondary_after_hours": 96,
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
    if rule.ticker != WOODWARD_TICKER or rule.cik != WOODWARD_CIK:
        return "unsupported_woodward_rule"
    if rule.metric is not EarningsMetric.GAAP_EPS:
        return "unsupported_woodward_metric"
    return None


def _extract_gaap_eps(
    value: str,
    *,
    rule: EarningsMarketRule,
) -> tuple[tuple[Decimal, str], ...]:
    found: list[tuple[Decimal, str]] = []
    rows = value.split(ROW_SEPARATOR)
    for row_index, row in enumerate(rows):
        label = _EPS_LABEL_PATTERN.search(row)
        if label is None:
            continue
        prefix = row[
            max(0, label.start() - 40):label.start()
        ].casefold()
        if "adjusted" in prefix or "guidance" in row.casefold():
            continue
        values = accounting_values(row[label.end():])
        if not values:
            continue
        if len(values) > 1 and not _has_safe_woodward_layout(
            rows,
            row_index=row_index,
            value_count=len(values),
            rule=rule,
        ):
            continue
        found.append((values[0], row.strip()[:400]))
    return tuple(found)


def _has_safe_woodward_layout(
    rows: list[str],
    *,
    row_index: int,
    value_count: int,
    rule: EarningsMarketRule,
) -> bool:
    if value_count != 2:
        return False
    quarter_names = {
        1: "first",
        2: "second",
        3: "third",
        4: "fourth",
    }
    quarter_name = quarter_names.get(rule.fiscal_quarter)
    if quarter_name is None:
        return False
    header_context = " ".join(
        row.strip()
        for row in rows[max(0, row_index - 8):row_index]
        if row.strip()
    )
    quarter_header = re.search(
        rf"\b{quarter_name}\s+quarter\s+{rule.fiscal_year}\b",
        header_context,
        re.IGNORECASE,
    )
    cumulative_header = re.search(
        rf"\b(?:ytd|year[\s-]*to[\s-]*date|"
        rf"{3 * rule.fiscal_quarter}\s+months\s+ended)\b"
        rf".{{0,80}}\b{rule.fiscal_year}\b",
        header_context,
        re.IGNORECASE,
    )
    return bool(
        quarter_header
        and cumulative_header
        and quarter_header.start() < cumulative_header.start()
    )
