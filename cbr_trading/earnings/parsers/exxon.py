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
from cbr_trading.earnings.parsers._labelled_eps import (
    LabelledEpsParser,
    LabelledEpsParserConfig,
    eps_label,
)


EXXONMOBIL_HOLDINGS_CIK = "2115436"
EXXONMOBIL_PREDECESSOR_CIK = "34088"
EXXONMOBIL_Q2_2026_CONDITION_ID = (
    "0x4f47cfcf38650017dfcbf87a05776eb"
    "9692bdfab37d8bd8bcdba8733c7eb0fcd"
)
_EXXONMOBIL_IR_FEED = (
    "https://investor.exxonmobil.com/"
    "company-information/press-releases/rss"
)
_BUSINESSWIRE_EARNINGS_FEED = (
    "https://feed.businesswire.com/rss/home/"
    "?rss=G1QFDERJXkJeGVtQWw=="
)


class ExxonEarningsExcludingItemsEpsParser(LabelledEpsParser):
    """Parse Exxon's primary EPS excluding identified items."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="XOM",
                cik=EXXONMOBIL_HOLDINGS_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\bearnings\s+excluding\s+identified\s+items"
                        r"\s+per\s+common\s+share"
                        r"\s*\(\s*non[\s-]?gaap\s*\)"
                        r"(?:\s*[¹²³⁴⁵⁶⁷⁸⁹⁰\d*]+)?"
                    ),
                    eps_label(
                        r"\bearnings\s+excluding\s+identified\s+items"
                        r"\s+(?:were|was)\s+"
                        r"\$?\s*\d+(?:\.\d+)?\s*"
                        r"(?:billion|million)\s*,?\s+or\b"
                    ),
                ),
                parser_name=(
                    "exxon_earnings_excluding_identified_items_eps"
                ),
                parser_version="1",
                accepted_reason=(
                    "official_exxon_earnings_excluding_items_eps"
                ),
                missing_reason=(
                    "exxon_earnings_excluding_items_eps_not_found"
                ),
                conflicting_reason=(
                    "conflicting_exxon_earnings_excluding_items_eps"
                ),
                evidence_title="ExxonMobil official earnings release",
                resolution_basis=(
                    "earnings_excluding_identified_items_per_common_share"
                ),
                forbidden_prefixes=(
                    "guidance",
                    "outlook",
                ),
                forbidden_tails=(
                    "guidance",
                    "outlook",
                ),
            )
        )


def xom_q2_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in configuration for the July 31 XOM non-GAAP market."""

    rule = EarningsMarketRule(
        rule_key="xom-2026q2-nongaap-eps-3pt66",
        scope_id=earnings_scope_id("XOM", 2026, 2),
        ticker="XOM",
        cik=EXXONMOBIL_HOLDINGS_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-31T05:30:00-05:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("3.66"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "xom-quarterly-earnings-nongaap-eps-"
            "07-31-2026-3pt66"
        ),
        condition_id=EXXONMOBIL_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "earnings_excluding_identified_items_per_common_share"
            ),
            "issuer_successor_effective_date": "2026-07-01",
            "predecessor_cik": EXXONMOBIL_PREDECESSOR_CIK,
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
    title_all = [
        "ExxonMobil",
        "Announces",
        "Second",
        "Quarter",
        "2026",
        "Results",
    ]
    title_none = [
        "to Release",
        "Earnings Call",
        "Earnings Considerations",
        "Preliminary",
    ]
    return replace(
        rule,
        source_policy={
            **rule.source_policy,
            "company_ir": {
                "allowed_document_hosts": [
                    "investor.exxonmobil.com",
                ],
                "feed_url": _EXXONMOBIL_IR_FEED,
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


__all__ = [
    "EXXONMOBIL_HOLDINGS_CIK",
    "EXXONMOBIL_PREDECESSOR_CIK",
    "EXXONMOBIL_Q2_2026_CONDITION_ID",
    "ExxonEarningsExcludingItemsEpsParser",
    "xom_q2_2026_shadow_rule",
]
