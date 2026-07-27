from __future__ import annotations

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


ROYAL_CARIBBEAN_CIK = "884887"
ROYAL_CARIBBEAN_TICKER = "RCL"
ROYAL_CARIBBEAN_Q2_2026_CONDITION_ID = (
    "0x8701e9a10812190db05c6f703b4dd3d8"
    "d978ac171874c78bb26b2f23d7a38976"
)


class RoyalCaribbeanAdjustedEpsParser(LabelledEpsParser):
    """Parse only RCL's primary reported-quarter Adjusted EPS headline."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker=ROYAL_CARIBBEAN_TICKER,
                cik=ROYAL_CARIBBEAN_CIK,
                metric=EarningsMetric.NON_GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(
                    eps_label(
                        r"\breported\s+(?:first|second|third|fourth)"
                        r"\s+quarter\s+earnings\s+per\s+share"
                        r"(?:\s*\([^)]{1,32}\))?\s+of\s+"
                        r"(?:\$\s*)?(?:\(\s*)?-?\d+(?:\.\d+)?"
                        r"(?:\s*\))?\s+and\s+adjusted\s+eps\s+of"
                    ),
                ),
                parser_name="royal_caribbean_adjusted_eps",
                parser_version="1",
                accepted_reason=(
                    "official_royal_caribbean_adjusted_eps"
                ),
                missing_reason=(
                    "royal_caribbean_adjusted_eps_headline_not_found"
                ),
                conflicting_reason=(
                    "conflicting_royal_caribbean_adjusted_eps_values"
                ),
                evidence_title=(
                    "Royal Caribbean Group official earnings release"
                ),
                resolution_basis=(
                    "primary_headline_non_gaap_diluted_eps"
                ),
            )
        )


def rcl_q2_2026_shadow_rule() -> EarningsMarketRule:
    return EarningsMarketRule(
        rule_key="rcl-2026q2-nongaap-eps-3pt97",
        scope_id=earnings_scope_id("RCL", 2026, 2),
        ticker="RCL",
        cik=ROYAL_CARIBBEAN_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-28T06:30:00-04:00"
        ),
        metric=EarningsMetric.NON_GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("3.97"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "rcl-quarterly-earnings-nongaap-eps-"
            "07-28-2026-3pt97"
        ),
        condition_id=ROYAL_CARIBBEAN_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "primary_headline_non_gaap_diluted_eps"
            ),
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
            "company_ir": {
                "kind": "html_listing",
                "provider": "company_ir",
                "feed_url": (
                    "https://www.rclinvestor.com/press-releases/"
                ),
                "listing_utc_offset_minutes": -240,
                "allowed_document_hosts": [
                    "www.rclinvestor.com",
                ],
                "title_all": [
                    "Royal Caribbean Group",
                    "Reports",
                    "Second Quarter",
                    "Results",
                ],
                "title_none": [
                    "to hold",
                    "conference call",
                ],
            },
            "press_wire": {
                "kind": "rss",
                "provider": "prnewswire",
                "feed_url": (
                    "https://www.prnewswire.com/rss/"
                    "news-releases-list.rss"
                ),
                "allowed_document_hosts": [
                    "www.prnewswire.com",
                ],
                "title_all": [
                    "Royal Caribbean Group",
                    "Reports",
                    "Second Quarter",
                    "Results",
                ],
                "title_none": [
                    "to hold",
                    "conference call",
                ],
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
