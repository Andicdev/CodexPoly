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


RIVIAN_CIK = "1874178"
RIVIAN_Q2_2026_CONDITION_ID = (
    "0xa99739deef61f908379c067815f2b9d5"
    "ba8aab1af77b2a65b216fa12d7e1f751"
)
_RIVIAN_NEWSROOM = "https://rivian.com/newsroom"
_BUSINESSWIRE_EARNINGS_FEED = (
    "https://feed.businesswire.com/rss/home/"
    "?rss=G1QFDERJXkJeGVtQWw=="
)
_GAAP_EPS_ROW = re.compile(
    r"\bnet\s+(?:income|loss)\s+per\s+share\s+"
    r"attributable\s+to\s+class\s+a\s+and\s+class\s+b\s+"
    r"common\s+stockholders\s*,?\s*basic\s+and\s+diluted\b",
    re.IGNORECASE,
)


class RivianGaapDilutedEpsParser(LabelledEpsParser):
    """Parse Rivian's current-period GAAP basic-and-diluted EPS row."""

    def __init__(self) -> None:
        super().__init__(
            LabelledEpsParserConfig(
                ticker="RIVN",
                cik=RIVIAN_CIK,
                metric=EarningsMetric.GAAP_EPS,
                basis=EpsBasis.DILUTED,
                label_patterns=(),
                parser_name="rivian_gaap_diluted_eps",
                parser_version="2",
                accepted_reason="official_rivian_gaap_diluted_eps",
                missing_reason="rivian_gaap_diluted_eps_row_not_found",
                conflicting_reason=(
                    "conflicting_rivian_gaap_diluted_eps_rows"
                ),
                evidence_title="Rivian official earnings release",
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
            # Rivian presents the prior-year quarter first and the
            # current-year quarter second. Q2/Q3 rows then append the
            # prior/current year-to-date pair, so values[-1] is not the
            # quarterly result.
            found.append((values[1], row.strip()[:400]))
        return tuple(found)


def rivn_q2_2026_shadow_rule() -> EarningsMarketRule:
    """Checked-in configuration for the July 30 Rivian market."""

    title_all = [
        "Rivian",
        "Second Quarter",
        "2026",
        "Financial Results",
    ]
    title_none = [
        "Production and Delivery",
        "Sets Date",
        "Preliminary",
    ]
    return EarningsMarketRule(
        rule_key="rivn-2026q2-gaap-eps-neg0pt78",
        scope_id=earnings_scope_id("RIVN", 2026, 2),
        ticker="RIVN",
        cik=RIVIAN_CIK,
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
        strike=Decimal("-0.78"),
        rounding_places=2,
        currency="USD",
        market_slug=(
            "rivn-quarterly-earnings-gaap-eps-"
            "07-30-2026-neg0pt78"
        ),
        condition_id=RIVIAN_Q2_2026_CONDITION_ID,
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
                    "rivian.com",
                    "www.rivian.com",
                ],
                "feed_url": _RIVIAN_NEWSROOM,
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
