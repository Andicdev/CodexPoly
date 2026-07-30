from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from cbr_trading.earnings.contracts import (
    EarningsMarketRule,
    EarningsMetric,
    EpsBasis,
    earnings_scope_id,
)
from cbr_trading.earnings.parsers._common import (
    ROW_SEPARATOR,
    accounting_values,
)
from cbr_trading.earnings.parsers._labelled_eps import (
    LabelledEpsParser,
    LabelledEpsParserConfig,
)


ROBLOX_CIK = "1315098"
ROBLOX_Q2_2026_CONDITION_ID = (
    "0xa12716116eb129272d80f3b85a565f3e"
    "d7efe845bb29f46546187a90b986a7b9"
)
_ROBLOX_IR_LISTING = (
    "https://ir.roblox.com/news/default.aspx"
)
_BUSINESSWIRE_EARNINGS_FEED = (
    "https://feed.businesswire.com/rss/home/"
    "?rss=G1QFDERJXkJeGVtQWw=="
)
_GAAP_EPS_ROW = re.compile(
    r"\bnet\s+(?:income|loss)\s+per\s+share\s+"
    r"attributable\s+to\s+common\s+stockholders\s*,?\s*"
    r"basic\s+and\s+diluted\b",
    re.IGNORECASE,
)


class RobloxGaapDilutedEpsParser(LabelledEpsParser):
    """Parse Roblox's current-period GAAP basic-and-diluted EPS row."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="RBLX",
                cik=ROBLOX_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="roblox_gaap_diluted_eps",
                parser_version="2",
                accepted_reason="official_roblox_gaap_diluted_eps",
                missing_reason=(
                    "roblox_gaap_diluted_eps_row_not_found"
                ),
                conflicting_reason=(
                    "conflicting_roblox_gaap_diluted_eps_rows"
                ),
                evidence_title="Roblox official shareholder letter",
                resolution_basis=(
                    "current_period_gaap_basic_and_diluted_eps_row"
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
        found: list[tuple[Decimal, str]] = []
        for row in value.split(ROW_SEPARATOR):
            label = _GAAP_EPS_ROW.search(row)
            if label is None:
                continue
            values = accounting_values(row[label.end():])
            if len(values) < 2:
                continue
            # Roblox presents the current-year quarter first and the
            # prior-year comparator second.
            found.append((values[0], row.strip()[:400]))
        return tuple(found)


def rblx_q2_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in configuration for the July 30 Roblox market."""

    title_all = [
        "Roblox",
        "Second Quarter",
        "2026",
        "Financial Results",
    ]
    title_none = [
        "to Report",
        "Conference Call",
        "Preliminary",
    ]
    return EarningsMarketRule(
        rule_key="rblx-2026q2-gaap-eps-neg0pt33",
        scope_id=earnings_scope_id("RBLX", 2026, 2),
        ticker="RBLX",
        cik=ROBLOX_CIK,
        fiscal_year=2026,
        fiscal_quarter=2,
        period_end=date(2026, 6, 30),
        estimated_release_at=datetime.fromisoformat(
            "2026-07-30T20:00:00+00:00"
        ),
        metric=EarningsMetric.GAAP_EPS,
        primary_basis=EpsBasis.DILUTED,
        fallback_basis=EpsBasis.BASIC,
        comparison_op=">",
        strike=Decimal("-0.33"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "rblx-quarterly-earnings-gaap-eps-"
            "07-30-2026-neg0pt33"
        ),
        condition_id=ROBLOX_Q2_2026_CONDITION_ID,
        source_policy={
            "primary_authority": "official_company",
            "initial_release_only": True,
            "metric_selection": (
                "current_period_gaap_basic_and_diluted_eps_row"
            ),
            "sec": {
                "form_type": "8-K",
                "required_item": "2.02",
                "document_type": "EX-99.1",
            },
            "company_ir": {
                "allowed_document_hosts": [
                    "ir.roblox.com",
                ],
                "feed_url": _ROBLOX_IR_LISTING,
                "kind": "html_listing",
                "listing_utc_offset_minutes": -240,
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
        fallback_policy={
            "gaap_secondary": "seeking_alpha",
            "gaap_after_hours": 96,
            "no_release_after_days": 45,
            "gaap_primary_basis": "diluted",
            "gaap_fallback_basis": "basic",
        },
    )
