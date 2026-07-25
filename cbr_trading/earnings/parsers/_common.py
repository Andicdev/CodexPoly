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
    r"\(\s*\d+(?:\.\d+)?\s*\)"
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


def accounting_values(value: str) -> tuple[Decimal, ...]:
    return tuple(
        parse_accounting_decimal(match.group("value"))
        for match in _ACCOUNTING_VALUE_PATTERN.finditer(value)
    )


def parse_accounting_decimal(value: str) -> Decimal:
    normalized = "".join(str(value or "").split())
    negative = normalized.startswith("(") and normalized.endswith(")")
    if negative:
        normalized = normalized[1:-1]
    parsed = Decimal(normalized)
    return -parsed if negative else parsed


def normalize_whitespace(value: str) -> str:
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
