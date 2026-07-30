from __future__ import annotations

import html
import re
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser


ROW_SEPARATOR = "__EARNINGS_ROW__"
_ACCOUNTING_VALUE_PATTERN = re.compile(
    r"(?:\$\s*)?"
    r"(?P<value>"
    r"\(\s*(?:\$\s*)?\d+(?:\.\d+)?\s*\)"
    r"|-\s*\d+(?:\.\d+)?"
    r"|\d+(?:\.\d+)?"
    r")"
)


def decode_document(document: str | bytes) -> str:
    if isinstance(document, str):
        return document
    if isinstance(document, bytes):
        try:
            return document.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return document.decode("windows-1252")
            except UnicodeDecodeError as exc:
                raise ValueError(
                    "unsupported document encoding"
                ) from exc
    raise TypeError("document must be str or bytes")


def document_text(value: str) -> str:
    if "<" not in value or ">" not in value:
        return normalize_whitespace(html.unescape(value))
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    return normalize_whitespace(" ".join(parser.parts))


def contains_period(value: str, period_end: date) -> bool:
    month_name = period_end.strftime("%B")
    pattern = re.compile(
        rf"\b{re.escape(month_name)}\s+0?{period_end.day}"
        rf"\s*,?\s+{period_end.year}\b",
        re.IGNORECASE,
    )
    return bool(pattern.search(value))


def contains_fiscal_period(
    value: str,
    *,
    period_end: date,
    fiscal_year: int,
    fiscal_quarter: int,
) -> bool:
    if contains_period(value, period_end):
        return True
    quarter_words = {
        1: ("first", "1st", "q1"),
        2: ("second", "2nd", "q2"),
        3: ("third", "3rd", "q3"),
        4: ("fourth", "4th", "q4"),
    }
    choices = "|".join(
        re.escape(item)
        for item in quarter_words[int(fiscal_quarter)]
    )
    quarter_then_year = re.compile(
        rf"\b(?:{choices})\s+quarter\b"
        rf".{{0,80}}\b{int(fiscal_year)}\b",
        re.IGNORECASE,
    )
    year_then_quarter = re.compile(
        rf"\b{int(fiscal_year)}\b"
        rf".{{0,80}}\b(?:{choices})\s+quarter\b",
        re.IGNORECASE,
    )
    return bool(
        quarter_then_year.search(value)
        or year_then_quarter.search(value)
    )


def accounting_values(value: str) -> tuple[Decimal, ...]:
    return tuple(
        parse_accounting_decimal(match.group("value"))
        for match in _ACCOUNTING_VALUE_PATTERN.finditer(value)
    )


def parse_accounting_decimal(value: str) -> Decimal:
    normalized = "".join(str(value or "").split()).replace("$", "")
    negative = normalized.startswith("(") and normalized.endswith(")")
    if negative:
        normalized = normalized[1:-1]
    parsed = Decimal(normalized)
    return -parsed if negative else parsed


def normalize_whitespace(value: str) -> str:
    without_formatting_marks = value.translate(
        {
            ord("\u200b"): None,
            ord("\u200c"): None,
            ord("\u200d"): None,
            ord("\u2060"): None,
            ord("\ufeff"): None,
        }
    )
    return " ".join(
        without_formatting_marks.replace("\xa0", " ").split()
    )


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
        normalized = tag.casefold()
        if normalized in {"script", "style"}:
            self._ignored_depth += 1
        elif normalized == "tr":
            self.parts.append(f" {ROW_SEPARATOR} ")
        elif normalized in {
            "br",
            "p",
            "div",
            "td",
            "th",
            "li",
        }:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in {"script", "style"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif normalized == "tr":
            self.parts.append(f" {ROW_SEPARATOR} ")
        elif normalized in {
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
