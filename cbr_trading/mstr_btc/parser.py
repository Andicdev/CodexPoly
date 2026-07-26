from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser

from cbr_trading.mstr_btc.contracts import (
    MstrBtcDocumentCandidate,
    MstrBtcFactCandidate,
    MstrBtcHoldingsBaseline,
    MstrBtcParseResult,
    MstrBtcParseStatus,
    MstrBtcProvider,
    MstrBtcValueDerivation,
)


MSTR_CIK = "1050446"
MSTR_TICKER = "MSTR"
MSTR_BTC_PARSER_NAME = "mstr_btc_holdings_first"
MSTR_BTC_PARSER_VERSION = "1"
HOLDINGS_CROSSCHECK_TOLERANCE_BTC = 1

_ROW_SEPARATOR = "__MSTR_BTC_ROW__"
_CELL_SEPARATOR = "__MSTR_BTC_CELL__"
_BTC_HEADING_PATTERN = re.compile(r"\bBTC\s+Updates?\b", re.IGNORECASE)
_BLOCK_END_PATTERNS = (
    re.compile(r"\bATM\s+Update\b", re.IGNORECASE),
    re.compile(r"\bUSD\s+Reserve\b", re.IGNORECASE),
    re.compile(r"\bItem\s+7\.01\b", re.IGNORECASE),
    re.compile(r"\bItem\s+9\.01\b", re.IGNORECASE),
    re.compile(r"\bSIGNATURES?\b", re.IGNORECASE),
)
_HOLDINGS_LABEL_PATTERN = re.compile(
    r"\bAggregate\s+BTC\s+Holdings\b",
    re.IGNORECASE,
)
_HOLDINGS_NARRATIVE_PATTERN = re.compile(
    r"\b(?:held|holds?)\s+(?:approximately\s+)?"
    r"(?P<value>\d{1,3}(?:,\d{3})+|\d+)\s+bitcoins?\b",
    re.IGNORECASE,
)
_ACQUIRED_LABEL_PATTERN = re.compile(r"\bBTC\s+Acquired\b", re.IGNORECASE)
_SOLD_LABEL_PATTERN = re.compile(r"\bBTC\s+Sold\b", re.IGNORECASE)
_INTEGER_PATTERN = re.compile(
    r"(?<![\d.])(?P<value>\d{1,3}(?:,\d{3})+|\d+)(?![\d.])"
)
_INTEGER_CELL_PATTERN = re.compile(
    r"^\s*(?P<value>\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\s*\(\s*\d+\s*\))?\s*$"
)
_ZERO_MARKER_PATTERN = re.compile(
    r"^\s*(?:\$?\s*)?(?:[\u2010-\u2015-]+|N/?A\b)"
    r"(?:\s*\(\s*\d+\s*\))?\s*$",
    re.IGNORECASE,
)
_NO_PURCHASE_PATTERNS = (
    re.compile(r"\bdid\s+not\s+purchase\s+any\s+bitcoin\b", re.IGNORECASE),
    re.compile(r"\bno\s+bitcoin\s+purchases?\s+were\s+made\b", re.IGNORECASE),
    re.compile(r"\bmade\s+no\s+bitcoin\s+purchases?\b", re.IGNORECASE),
    re.compile(r"\bdid\s+not\s+acquire\s+any\s+bitcoin\b", re.IGNORECASE),
)
_NO_SALE_PATTERNS = (
    re.compile(r"\bdid\s+not\s+sell\s+any\s+bitcoin\b", re.IGNORECASE),
    re.compile(r"\bno\s+bitcoin\s+sales?\s+were\s+made\b", re.IGNORECASE),
    re.compile(r"\bmade\s+no\s+bitcoin\s+sales?\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class _ExplicitOperation:
    value: int | None
    label_count: int
    malformed_count: int
    excerpts: tuple[str, ...]


class MstrBtc8KParser:
    """Extract BTC activity using final holdings as the stable anchor."""

    parser_name = MSTR_BTC_PARSER_NAME
    parser_version = MSTR_BTC_PARSER_VERSION

    def parse(
        self,
        document: str | bytes,
        *,
        source: MstrBtcDocumentCandidate,
        baseline: MstrBtcHoldingsBaseline,
        detected_at: datetime,
    ) -> MstrBtcParseResult:
        mismatch = _validate_context(source, baseline)
        if mismatch:
            return _result(MstrBtcParseStatus.QUARANTINED, mismatch)
        try:
            raw_document = _decode_document(document)
        except ValueError:
            return _result(
                MstrBtcParseStatus.QUARANTINED,
                "document_encoding_invalid",
            )
        normalized_text = _document_text(raw_document)
        if not normalized_text:
            return _result(
                MstrBtcParseStatus.NO_MATCH,
                "document_is_empty",
            )
        block = _btc_update_block(normalized_text)
        if block is None:
            return _result(
                MstrBtcParseStatus.NO_MATCH,
                "btc_update_block_not_found",
            )

        holdings_matches = _extract_holdings(block)
        if not holdings_matches:
            return _result(
                MstrBtcParseStatus.QUARANTINED,
                "aggregate_btc_holdings_not_found",
            )
        holdings_after, holdings_excerpt = holdings_matches[-1]
        holdings_before = baseline.holdings_btc
        net_change = holdings_after - holdings_before

        acquired = _extract_explicit_operation(
            block,
            label_pattern=_ACQUIRED_LABEL_PATTERN,
            no_activity_patterns=_NO_PURCHASE_PATTERNS,
        )
        sold = _extract_explicit_operation(
            block,
            label_pattern=_SOLD_LABEL_PATTERN,
            no_activity_patterns=_NO_SALE_PATTERNS,
        )
        if acquired.malformed_count:
            return _result(
                MstrBtcParseStatus.QUARANTINED,
                "btc_acquired_value_malformed",
            )
        if sold.malformed_count:
            return _result(
                MstrBtcParseStatus.QUARANTINED,
                "btc_sold_value_malformed",
            )

        reconciled = _reconcile_operations(
            net_change=net_change,
            acquired=acquired.value,
            sold=sold.value,
        )
        if isinstance(reconciled, str):
            return _result(MstrBtcParseStatus.QUARANTINED, reconciled)
        (
            acquired_value,
            sold_value,
            acquired_derivation,
            sold_derivation,
            crosscheck_difference,
        ) = reconciled

        excerpts = _deduplicate(
            (
                holdings_excerpt,
                *acquired.excerpts,
                *sold.excerpts,
            )
        )
        fingerprint = hashlib.sha256(
            raw_document.encode("utf-8")
        ).hexdigest()
        candidate = MstrBtcFactCandidate(
            scope_id=source.scope_id,
            provider=source.provider,
            provider_event_id=source.provider_event_id,
            baseline_state_id=baseline.state_id,
            holdings_before_btc=holdings_before,
            holdings_after_btc=holdings_after,
            net_change_btc=net_change,
            acquired_btc=acquired_value,
            sold_btc=sold_value,
            acquired_derivation=acquired_derivation,
            sold_derivation=sold_derivation,
            holdings_crosscheck_difference_btc=crosscheck_difference,
            source_url=source.source_url,
            filing_url=source.filing_url,
            published_at=source.filed_at,
            detected_at=detected_at,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            document_fingerprint=fingerprint,
            evidence_excerpts=excerpts,
            attributes={
                "ticker": source.ticker,
                "cik": source.cik,
                "form_type": source.form_type,
                "transport_fingerprint": source.transport_fingerprint,
                "holdings_match_count": len(holdings_matches),
                "acquired_label_count": acquired.label_count,
                "sold_label_count": sold.label_count,
            },
        )
        return MstrBtcParseResult(
            status=MstrBtcParseStatus.ACCEPTED,
            reason="official_mstr_btc_update",
            candidate=candidate,
        )


def _validate_context(
    source: MstrBtcDocumentCandidate,
    baseline: MstrBtcHoldingsBaseline,
) -> str | None:
    if source.provider is not MstrBtcProvider.SEC:
        return "unsupported_document_provider"
    if source.ticker != MSTR_TICKER or source.cik != MSTR_CIK:
        return "unsupported_mstr_issuer"
    if source.form_type != "8-K":
        return "unsupported_mstr_form_type"
    if baseline.as_of > source.filed_at:
        return "baseline_is_newer_than_document"
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


def _btc_update_block(value: str) -> str | None:
    heading = _BTC_HEADING_PATTERN.search(value)
    if heading is None:
        return None
    end = len(value)
    for pattern in _BLOCK_END_PATTERNS:
        match = pattern.search(value, heading.end())
        if match is not None:
            end = min(end, match.start())
    return value[heading.start():end].strip()


def _extract_holdings(value: str) -> tuple[tuple[int, str], ...]:
    found = list(
        _extract_table_label_values(
            value,
            label_pattern=_HOLDINGS_LABEL_PATTERN,
            allow_zero=False,
        )
    )
    found.extend(
        _extract_plain_label_values(
            value,
            label_pattern=_HOLDINGS_LABEL_PATTERN,
            allow_zero=False,
        )
    )
    if found:
        return tuple(found)
    for match in _HOLDINGS_NARRATIVE_PATTERN.finditer(value):
        found.append(
            (
                _parse_btc_integer(match.group("value")),
                _excerpt(match.group(0)),
            )
        )
    return tuple(found)


def _extract_explicit_operation(
    value: str,
    *,
    label_pattern: re.Pattern[str],
    no_activity_patterns: tuple[re.Pattern[str], ...],
) -> _ExplicitOperation:
    labeled_values = (
        *_extract_table_label_values(
            value,
            label_pattern=label_pattern,
            allow_zero=True,
        ),
        *_extract_plain_label_values(
            value,
            label_pattern=label_pattern,
            allow_zero=True,
        ),
    )
    values = [item for item, _ in labeled_values]
    excerpts = [excerpt for _, excerpt in labeled_values]
    labels = tuple(label_pattern.finditer(value))
    malformed_count = max(0, len(labels) - len(labeled_values))

    no_activity_matches = tuple(
        match
        for pattern in no_activity_patterns
        if (match := pattern.search(value)) is not None
    )
    excerpts.extend(_excerpt(match.group(0)) for match in no_activity_matches)
    if no_activity_matches:
        if any(item > 0 for item in values):
            malformed_count += 1
        elif not values:
            values.append(0)

    return _ExplicitOperation(
        value=sum(values) if values else None,
        label_count=len(labels),
        malformed_count=malformed_count,
        excerpts=_deduplicate(excerpts),
    )


def _reconcile_operations(
    *,
    net_change: int,
    acquired: int | None,
    sold: int | None,
) -> (
    tuple[
        int | None,
        int | None,
        MstrBtcValueDerivation,
        MstrBtcValueDerivation,
        int,
    ]
    | str
):
    explicit_acquired = acquired is not None
    explicit_sold = sold is not None
    if explicit_acquired and explicit_sold:
        difference = net_change - (acquired - sold)
        if abs(difference) > HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
            return "explicit_activity_conflicts_with_holdings"
        return (
            acquired,
            sold,
            MstrBtcValueDerivation.EXPLICIT,
            MstrBtcValueDerivation.EXPLICIT,
            difference,
        )

    if explicit_acquired:
        inferred_sold = acquired - net_change
        if inferred_sold > HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
            return (
                acquired,
                inferred_sold,
                MstrBtcValueDerivation.EXPLICIT,
                MstrBtcValueDerivation.HOLDINGS_DELTA,
                0,
            )
        if inferred_sold < -HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
            return "explicit_purchase_conflicts_with_holdings"
        return (
            acquired,
            None,
            MstrBtcValueDerivation.EXPLICIT,
            MstrBtcValueDerivation.NOT_CONFIRMED,
            net_change - acquired,
        )

    if explicit_sold:
        inferred_acquired = net_change + sold
        if inferred_acquired > HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
            return (
                inferred_acquired,
                sold,
                MstrBtcValueDerivation.HOLDINGS_DELTA,
                MstrBtcValueDerivation.EXPLICIT,
                0,
            )
        if inferred_acquired < -HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
            return "explicit_sale_conflicts_with_holdings"
        return (
            None,
            sold,
            MstrBtcValueDerivation.NOT_CONFIRMED,
            MstrBtcValueDerivation.EXPLICIT,
            net_change + sold,
        )

    if net_change > HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
        return (
            net_change,
            None,
            MstrBtcValueDerivation.HOLDINGS_DELTA,
            MstrBtcValueDerivation.NOT_CONFIRMED,
            0,
        )
    if net_change < -HOLDINGS_CROSSCHECK_TOLERANCE_BTC:
        return (
            None,
            -net_change,
            MstrBtcValueDerivation.NOT_CONFIRMED,
            MstrBtcValueDerivation.HOLDINGS_DELTA,
            0,
        )
    return (
        None,
        None,
        MstrBtcValueDerivation.NOT_CONFIRMED,
        MstrBtcValueDerivation.NOT_CONFIRMED,
        net_change,
    )


def _extract_table_label_values(
    value: str,
    *,
    label_pattern: re.Pattern[str],
    allow_zero: bool,
) -> tuple[tuple[int, str], ...]:
    rows = _table_rows(value)
    found: list[tuple[int, str]] = []
    for row_index, cells in enumerate(rows):
        for column_index, cell in enumerate(cells):
            if label_pattern.search(cell) is None:
                continue
            parsed: int | None = None
            value_cell = ""
            next_nonempty_column = next(
                (
                    index
                    for index in range(column_index + 1, len(cells))
                    if cells[index]
                ),
                len(cells),
            )
            if next_nonempty_column < len(cells):
                candidate = cells[next_nonempty_column]
                parsed = _parse_value_cell(
                    candidate,
                    allow_zero=allow_zero,
                )
                if parsed is not None:
                    value_cell = candidate
            if parsed is None:
                for later_cells in rows[row_index + 1:row_index + 5]:
                    end = min(next_nonempty_column, len(later_cells))
                    for candidate in later_cells[column_index:end]:
                        parsed = _parse_value_cell(
                            candidate,
                            allow_zero=allow_zero,
                        )
                        if parsed is not None:
                            value_cell = candidate
                            break
                    if parsed is not None:
                        break
            if parsed is not None:
                found.append(
                    (
                        parsed,
                        _excerpt(f"{cell} {value_cell}"),
                    )
                )
    return tuple(found)


def _extract_plain_label_values(
    value: str,
    *,
    label_pattern: re.Pattern[str],
    allow_zero: bool,
) -> tuple[tuple[int, str], ...]:
    found: list[tuple[int, str]] = []
    for label in label_pattern.finditer(value):
        row_start = value.rfind(_ROW_SEPARATOR, 0, label.start())
        row_end = value.find(_ROW_SEPARATOR, label.end())
        containing_row = value[
            row_start + len(_ROW_SEPARATOR) if row_start >= 0 else 0:
            row_end if row_end >= 0 else len(value)
        ]
        if _CELL_SEPARATOR in containing_row:
            continue
        tail = value[label.end():label.end() + 180]
        if allow_zero and _ZERO_MARKER_PATTERN.match(tail):
            found.append((0, _excerpt(value[label.start():label.end() + 16])))
            continue
        number = _INTEGER_PATTERN.search(tail)
        if number is None:
            continue
        found.append(
            (
                _parse_btc_integer(number.group("value")),
                _excerpt(value[label.start():label.end() + number.end()]),
            )
        )
    return tuple(found)


def _table_rows(value: str) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for raw_row in value.split(_ROW_SEPARATOR):
        if _CELL_SEPARATOR not in raw_row:
            continue
        raw_cells = raw_row.split(_CELL_SEPARATOR)[1:]
        cells = tuple(_normalize_whitespace(cell) for cell in raw_cells)
        if any(cells):
            rows.append(cells)
    return tuple(rows)


def _parse_value_cell(value: str, *, allow_zero: bool) -> int | None:
    normalized = _normalize_whitespace(value)
    if allow_zero and _ZERO_MARKER_PATTERN.fullmatch(normalized):
        return 0
    match = _INTEGER_CELL_PATTERN.fullmatch(normalized)
    if match is None:
        return None
    return _parse_btc_integer(match.group("value"))


def _parse_btc_integer(value: str) -> int:
    return int(value.replace(",", ""))


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _excerpt(value: str) -> str:
    return _normalize_whitespace(value)[:300]


def _deduplicate(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _result(
    status: MstrBtcParseStatus,
    reason: str,
) -> MstrBtcParseResult:
    return MstrBtcParseResult(status=status, reason=reason)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0
        self._cell_colspans: list[int] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.casefold()
        if normalized in {"script", "style"}:
            self._ignored_depth += 1
        elif normalized == "tr":
            self.parts.append(f" {_ROW_SEPARATOR} ")
        elif normalized in {"td", "th"}:
            attributes = {name.casefold(): value for name, value in attrs}
            try:
                colspan = max(1, int(attributes.get("colspan") or "1"))
            except ValueError:
                colspan = 1
            self._cell_colspans.append(colspan)
            self.parts.append(f" {_CELL_SEPARATOR} ")
        elif normalized in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in {"script", "style"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif normalized == "tr":
            self.parts.append(f" {_ROW_SEPARATOR} ")
        elif normalized in {"td", "th"}:
            colspan = self._cell_colspans.pop() if self._cell_colspans else 1
            for _ in range(colspan - 1):
                self.parts.append(f" {_CELL_SEPARATOR} ")
            self.parts.append(" ")
        elif normalized in {"p", "div", "li"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)
