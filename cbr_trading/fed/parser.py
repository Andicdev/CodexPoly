from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser

from cbr_trading.fed.contracts import FedRateDecision


FED_PARSER_NAME = "fed_fomc_target_range"
FED_PARSER_VERSION = "1"

_RATE_TOKEN = (
    r"(?:\d+(?:\.\d+)?(?:\s*-\s*[13]\s*/\s*[24])?"
    r"|\d+\s+[13]\s*/\s*[24]"
    r"|[13]\s*/\s*[24]"
    r"|\d+[¼½¾])"
)
_TARGET_RANGE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        (
            r"target\s+range\s+for\s+the\s+federal\s+funds\s+rate"
            r"(?:\s+at|\s+of|\s+in)?\s+"
            rf"(?P<lower>{_RATE_TOKEN})"
            r"\s*(?:percent|%)?\s+to\s+"
            rf"(?P<upper>{_RATE_TOKEN})"
            r"\s*(?:percent|%)"
        ),
        (
            r"federal\s+funds\s+rate\s+in\s+a\s+target\s+range"
            r"\s+of\s+"
            rf"(?P<lower>{_RATE_TOKEN})"
            r"\s*(?:percent|%)?\s+to\s+"
            rf"(?P<upper>{_RATE_TOKEN})"
            r"\s*(?:percent|%)"
        ),
        (
            r"(?:committee\s+decided\s+to\s+)?"
            r"(?:lower|raise|increase|decrease)\s+the\s+target\s+range"
            r"\s+for\s+the\s+federal\s+funds\s+rate"
            rf"(?:\s+by\s+{_RATE_TOKEN}\s*"
            r"(?:percentage\s+point|percent|basis\s+points?))?"
            r"\s*,?\s+to\s+"
            rf"(?P<lower>{_RATE_TOKEN})"
            r"\s*(?:percent|%)?\s+to\s+"
            rf"(?P<upper>{_RATE_TOKEN})"
            r"\s*(?:percent|%)"
        ),
    )
)
_UNICODE_FRACTIONS = {
    "¼": Decimal("0.25"),
    "½": Decimal("0.5"),
    "¾": Decimal("0.75"),
}


class FedDecisionParseError(ValueError):
    """The document is not an unambiguous scheduled FOMC decision."""


def html_visible_text(document: bytes | str) -> str:
    if isinstance(document, bytes):
        decoded = document.decode("utf-8", errors="replace")
    else:
        decoded = str(document)
    parser = _VisibleTextParser()
    parser.feed(decoded)
    parser.close()
    return " ".join(parser.parts)


def parse_fomc_target_range(
    document_text: str,
    *,
    expected_release_date: date,
) -> FedRateDecision:
    normalized = _normalized_text(document_text)
    if not _contains_release_date(
        normalized,
        expected_release_date,
    ):
        raise FedDecisionParseError(
            "FOMC document does not contain the expected release date"
        )
    decisions: set[tuple[Decimal, Decimal]] = set()
    for pattern in _TARGET_RANGE_PATTERNS:
        for match in pattern.finditer(normalized):
            try:
                lower = _parse_rate(match.group("lower"))
                upper = _parse_rate(match.group("upper"))
                decision = FedRateDecision(lower=lower, upper=upper)
            except (ArithmeticError, ValueError):
                continue
            decisions.add((decision.lower, decision.upper))
    if not decisions:
        raise FedDecisionParseError(
            "FOMC target range was not found"
        )
    if len(decisions) != 1:
        raise FedDecisionParseError(
            "FOMC document contains conflicting target ranges"
        )
    lower, upper = next(iter(decisions))
    return FedRateDecision(lower=lower, upper=upper)


def _parse_rate(value: str) -> Decimal:
    token = re.sub(r"\s+", "", str(value or ""))
    if not token:
        raise ValueError("rate token is empty")
    for symbol, fraction in _UNICODE_FRACTIONS.items():
        if symbol not in token:
            continue
        whole = token.replace(symbol, "")
        return Decimal(whole or "0") + fraction
    mixed = re.fullmatch(
        r"(?:(?P<whole>\d+(?:\.\d+)?)-)?"
        r"(?P<numerator>[13])/(?P<denominator>[24])",
        token,
    )
    if mixed:
        whole = Decimal(mixed.group("whole") or "0")
        fraction = (
            Decimal(mixed.group("numerator"))
            / Decimal(mixed.group("denominator"))
        )
        return whole + fraction
    return Decimal(token)


def _normalized_text(value: str) -> str:
    return " ".join(
        str(value or "")
        .replace("\u00a0", " ")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .split()
    )


def _contains_release_date(
    document: str,
    expected: date,
) -> bool:
    month = expected.strftime("%B")
    variants = (
        f"{month} {expected.day}, {expected.year}",
        f"{month} {expected.day} {expected.year}",
        expected.isoformat(),
    )
    normalized = document.casefold()
    return any(variant.casefold() in normalized for variant in variants)


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
        del attrs
        if tag.casefold() in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if (
            tag.casefold() in {"script", "style", "noscript"}
            and self._ignored_depth
        ):
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        normalized = " ".join(data.split())
        if normalized:
            self.parts.append(normalized)
