from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsMarketRule,
    EarningsMetric,
    EpsBasis,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers._common import (
    parse_accounting_decimal,
)
from cbr_trading.earnings.parsers._labelled_eps import (
    LabelledEpsParser,
    LabelledEpsParserConfig,
)


DOLBY_CIK = "1308547"
DOLBY_Q3_2026_CONDITION_ID = (
    "0x588abaea5b7791fc51f3272a1ff04eb"
    "414ff4078b5840eb9a21ea385717bd43e"
)
_DOLBY_IR_LISTING = (
    "https://investor.dolby.com/news-events/"
    "financial-news/default.aspx"
)
_PRNEWSWIRE_RSS = (
    "https://www.prnewswire.com/rss/news-releases-list.rss"
)
_ACCOUNTING_EPS = (
    r"(?P<value>"
    r"\(\s*\$?\s*\d+(?:\.\d+)?\s*\)"
    r"|-\s*\$?\s*\d+(?:\.\d+)?"
    r"|\$?\s*\d+(?:\.\d+)?"
    r")"
)


class DolbyNonGaapDilutedEpsParser(LabelledEpsParser):
    """Parse Dolby's current-quarter non-GAAP diluted EPS headline."""

    _HEADLINE = re.compile(
        r"\bon\s+a\s+non-gaap\s+basis\s*,?\s*"
        r"(?:the\s+)?(?:first|second|third|fourth)\s+quarter\s+"
        r"net\s+(?:income|loss)\s+was\b"
        r".{0,240}?\bor\s+"
        + _ACCOUNTING_EPS
        + r"\s+per\s+diluted\s+share\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="DLB",
                cik=DOLBY_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="dolby_non_gaap_diluted_eps",
                parser_version="1",
                accepted_reason=(
                    "official_dolby_non_gaap_diluted_eps"
                ),
                missing_reason=(
                    "dolby_non_gaap_diluted_eps_not_found"
                ),
                conflicting_reason=(
                    "conflicting_dolby_non_gaap_diluted_eps_values"
                ),
                evidence_title=(
                    "Dolby Laboratories official earnings release"
                ),
                resolution_basis=(
                    "current_quarter_headline_non_gaap_diluted_eps"
                ),
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        del rule
        return tuple(
            (
                parse_accounting_decimal(match.group("value")),
                match.group(0)[:400],
            )
            for match in self._HEADLINE.finditer(value)
        )


def dlb_q3_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in configuration for the July 30 Dolby market."""

    rule = EarningsMarketRule(
        rule_key="dlb-2026q3-nongaap-eps-0pt67",
        scope_id=earnings_scope_id("DLB", 2026, 3),
        ticker="DLB",
        cik=DOLBY_CIK,
        fiscal_year=2026,
        fiscal_quarter=3,
        period_end=date(2026, 6, 26),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-30T20:15:00+00:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("0.67"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "dlb-quarterly-earnings-nongaap-eps-"
            "07-30-2026-0pt67"
        ),
        condition_id=DOLBY_Q3_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "current_quarter_headline_non_gaap_diluted_eps"
            ),
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
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": ["investor.dolby.com"],
                "feed_url": _DOLBY_IR_LISTING,
                "kind": "html_listing",
                "listing_utc_offset_minutes": -240,
                "provider": "company_ir",
                "title_all": [
                    "Dolby Laboratories",
                    "Reports",
                    "Third Quarter",
                    "Financial Results",
                ],
                "title_none": [
                    "conference call",
                    "webcast",
                ],
            },
            "press_wire": {
                "allowed_document_hosts": ["www.prnewswire.com"],
                "feed_url": _PRNEWSWIRE_RSS,
                "kind": "rss",
                "provider": "prnewswire",
                "title_all": [
                    "Dolby Laboratories",
                    "Reports",
                    "Third Quarter",
                    "Financial Results",
                ],
                "title_none": [
                    "conference call",
                    "webcast",
                ],
            },
        },
    )
