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


APPLE_CIK = "320193"
APPLE_Q3_2026_CONDITION_ID = (
    "0x48af8cf39c8f44b70f951255fb29a956"
    "f2093e8596defc9a7da87e52c8464377"
)
_APPLE_NEWSROOM_FEED = "https://www.apple.com/newsroom/rss-feed.rss"
_ACCOUNTING_EPS = (
    r"(?P<value>"
    r"\(\s*\$?\s*\d+(?:\.\d+)?\s*\)"
    r"|-\s*\$?\s*\d+(?:\.\d+)?"
    r"|\$?\s*\d+(?:\.\d+)?"
    r")"
)


class AppleGaapDilutedEpsParser(LabelledEpsParser):
    """Parse Apple's current-quarter GAAP diluted EPS headline."""

    _HEADLINE = re.compile(
        r"\b(?:quarterly\s+)?diluted\s+earnings\s+per\s+share"
        r"\s+(?:was|were|of)\s+"
        + _ACCOUNTING_EPS
        + r"\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="AAPL",
                cik=APPLE_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="apple_gaap_diluted_eps",
                parser_version="1",
                accepted_reason="official_apple_gaap_diluted_eps",
                missing_reason="apple_gaap_diluted_eps_not_found",
                conflicting_reason=(
                    "conflicting_apple_gaap_diluted_eps_values"
                ),
                evidence_title="Apple official earnings release",
                resolution_basis=(
                    "current_quarter_headline_gaap_diluted_eps"
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


def aapl_q3_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in configuration for the July 30 Apple GAAP EPS market."""

    rule = EarningsMarketRule(
        rule_key="aapl-2026q3-gaap-eps-1pt89",
        scope_id=earnings_scope_id("AAPL", 2026, 3),
        ticker="AAPL",
        cik=APPLE_CIK,
        fiscal_year=2026,
        fiscal_quarter=3,
        period_end=date(2026, 6, 27),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-30T16:30:00-04:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("1.89"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "aapl-quarterly-earnings-gaap-eps-"
            "07-30-2026-1pt89"
        ),
        condition_id=APPLE_Q3_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "current_quarter_headline_gaap_diluted_eps"
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
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": ["www.apple.com"],
                "feed_url": _APPLE_NEWSROOM_FEED,
                "kind": "rss",
                "provider": "company_ir",
                "title_all": [
                    "Apple",
                    "reports",
                    "third quarter",
                    "results",
                ],
                "title_none": [
                    "conference call",
                    "earnings call",
                ],
            },
        },
    )
