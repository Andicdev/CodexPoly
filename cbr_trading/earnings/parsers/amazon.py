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


AMAZON_CIK = "1018724"
AMAZON_Q2_2026_CONDITION_ID = (
    "0x778f7b1584c2d2585944ac4020dcb187"
    "ac86f4552293ad7dd9bb1c79e458e4fb"
)
_AMAZON_IR_FEED = (
    "https://ir.aboutamazon.com/rss/pressrelease.aspx"
)
_BUSINESSWIRE_EARNINGS_FEED = (
    "https://feed.businesswire.com/rss/home/"
    "?rss=G1QFDERJXkJeGVtQWw=="
)
_QUARTER_LABELS = {
    1: ("first", "1st"),
    2: ("second", "2nd"),
    3: ("third", "3rd"),
    4: ("fourth", "4th"),
}
_ACCOUNTING_EPS = (
    r"(?P<value>"
    r"\(\s*\$?\s*\d+(?:\.\d+)?\s*\)"
    r"|-\s*\$?\s*\d+(?:\.\d+)?"
    r"|\$?\s*\d+(?:\.\d+)?"
    r")"
)


class AmazonGaapDilutedEpsParser(LabelledEpsParser):
    """Parse Amazon's current-quarter GAAP diluted EPS headline."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="AMZN",
                cik=AMAZON_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="amazon_gaap_diluted_eps",
                parser_version="1",
                accepted_reason=(
                    "official_amazon_gaap_diluted_eps"
                ),
                missing_reason=(
                    "amazon_gaap_diluted_eps_not_found"
                ),
                conflicting_reason=(
                    "conflicting_amazon_gaap_diluted_eps_values"
                ),
                evidence_title="Amazon official earnings release",
                resolution_basis=(
                    "current_quarter_net_income_or_loss_per_diluted_share"
                ),
            )
        )

    def _preferred_matches(
        self,
        value: str,
        *,
        rule: EarningsMarketRule,
    ) -> tuple[tuple[Decimal, str], ...]:
        quarter_labels = _QUARTER_LABELS.get(rule.fiscal_quarter)
        if quarter_labels is None:
            return ()
        quarter_choice = "|".join(
            re.escape(label) for label in quarter_labels
        )
        pattern = re.compile(
            r"\bnet\s+(?P<result>income|loss)\b"
            r".{0,220}?"
            r"\b(?:in|for)\s+(?:the\s+)?"
            rf"(?:{quarter_choice})\s+quarter"
            rf"(?:\s+(?:of\s+)?{rule.fiscal_year})?"
            r"\s*,?\s+or\s+"
            + _ACCOUNTING_EPS
            + r"\s+per\s+diluted\s+share\b",
            re.IGNORECASE,
        )
        found: list[tuple[Decimal, str]] = []
        for match in pattern.finditer(value):
            parsed = parse_accounting_decimal(
                match.group("value")
            )
            if (
                match.group("result").casefold() == "loss"
                and parsed > 0
            ):
                parsed = -parsed
            found.append((parsed, match.group(0)[:400]))
        return tuple(found)


def amzn_q2_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in configuration for the July 30 AMZN GAAP EPS market."""

    rule = EarningsMarketRule(
        rule_key="amzn-2026q2-gaap-eps-1pt82",
        scope_id=earnings_scope_id("AMZN", 2026, 2),
        ticker="AMZN",
        cik=AMAZON_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-30T16:01:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("1.82"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "amzn-quarterly-earnings-gaap-eps-"
            "07-30-2026-1pt82"
        ),
        condition_id=AMAZON_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "current_quarter_net_income_or_loss_per_diluted_share"
            ),
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
        },
        fallback_policy={
            "gaap_secondary": "seeking_alpha",
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
    title_all = [
        "Amazon.com",
        "Announces",
        "Second Quarter",
        "Results",
    ]
    title_none = [
        "to Webcast",
        "Conference Call",
    ]
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": [
                    "ir.aboutamazon.com",
                ],
                "feed_url": _AMAZON_IR_FEED,
                "kind": "rss",
                "provider": "company_ir",
                "title_all": title_all,
                "title_none": title_none,
            },
            "press_wire": {
                "allowed_document_hosts": [
                    "www.businesswire.com",
                ],
                "feed_url": _BUSINESSWIRE_EARNINGS_FEED,
                "kind": "rss",
                "provider": "businesswire",
                "title_all": title_all,
                "title_none": title_none,
            },
        },
    )
