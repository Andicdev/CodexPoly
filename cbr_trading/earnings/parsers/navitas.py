from __future__ import annotations

import hashlib
import html
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html.parser import HTMLParser

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


NAVITAS_CIK = "1821769"
NAVITAS_TICKER = "NVTS"
NAVITAS_Q2_2026_CONDITION_ID = (
    "0xa9397ae270be6e9dec1cdd1d89b3e122"
    "b2a60647271261cda138bced069f7d9d"
)
NAVITAS_PARSER_NAME = "navitas_reconciliation_eps"
NAVITAS_PARSER_VERSION = "1"
_ROW_SEPARATOR = "__NAVITAS_ROW__"

_ROW_LABEL_PATTERN = re.compile(
    r"non[\s\u2010-\u2015-]*gaap\s+"
    r"net\s+loss\s+per\s+share\s*"
    r"\(\s*basic\s+and\s+diluted\s*\)",
    re.IGNORECASE,
)
_VALUE_PATTERN = re.compile(
    r"(?:\$\s*)?"
    r"(?P<value>"
    r"\(\s*\d+(?:\.\d+)?\s*\)"
    r"|-\s*\d+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?"
    r")"
)


class NavitasEpsParser:
    """Parse Navitas' official non-GAAP EPS reconciliation row."""

    parser_name = NAVITAS_PARSER_NAME
    parser_version = NAVITAS_PARSER_VERSION

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
            raw_document = _decode_document(document)
        except ValueError:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="document_encoding_invalid",
            )
        normalized_text = _document_text(raw_document)
        if not normalized_text:
            return EarningsParseResult(
                status=ParseStatus.NO_MATCH,
                reason="document_is_empty",
            )
        if not _contains_expected_period(normalized_text, rule.period_end):
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="fiscal_period_not_confirmed",
            )

        matches = _extract_values(normalized_text)
        if not matches:
            return EarningsParseResult(
                status=ParseStatus.NO_MATCH,
                reason="navitas_non_gaap_eps_row_not_found",
            )
        distinct_values = {value for value, _ in matches}
        if len(distinct_values) != 1:
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="conflicting_navitas_eps_rows",
            )
        raw_value = next(iter(distinct_values))
        if raw_value < Decimal("-100") or raw_value > Decimal("100"):
            return EarningsParseResult(
                status=ParseStatus.QUARANTINED,
                reason="eps_value_out_of_range",
            )

        quantum = Decimal(1).scaleb(-rule.rounding_places)
        value = raw_value.quantize(quantum, rounding=ROUND_HALF_UP)
        fingerprint = hashlib.sha256(
            raw_document.encode("utf-8")
        ).hexdigest()
        excerpt = matches[0][1]
        candidate = EarningsFactCandidate(
            scope_id=rule.scope_id,
            provider=source.provider,
            provider_event_id=source.provider_event_id,
            ticker=rule.ticker,
            cik=rule.cik,
            period_end=rule.period_end,
            metric=EarningsMetric.NON_GAAP_EPS,
            basis=EpsBasis.BASIC_AND_DILUTED,
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
            document_fingerprint=fingerprint,
            evidence_title=(
                "Navitas Semiconductor official earnings release"
            ),
            excerpt=excerpt,
            attributes={
                "form_type": source.form_type,
                "document_type": source.document_type,
                "transport_fingerprint": source.transport_fingerprint,
            },
        )
        return EarningsParseResult(
            status=ParseStatus.ACCEPTED,
            reason="official_navitas_non_gaap_eps",
            candidate=candidate,
        )


def nvts_q2_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in shadow configuration for the July 27 NVTS market."""

    return EarningsMarketRule(
        rule_key="nvts-2026q2-nongaap-eps-neg0pt04",
        scope_id=earnings_scope_id("NVTS", 2026, 2),
        ticker="NVTS",
        cik=NAVITAS_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-27T17:00:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("-0.04"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "nvts-quarterly-earnings-nongaap-eps-"
            "07-27-2026-neg0pt04"
        ),
        condition_id=NAVITAS_Q2_2026_CONDITION_ID,
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
    if rule.ticker != NAVITAS_TICKER or rule.cik != NAVITAS_CIK:
        return "unsupported_navitas_rule"
    if rule.metric is not EarningsMetric.NON_GAAP_EPS:
        return "unsupported_navitas_metric"
    return None


def _decode_document(document: str | bytes) -> str:
    if isinstance(document, str):
        return document
    if isinstance(document, bytes):
        try:
            return document.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return document.decode("windows-1252")
            except UnicodeDecodeError as exc:
                raise ValueError("unsupported document encoding") from exc
    raise TypeError("document must be str or bytes")


def _document_text(value: str) -> str:
    if "<" not in value or ">" not in value:
        return _normalize_whitespace(html.unescape(value))
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    return _normalize_whitespace(" ".join(parser.parts))


def _contains_expected_period(value: str, period_end: date) -> bool:
    month_name = period_end.strftime("%B")
    day = str(period_end.day)
    year = str(period_end.year)
    pattern = re.compile(
        rf"\b{re.escape(month_name)}\s+0?{day}\s*,?\s+{year}\b",
        re.IGNORECASE,
    )
    return bool(pattern.search(value))


def _extract_values(value: str) -> tuple[tuple[Decimal, str], ...]:
    found: list[tuple[Decimal, str]] = []
    for label in _ROW_LABEL_PATTERN.finditer(value):
        row_start = value.rfind(_ROW_SEPARATOR, 0, label.start())
        prefix = value[
            row_start + len(_ROW_SEPARATOR)
            if row_start >= 0
            else max(0, label.start() - 140):
            label.start()
        ]
        if "average shares outstanding" in prefix.casefold():
            continue
        row_end = value.find(_ROW_SEPARATOR, label.end())
        tail = value[
            label.end():
            row_end if row_end >= 0 else label.end() + 320
        ]
        match = _VALUE_PATTERN.search(tail)
        if match is None:
            continue
        try:
            parsed = _parse_accounting_decimal(match.group("value"))
        except InvalidOperation:
            continue
        excerpt_end = label.end() + match.end()
        excerpt = value[label.start():excerpt_end].strip()
        found.append((parsed, excerpt[:400]))
    return tuple(found)


def _parse_accounting_decimal(value: str) -> Decimal:
    normalized = "".join(str(value or "").split())
    negative = normalized.startswith("(") and normalized.endswith(")")
    if negative:
        normalized = normalized[1:-1]
    parsed = Decimal(normalized)
    return -parsed if negative else parsed


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() in {"script", "style"}:
            self._ignored_depth += 1
        elif tag.casefold() == "tr":
            self.parts.append(f" {_ROW_SEPARATOR} ")
        elif tag.casefold() in {
            "br",
            "p",
            "div",
            "td",
            "th",
            "li",
        }:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif tag.casefold() == "tr":
            self.parts.append(f" {_ROW_SEPARATOR} ")
        elif tag.casefold() in {
            "p",
            "div",
            "td",
            "th",
            "li",
        }:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)
